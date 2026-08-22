"""The human queue: what could not be automated, and why.

A batch already decides every document correctly and writes each decision to
`out/runs/<name>.json`. That is enough for a program and not enough for a person: five
stopped invoices become five files somebody has to know to open, in a directory that also
holds the seven that went through fine. This package is the difference between findings
existing and findings being *worked*.

It adds no verification. Every reason in here was decided by `verify/` before this package
saw it. What it adds is the second half of a rejection — the decision that belongs to a
human, and what the system deliberately declined to do on its own. `verify/` states facts
and stays pure; `review/` states consequences. Keeping the two apart is what stops the
checker from growing opinions about workflow, and what lets the guidance be rewritten
without touching a single check.

    build_queue     run records → what needs a person   (pure)
    render_markdown queue → the file a reviewer opens   (pure)
    to_json         queue → the same, for a program     (pure)
    write_queue     the one function here that touches a disk

The split is deliberate: everything that decides anything is testable with fabricated
dictionaries, offline, with no key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from ..config import OUT_DIR, REPO_ROOT, RUNS_DIR, ensure_out_dirs
from .queue import (
    HandledWithoutAPerson,
    ReviewFinding,
    ReviewItem,
    ReviewQueue,
    build_queue,
)
from .reasons import REASONS, Reason, reason_for
from .render import render_markdown, to_json

__all__ = [
    "HandledWithoutAPerson",
    "REASONS",
    "Reason",
    "ReviewFinding",
    "ReviewItem",
    "ReviewQueue",
    "build_queue",
    "load_records",
    "reason_for",
    "render_markdown",
    "to_json",
    "write_queue",
]

QUEUE_MARKDOWN = "review_queue.md"
QUEUE_JSON = "review_queue.json"


def load_records(runs_dir: Path = RUNS_DIR) -> list[dict]:
    """Read back the run records a batch wrote, in the order it wrote them.

    Each record is tagged with the path it came from, so the queue can point a reviewer at
    the full evidence without this package having to know where run records live. The
    batch does the same thing in memory, which is why a regenerated queue is identical to
    the emitted one rather than merely similar.
    """
    if not runs_dir.is_dir():
        return []

    records: list[dict] = []
    for path in sorted(runs_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.setdefault("record_path", relative_to_repo(path))
        records.append(record)
    return records


def relative_to_repo(path: Path) -> str:
    """A path as it should appear in an artifact: repo-relative, forward slashes.

    An absolute Windows path in a file a reviewer reads is noise, and one that leaks a
    developer's home directory into a public repository is worse than noise.
    """
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write_queue(
    records: Sequence[Mapping],
    *,
    generated_at: str | None = None,
    out_dir: Path = OUT_DIR,
) -> tuple[Path, ReviewQueue]:
    """Build the queue from run records and write both renderings.

    Returns the Markdown path and the queue itself, because the caller invariably wants to
    say how many items landed in it and should not have to count them a second time.
    """
    ensure_out_dirs()
    queue = build_queue(records)
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    markdown_path = out_dir / QUEUE_MARKDOWN
    markdown_path.write_text(render_markdown(queue, stamp), encoding="utf-8")

    json_path = out_dir / QUEUE_JSON
    json_path.write_text(
        json.dumps(to_json(queue, stamp), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return markdown_path, queue
