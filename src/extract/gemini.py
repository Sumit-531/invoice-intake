"""The model provider, behind one function.

Deliberately a function and not an abstraction layer. Swapping providers means editing
this file; nothing above it knows which model answered. That is enough to make the choice
of provider genuinely not load-bearing, and an interface with one implementation would be
ceremony rather than design.

Nothing here parses. It returns the response text as it arrived, and the caller persists
it before a schema ever touches it.
"""

from __future__ import annotations

import time

from google import genai
from google.genai import types

from ..config import GEMINI_API_KEY, GEMINI_MODEL, MODEL_TIMEOUT_SECONDS
from ..models import ExtractedInvoice
from .cache import RawResponse, now_iso


class ExtractionCallFailed(RuntimeError):
    """The provider did not return a usable response. Never retried into submission."""


def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ExtractionCallFailed(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and paste a key from "
            "https://aistudio.google.com/apikey (free tier, no card required)."
        )
    return genai.Client(
        api_key=GEMINI_API_KEY,
        # A model call is a network call: explicit timeout, in milliseconds.
        http_options=types.HttpOptions(timeout=MODEL_TIMEOUT_SECONDS * 1000),
    )


def generate(
    prompt: str,
    *,
    source_name: str,
    source_sha256: str,
    prompt_version: str,
) -> RawResponse:
    """One call. Returns the raw text; does not parse it."""
    client = _client()
    started = time.monotonic()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                # The schema is enforced by the provider, so a malformed shape fails at
                # the boundary instead of halfway through the verifier.
                response_mime_type="application/json",
                response_schema=ExtractedInvoice,
                # Transcription, not composition. Nothing here benefits from sampling.
                temperature=0.0,
            ),
        )
    except Exception as exc:  # provider errors are opaque and varied; surface, never swallow
        raise ExtractionCallFailed(f"{type(exc).__name__}: {exc}") from exc

    elapsed = time.monotonic() - started
    text = response.text or ""
    if not text.strip():
        raise ExtractionCallFailed(
            "The provider returned an empty response body "
            f"(finish reason: {_finish_reason(response)})."
        )

    usage = response.usage_metadata
    return RawResponse(
        source_name=source_name,
        source_sha256=source_sha256,
        prompt_version=prompt_version,
        model=GEMINI_MODEL,
        requested_at=now_iso(),
        text=text,
        prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        response_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        total_tokens=getattr(usage, "total_token_count", 0) or 0,
        elapsed_seconds=round(elapsed, 2),
    )


def _finish_reason(response: object) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "no candidates"
    return str(getattr(candidates[0], "finish_reason", "unknown"))
