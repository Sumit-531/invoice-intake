"""The queue as something a person opens, and as something a program reads.

Two renderings of one object, deliberately. The Markdown is the deliverable — a reviewer
opens it, works down it, and never needs the source documents or this codebase to
understand why a document is in front of them. The JSON is the same content with the prose
kept intact, so that the review *screen* this project deliberately did not build has
something to consume the day it is built. The screen was cut; the capability was not
thrown away.

Both are pure functions of the queue and a timestamp. The timestamp is an argument rather
than a `now()` call so that rendering stays deterministic and testable — a function that
reads the clock cannot be compared against an expected string.
"""

from __future__ import annotations

import json

from .queue import ReviewFinding, ReviewItem, ReviewQueue
from .reasons import GROUP_BLURBS, GROUP_HEADINGS

_UNTITLED_GROUP = "Unclassified"


def _yen(value: object) -> str:
    return f"¥{value:,}" if isinstance(value, int) else "not printed"


def _scalar(value: object) -> str:
    """Render one evidence value for a human.

    Integers get thousands separators because every integer in this system is either money
    or a count, and both read better grouped. `bool` is checked first on purpose: it is a
    subclass of `int` in Python, and `True` formatted as `1` would be a small lie in an
    artifact whose entire job is not telling small lies.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if value is None:
        return "(none)"
    return str(value)


def _evidence_lines(evidence: dict) -> list[str]:
    """Evidence as bullets, with anything structured dropped into a JSON block.

    Scalars are what a reviewer actually compares — printed against recomputed — so they
    stay flat and scannable. Nested values (the line table, the per-code tax breakdown)
    are printed in full rather than summarised: this file exists so nobody has to reopen
    the source document, and a truncated line table sends them straight back to it.
    """
    if not evidence:
        return []

    lines: list[str] = ["**Evidence**", ""]
    structured: list[tuple[str, object]] = []

    for key, value in evidence.items():
        if isinstance(value, (dict, list, tuple)):
            structured.append((key, value))
        else:
            lines.append(f"- `{key}`: {_scalar(value)}")

    for key, value in structured:
        lines.extend(
            [
                "",
                f"`{key}`",
                "",
                "```json",
                json.dumps(value, ensure_ascii=False, indent=2),
                "```",
            ]
        )

    lines.append("")
    return lines


def _finding_lines(finding: ReviewFinding) -> list[str]:
    lines = [
        f"#### {finding.code} — {finding.title}",
        "",
        finding.message,
        "",
    ]
    lines.extend(_evidence_lines(finding.evidence))
    lines.extend(
        [
            f"**Your decision.** {finding.decision}",
            "",
            f"**What the system did not do.** {finding.not_done}",
            "",
        ]
    )
    return lines


def _item_lines(item: ReviewItem) -> list[str]:
    route = f"{item.route} route" if item.route else "route not determined"
    lines = [
        f"### `{item.source}` · {route}",
        "",
        "| As read | |",
        "|---|---|",
        f"| Supplier | {item.supplier_as_read or '—'} |",
        f"| Invoice number | {item.invoice_number_as_read or '—'} |",
        f"| Issue date | {item.issue_date_as_read or '—'} |",
        f"| Printed total | {_yen(item.printed_total_as_read)} |",
    ]
    if item.record_path:
        lines.append(f"| Full record | `{item.record_path}` |")
    lines.extend(
        [
            "",
            "Read, not verified — this document is here because verification did not "
            "pass, so nothing above has been confirmed against anything.",
            "",
        ]
    )

    for finding in item.findings:
        lines.extend(_finding_lines(finding))

    return lines


def _summary_sentence(queue: ReviewQueue) -> str:
    if queue.document_count == 0:
        return "**No documents were processed.**"

    parts = [f"{len(queue.registered)} registered"]
    if queue.handled_without_a_person:
        parts.append(
            f"{len(queue.handled_without_a_person)} stopped without needing anyone"
        )

    if not queue.items:
        return (
            f"**Nothing needs a person.** {queue.document_count} document(s) processed — "
            + ", ".join(parts)
            + "."
        )

    return (
        f"**{queue.needs_a_person} of {queue.document_count} document(s) need a person.** "
        + ", ".join(parts)
        + "."
    )


def render_markdown(queue: ReviewQueue, generated_at: str) -> str:
    """The queue as one file a reviewer opens."""
    lines: list[str] = [
        "# Review queue",
        "",
        _summary_sentence(queue),
        "",
        f"Generated {generated_at} by the pipeline, not written by hand. Rebuild it from "
        "the stored run records at any time with `python -m src.review` — that costs no "
        "model requests and does not need the accounting system running.",
        "",
    ]

    if queue.items:
        lines.extend(
            [
                "Every document below stopped **before** anything was sent to the "
                "accounting system. Nothing here was guessed at, quietly corrected, or "
                "registered as a best effort — which is why each item says what the "
                "system declined to do as well as what it found.",
                "",
            ]
        )

    for group, members in queue.by_group():
        lines.extend(
            [
                "---",
                "",
                f"## {GROUP_HEADINGS.get(group, _UNTITLED_GROUP)}  ({len(members)})",
                "",
            ]
        )
        blurb = GROUP_BLURBS.get(group)
        if blurb:
            lines.extend([blurb, ""])
        for item in members:
            lines.extend(_item_lines(item))

    if queue.handled_without_a_person:
        lines.extend(
            [
                "---",
                "",
                "## Stopped without needing a person",
                "",
                "Listed for completeness, not for action. The pipeline reached a correct "
                "decision on these by itself; a reviewer sent to look at one would be "
                "hunting a fault that is not there.",
                "",
            ]
        )
        for handled in queue.handled_without_a_person:
            lines.append(f"- `{handled.source}` — {handled.title} ({handled.code})")
        lines.append("")

    if queue.registered:
        lines.extend(
            [
                "---",
                "",
                "## Registered",
                "",
                "Passed every local check and were accepted by the accounting system: "
                + ", ".join(f"`{source}`" for source in queue.registered)
                + ".",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def to_json(queue: ReviewQueue, generated_at: str) -> dict:
    """The same queue, structured — for whatever consumes it next.

    The prose fields travel with it. A consumer that has the code but not the guidance
    would have to reinvent the wording, and two descriptions of one reason code drift
    apart the moment either is edited.
    """
    return {
        "generated_at": generated_at,
        "document_count": queue.document_count,
        "needs_a_person": queue.needs_a_person,
        "registered": list(queue.registered),
        "handled_without_a_person": [
            {"source": h.source, "code": h.code, "title": h.title}
            for h in queue.handled_without_a_person
        ],
        "items": [
            {
                "source": item.source,
                "route": item.route,
                "outcome": item.outcome,
                "group": item.group,
                "group_heading": GROUP_HEADINGS.get(item.group, _UNTITLED_GROUP),
                "record_path": item.record_path,
                "as_read": {
                    "supplier_name": item.supplier_as_read,
                    "invoice_number": item.invoice_number_as_read,
                    "issue_date": item.issue_date_as_read,
                    "printed_total": item.printed_total_as_read,
                },
                "findings": [
                    {
                        "code": finding.code,
                        "title": finding.title,
                        "message": finding.message,
                        "decision": finding.decision,
                        "not_done": finding.not_done,
                        "evidence": finding.evidence,
                    }
                    for finding in item.findings
                ],
            }
            for item in queue.items
        ],
    }
