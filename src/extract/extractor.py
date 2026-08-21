"""One document in, one typed extraction out — with the raw response on disk either way.

The order of operations in `extract_invoice` is the contract, not an implementation
detail: look in the cache, call only on a miss, **write the response down, then parse**.
A parse failure must leave behind exactly what the model said, or diagnosing it costs
another request against a 20-per-day budget.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from ..models import ExtractedInvoice
from . import cache, gemini
from .cache import RawResponse
from .document import Route, SourceDocument
from .prompt import PROMPT_VERSION, build_prompt


class ExtractionParseFailed(RuntimeError):
    """The response did not fit the schema. The raw text is on disk; look there."""


class RouteNotImplemented(NotImplementedError):
    """This document needs a path that has not been built yet. Not a failure of the
    document, and not something to work around by forcing it down the wrong route."""


@dataclass(frozen=True)
class ExtractionResult:
    invoice: ExtractedInvoice
    raw: RawResponse
    from_cache: bool


def extract_invoice(document: SourceDocument) -> ExtractionResult:
    if document.route is not Route.VISION:
        prompt = build_prompt(document.text)
    else:
        raise RouteNotImplemented(
            f"{document.name} has no usable text layer "
            f"({document.text_char_count} characters) and needs the vision route, "
            "which is not built yet."
        )

    raw = cache.load(document.sha256, PROMPT_VERSION, gemini.GEMINI_MODEL)
    from_cache = raw is not None

    if raw is None:
        raw = gemini.generate(
            prompt,
            source_name=document.name,
            source_sha256=document.sha256,
            prompt_version=PROMPT_VERSION,
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
            f"{cache.cache_path(document.sha256, PROMPT_VERSION, raw.model)}.\n{exc}"
        ) from exc

    return ExtractionResult(invoice=invoice, raw=raw, from_cache=from_cache)
