"""One document in, one typed extraction out — with the raw response on disk either way.

The order of operations in `extract_invoice` is the contract, not an implementation
detail: look in the cache, call only on a miss, **write the response down, then parse**.
A parse failure must leave behind exactly what the model said, or diagnosing it costs
another request against a 20-per-day budget.

ROUTING IS DECIDED UPSTREAM, NOT HERE
`document.route` was set by measuring the text layer. This module only honours it. The
difference between the two routes is which prompt is built and whether page images are
attached — nothing about the caching, the persistence order, or the parsing changes, which
is what keeps a vision extraction as auditable as a text one.

RENDERING HAPPENS ONLY ON A CACHE MISS
The cache is checked before any page is rasterised. Replaying a stored vision response
therefore costs neither a request nor the rendering, which is what makes iterating on the
verifier against the full set free.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from ..models import ExtractedInvoice
from . import cache, gemini
from .cache import RawResponse
from .document import Route, SourceDocument
from .prompt import (
    PROMPT_VERSION,
    VISION_PROMPT_VERSION,
    build_prompt,
    build_vision_prompt,
)
from .render import PageImage, render_pages


class ExtractionParseFailed(RuntimeError):
    """The response did not fit the schema. The raw text is on disk; look there."""


@dataclass(frozen=True)
class ExtractionResult:
    invoice: ExtractedInvoice
    raw: RawResponse
    from_cache: bool


def prompt_version_for(document: SourceDocument) -> str:
    """Which prompt this document will be read with — without building it.

    Split out so the cache can be consulted, and a caller can ask whether a request is
    about to be spent, before anything is rendered or assembled.
    """
    return PROMPT_VERSION if document.route is Route.TEXT else VISION_PROMPT_VERSION


def is_cached(document: SourceDocument) -> bool:
    """True when extracting this document will cost no request.

    Batch pacing needs this: a run that sleeps between cached replays would take minutes
    to do nothing. The pacing lives in the caller rather than here, because a single-file
    run has nothing to pace against and should not wait.
    """
    path = cache.cache_path(
        document.sha256, prompt_version_for(document), gemini.GEMINI_MODEL
    )
    return path.is_file()


def _build_request(document: SourceDocument) -> tuple[str, tuple[PageImage, ...]]:
    if document.route is Route.TEXT:
        return build_prompt(document.text), ()

    images = tuple(render_pages(document.path))
    return build_vision_prompt(len(images)), images


def extract_invoice(document: SourceDocument) -> ExtractionResult:
    prompt_version = prompt_version_for(document)

    raw = cache.load(document.sha256, prompt_version, gemini.GEMINI_MODEL)
    from_cache = raw is not None

    if raw is None:
        prompt, images = _build_request(document)
        raw = gemini.generate(
            prompt,
            source_name=document.name,
            source_sha256=document.sha256,
            prompt_version=prompt_version,
            route=document.route.value,
            images=images,
        )
        # Before parsing. Always. This line is the reason a bad extraction is free to
        # investigate instead of costing another call.
        cache.save(raw)

    try:
        invoice = ExtractedInvoice.model_validate_json(raw.text)
    except ValidationError as exc:
        raise ExtractionParseFailed(
            f"{document.name}: the response did not fit the schema. "
            f"Raw text saved at "
            f"{cache.cache_path(document.sha256, prompt_version, raw.model)}.\n{exc}"
        ) from exc

    return ExtractionResult(invoice=invoice, raw=raw, from_cache=from_cache)
