"""The raw-response cache.

Two rules in CLAUDE.md are served by one mechanism here:

  "Raw model output is persisted before parsing." When something is wrong, the question is
  always what the model actually said — and that answer must not require paying again.

  "A model call is a network call." The free tier allows 20 requests per day. Iterating on
  the *verifier* must never re-pay the *extractor*, or a week's quota disappears into
  re-reading documents that were read correctly the first time.

The key is (file content, prompt version, model). Content-addressed, so the same bytes
under a different filename hit the same entry, and editing the prompt or switching models
correctly misses rather than silently serving a response the current code never asked for.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import RAW_DIR


@dataclass(frozen=True)
class RawResponse:
    """Exactly what came back, plus enough context to reproduce the conditions."""

    source_name: str
    source_sha256: str
    prompt_version: str
    model: str
    requested_at: str
    text: str
    prompt_tokens: int
    response_tokens: int
    total_tokens: int
    elapsed_seconds: float

    # How this response was obtained, for the cost table. Both carry defaults so that an
    # entry written before the vision route existed still loads — a cache that cannot read
    # its own older entries is a cache that silently starts costing requests again.
    route: str = "text"
    page_images: int = 0


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def cache_path(source_sha256: str, prompt_version: str, model: str) -> Path:
    return RAW_DIR / f"{source_sha256[:16]}.{prompt_version}.{_slug(model)}.json"


def load(source_sha256: str, prompt_version: str, model: str) -> RawResponse | None:
    path = cache_path(source_sha256, prompt_version, model)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RawResponse(**payload)


def save(response: RawResponse) -> Path:
    """Write the response to disk. Called before anything attempts to parse it."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(response.source_sha256, response.prompt_version, response.model)
    path.write_text(
        json.dumps(asdict(response), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
