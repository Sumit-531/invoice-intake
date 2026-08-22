"""The review queue, built from fabricated run records.

`review/` decides two things and neither of them is arithmetic: **what needs a person**,
and **which person-shaped problem it is**. Both are policy, and policy that nothing tests
is policy that drifts the first time a reason code is added.

The cases below are the shapes a real batch produces — a document stopped for one reason,
a document stopped for several at once, a duplicate that needs nobody, a file that could
not be opened at all — plus the two that only appear when something has gone wrong: a code
the guidance table has never met, and a document that stopped without recording why. Those
last two matter most. A queue that raises on an unfamiliar finding does not fail loudly,
it fails *silently*, because the item it choked on is the one nobody ever sees.

Offline, no key, no accounting system, no documents. The builder and both renderers are
pure functions of plain dictionaries, which is the entire reason this file is cheap.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from src.review import build_queue, render_markdown, to_json
from src.review.queue import REGISTERED
from src.review.reasons import (
    ALREADY_HANDLED,
    DOCUMENT_UNREADABLE,
    FIGURES,
    HANDWRITING,
    REASONS,
    SUPPLIER,
    UNCLASSIFIED,
    VERIFICATION_GAP,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STAMP = "2026-08-23 03:00"


# ---------------------------------------------------------------------------
# Fabricated run records — the same shape `main.py` writes to out/runs/.
# ---------------------------------------------------------------------------


def finding(code: str, message: str = "Something was wrong.", **evidence) -> dict:
    return {"code": code, "message": message, "evidence": evidence}


def record(source: str, *findings: dict, **overrides) -> dict:
    base = {
        "source": source,
        "route": "vision",
        "outcome": "stopped_locally",
        "record_path": f"out/runs/{Path(source).stem}.json",
        "invoice": {
            "invoice_number": "ABC-001",
            "supplier_name": "株式会社テスト",
            "issue_date": "2026-02-05",
            "printed_total": 594000,
        },
        "findings": list(findings),
    }
    base.update(overrides)
    return base


def registered(source: str) -> dict:
    return record(source, outcome=REGISTERED, findings=[])


def duplicate(source: str) -> dict:
    return record(
        source,
        finding("ALREADY_REGISTERED", "It arrived twice."),
        outcome="already_registered",
    )


# ---------------------------------------------------------------------------
# The guarantee that keeps the table honest
# ---------------------------------------------------------------------------


def test_every_reason_code_verify_can_emit_has_guidance():
    """A check may not ship without deciding who owns its outcome.

    Without this, adding a check to `verify/` silently produces queue items that read
    "stopped by a check with no entry in the guidance table" — technically handled, and a
    reviewer left to work out on their own what the system wants from them.

    The codes are read out of the source rather than listed here on purpose: a list copied
    into a test is a list that agrees with the code exactly until someone edits one of
    them.
    """
    code_shaped = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
    found: set[str] = set()

    for path in (REPO_ROOT / "src" / "verify").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if code_shaped.fullmatch(node.value):
                    found.add(node.value)

    assert found, "no reason codes were found in verify/ — this test has stopped checking"

    missing = sorted(code for code in found if code not in REASONS)
    assert not missing, (
        "verify/ emits reason codes the review queue has no guidance for: "
        f"{missing}. Add them to src/review/reasons.py — a reviewer receiving one of "
        "these would be told what is wrong and not what to do about it."
    )


def test_an_unfamiliar_code_is_surfaced_rather_than_raising():
    """The queue must never be the reason a finding goes unseen."""
    queue = build_queue([record("doc.pdf", finding("A_CODE_FROM_THE_FUTURE"))])

    assert queue.needs_a_person == 1
    item = queue.items[0]
    assert item.group == UNCLASSIFIED
    assert item.findings[0].code == "A_CODE_FROM_THE_FUTURE"
    assert item.findings[0].decision  # guidance is generic, but it is not empty

    markdown = render_markdown(queue, STAMP)
    assert "A_CODE_FROM_THE_FUTURE" in markdown


# ---------------------------------------------------------------------------
# What gets in, and what does not
# ---------------------------------------------------------------------------


def test_a_registered_document_does_not_reach_the_queue():
    queue = build_queue([registered("ok.pdf")])

    assert queue.items == ()
    assert queue.registered == ("ok.pdf",)
    assert queue.document_count == 1


def test_a_stopped_duplicate_needs_nobody_but_is_still_reported():
    """A duplicate is a correct outcome, not a defect.

    Queueing it would send a reviewer looking for a fault that does not exist — and a
    queue that cries wolf stops being read, which costs far more than the one entry saves.
    It is still reported, because a system that quietly did something is never acceptable
    either.
    """
    queue = build_queue([duplicate("second_copy.jpg")])

    assert queue.items == ()
    assert len(queue.handled_without_a_person) == 1
    assert queue.handled_without_a_person[0].source == "second_copy.jpg"

    markdown = render_markdown(queue, STAMP)
    assert "Stopped without needing a person" in markdown
    assert "second_copy.jpg" in markdown


def test_a_duplicate_carrying_a_second_problem_is_queued_after_all():
    """Being a duplicate excuses the duplication, not everything else on the document."""
    queue = build_queue(
        [
            record(
                "awkward.jpg",
                finding("ALREADY_REGISTERED"),
                finding("TAX_MISMATCH"),
            )
        ]
    )

    assert queue.needs_a_person == 1
    assert queue.handled_without_a_person == ()
    assert queue.items[0].group == FIGURES


def test_a_document_that_stopped_without_a_reason_is_surfaced_not_dropped():
    """A record with no findings and no registration is a hole in the pipeline.

    The quiet failure would be to skip it — it satisfies neither branch. It is reported as
    an unclassified item instead, which is the loud one.
    """
    queue = build_queue([record("mystery.pdf", outcome="stopped_locally", findings=[])])

    assert queue.needs_a_person == 1
    assert queue.items[0].group == UNCLASSIFIED
    assert "NO_REASON_RECORDED" in render_markdown(queue, STAMP)


def test_a_file_that_could_not_be_opened_is_queued():
    queue = build_queue(
        [
            record(
                "broken.pdf",
                finding(DOCUMENT_UNREADABLE, "It would not open."),
                outcome="could_not_run",
                invoice={},
            )
        ]
    )

    assert queue.needs_a_person == 1
    item = queue.items[0]
    assert item.supplier_as_read is None
    assert "—" in render_markdown(queue, STAMP)  # the unknown fields render, blank


# ---------------------------------------------------------------------------
# Grouping and ordering
# ---------------------------------------------------------------------------


def test_an_item_is_filed_under_its_most_important_finding():
    """An invoice with a redirected bank account does not get filed under a missing unit."""
    queue = build_queue(
        [
            record(
                "several.jpg",
                finding("LINE_UNIT_MISSING"),
                finding("TAX_MISMATCH"),
                finding("HANDWRITING_ANNOTATION"),
            )
        ]
    )

    item = queue.items[0]
    assert item.group == HANDWRITING
    assert item.findings[0].code == "HANDWRITING_ANNOTATION"
    assert item.findings[-1].code == "LINE_UNIT_MISSING"


def test_groups_appear_in_priority_order_and_only_when_occupied():
    """A heading with nothing under it reads like something was suppressed."""
    queue = build_queue(
        [
            record("a.jpg", finding("PARTNER_NOT_FOUND")),
            record("b.jpg", finding("TAX_MISMATCH")),
            record("c.jpg", finding("REJECTED_BY_ACCOUNTING_SYSTEM")),
        ]
    )

    groups = [group for group, _ in queue.by_group()]
    assert groups == [VERIFICATION_GAP, SUPPLIER, FIGURES]

    markdown = render_markdown(queue, STAMP)
    assert "Dates" not in markdown


def test_items_keep_the_order_the_run_produced_them_in():
    queue = build_queue(
        [
            record("first.jpg", finding("TAX_MISMATCH")),
            record("second.jpg", finding("TOTAL_MISMATCH")),
            record("third.jpg", finding("SUBTOTAL_MISMATCH")),
        ]
    )

    _, members = queue.by_group()[0]
    assert [item.source for item in members] == ["first.jpg", "second.jpg", "third.jpg"]


# ---------------------------------------------------------------------------
# What a reviewer actually reads
# ---------------------------------------------------------------------------


def test_the_markdown_carries_evidence_a_reviewer_can_act_on():
    """The point of the artifact is not reopening the source document."""
    queue = build_queue(
        [
            record(
                "tax.jpg",
                finding(
                    "TAX_MISMATCH",
                    "The tax printed does not match the tax recalculated.",
                    printed_tax=5400,
                    recomputed_tax=54000,
                    lines=[{"description": "値引き", "amount": -30000}],
                ),
            )
        ]
    )
    markdown = render_markdown(queue, STAMP)

    assert "5,400" in markdown and "54,000" in markdown  # grouped, as money reads
    assert "値引き" in markdown  # the nested line table survives in full
    assert "```json" in markdown  # structured evidence is not flattened away
    assert "**Your decision.**" in markdown
    assert "**What the system did not do.**" in markdown


def test_the_queue_points_at_the_record_holding_everything_else():
    queue = build_queue([record("traceable.jpg", finding("PARTNER_NOT_FOUND"))])

    assert queue.items[0].record_path == "out/runs/traceable.json"
    assert "out/runs/traceable.json" in render_markdown(queue, STAMP)


def test_booleans_in_evidence_do_not_render_as_numbers():
    """`bool` is a subclass of `int`; `True` printed as `1` is a small lie in an artifact
    whose whole job is not telling small lies."""
    queue = build_queue(
        [record("flagged.jpg", finding("PARTNER_NOT_FOUND", "…", matched_by_alias=False))]
    )

    assert "`matched_by_alias`: no" in render_markdown(queue, STAMP)


def test_an_empty_queue_says_so_rather_than_rendering_nothing():
    """Zero items is a result, and it must not look like a broken file."""
    queue = build_queue([registered("a.pdf"), registered("b.pdf")])
    markdown = render_markdown(queue, STAMP)

    assert "Nothing needs a person" in markdown
    assert "2 document(s) processed" in markdown
    assert STAMP in markdown


def test_a_full_batch_summarises_the_way_the_run_did():
    records = [registered(f"r{n}.pdf") for n in range(7)]
    records.append(duplicate("dupe.jpg"))
    records.extend(
        [
            record("h.jpg", finding("HANDWRITING_ANNOTATION")),
            record("p.jpg", finding("PARTNER_NOT_FOUND")),
            record("t.jpg", finding("TOTAL_MISMATCH")),
            record("x.jpg", finding("TAX_MISMATCH")),
        ]
    )
    queue = build_queue(records)

    assert queue.document_count == 12
    assert queue.needs_a_person == 4
    assert len(queue.registered) == 7
    assert len(queue.handled_without_a_person) == 1
    assert "4 of 12 document(s) need a person" in render_markdown(queue, STAMP)


# ---------------------------------------------------------------------------
# The structured rendering, and purity
# ---------------------------------------------------------------------------


def test_the_json_describes_the_same_queue_as_the_markdown():
    """The screen this project cut has something to consume the day it is built."""
    queue = build_queue(
        [
            registered("ok.pdf"),
            record("h.jpg", finding("HANDWRITING_ANNOTATION", "Someone wrote on it.")),
        ]
    )
    payload = to_json(queue, STAMP)

    assert payload["document_count"] == 2
    assert payload["needs_a_person"] == 1
    assert payload["registered"] == ["ok.pdf"]

    item = payload["items"][0]
    assert item["group"] == HANDWRITING
    assert item["as_read"]["invoice_number"] == "ABC-001"
    # The prose travels with the code: a consumer holding only the code would have to
    # reinvent the wording, and two descriptions of one reason drift apart immediately.
    assert item["findings"][0]["decision"]
    assert item["findings"][0]["not_done"]

    json.dumps(payload, ensure_ascii=False)  # must survive serialisation as-is


def test_building_the_queue_does_not_disturb_the_records_it_was_given():
    """The batch passes in the very dictionaries it wrote to disk."""
    records = [record("a.jpg", finding("TAX_MISMATCH", "…", printed_tax=5400))]
    before = json.dumps(records, ensure_ascii=False, sort_keys=True)

    build_queue(records)

    assert json.dumps(records, ensure_ascii=False, sort_keys=True) == before


def test_the_pipeline_and_the_queue_agree_on_what_registered_means():
    """Two modules holding the same string is a drift risk; this is the guard.

    `review/` deliberately does not import upward into the runner, so the constant is
    repeated rather than shared. Repeated constants are fine exactly as long as something
    fails when they stop matching.
    """
    from src.main import ALREADY_REGISTERED as PIPELINE_ALREADY_REGISTERED
    from src.main import REGISTERED as PIPELINE_REGISTERED

    assert PIPELINE_REGISTERED == REGISTERED
    assert REASONS["ALREADY_REGISTERED"].group == ALREADY_HANDLED
    # The pipeline's outcome name and the queue's exclusion rule describe one event from
    # two sides. They need not be equal, but both must exist.
    assert PIPELINE_ALREADY_REGISTERED
