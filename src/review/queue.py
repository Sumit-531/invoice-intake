"""Turn the run records a batch produced into the queue a person works from.

Pure, like `verify/` and for the same reason: it takes plain dictionaries and returns
plain objects, so every shape a reviewer could meet — nothing queued, one invoice with
four findings, a code the guidance table has never seen — is testable against fabricated
input in microseconds, with no key, no network and no documents.

It reads records rather than live pipeline objects deliberately. The batch has them in
memory and passes them straight in; `python -m src.review` reads the same records back off
disk and gets a byte-identical queue. One code path, two entry points, no chance of the
regenerated queue quietly disagreeing with the one the run emitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .reasons import ALREADY_HANDLED, GROUP_ORDER, UNCLASSIFIED, Reason, reason_for

# Outcome names `main.py` writes into a record. Repeated here rather than imported: this
# package is downstream of the pipeline and importing upward to read a constant would
# couple the artifact to the runner for no gain. They are two short strings and a test
# asserts they still agree.
REGISTERED = "registered"


@dataclass(frozen=True)
class ReviewFinding:
    """One check's finding, with the guidance for acting on it attached."""

    code: str
    message: str
    title: str
    decision: str
    not_done: str
    evidence: dict = field(default_factory=dict)

    @property
    def group(self) -> str:
        return reason_for(self.code).group


@dataclass(frozen=True)
class ReviewItem:
    """One document that needs a person, and everything needed to act on it.

    The read fields are carried as *read*, not as verified — an item is here precisely
    because verification did not pass, so nothing on it has been confirmed. They exist so
    a reviewer can recognise the document without opening it, and the record path is here
    so the full evidence is one click away when recognising is not enough.
    """

    source: str
    route: str
    outcome: str
    group: str
    findings: tuple[ReviewFinding, ...]
    supplier_as_read: str | None = None
    invoice_number_as_read: str | None = None
    issue_date_as_read: str | None = None
    printed_total_as_read: int | None = None
    record_path: str = ""


@dataclass(frozen=True)
class HandledWithoutAPerson:
    """A document the pipeline stopped that needs no human decision.

    A stopped duplicate belongs here and not in the queue. Nothing is wrong with the
    document, so a reviewer sent to look at it goes hunting for a fault that does not
    exist — and a queue that cries wolf is a queue that stops being read. It is still
    reported, because "the system silently did something" is never an acceptable outcome
    either.
    """

    source: str
    code: str
    title: str


@dataclass(frozen=True)
class ReviewQueue:
    items: tuple[ReviewItem, ...] = ()
    handled_without_a_person: tuple[HandledWithoutAPerson, ...] = ()
    registered: tuple[str, ...] = ()
    document_count: int = 0

    @property
    def needs_a_person(self) -> int:
        return len(self.items)

    def by_group(self) -> list[tuple[str, tuple[ReviewItem, ...]]]:
        """Items gathered under their group, in the order `reasons.GROUPS` defines.

        Groups with nothing in them are absent rather than empty: a heading with no items
        under it reads like something was suppressed.
        """
        grouped: dict[str, list[ReviewItem]] = {}
        for item in self.items:
            grouped.setdefault(item.group, []).append(item)

        return [
            (group, tuple(members))
            for group, members in sorted(
                grouped.items(), key=lambda pair: _group_rank(pair[0])
            )
        ]


def _group_rank(group: str) -> int:
    return GROUP_ORDER.get(group, GROUP_ORDER[UNCLASSIFIED])


def _finding_from(raw: Mapping) -> ReviewFinding:
    code = str(raw.get("code", "")) or "UNSPECIFIED"
    reason: Reason = reason_for(code)
    evidence = raw.get("evidence") or {}
    return ReviewFinding(
        code=code,
        message=str(raw.get("message", "")),
        title=reason.title,
        decision=reason.decision,
        not_done=reason.not_done,
        evidence=dict(evidence),
    )


def _item_from(record: Mapping, findings: Sequence[ReviewFinding]) -> ReviewItem:
    invoice = record.get("invoice") or {}

    # Sorted so the finding that decides the item's group is also the one read first. An
    # invoice stopped for both a missing unit and a redirected bank account should not
    # open with the missing unit.
    ordered = tuple(sorted(findings, key=lambda f: _group_rank(f.group)))

    return ReviewItem(
        source=str(record.get("source", "")),
        route=str(record.get("route", "")),
        outcome=str(record.get("outcome", "")),
        group=ordered[0].group,
        findings=ordered,
        supplier_as_read=invoice.get("supplier_name"),
        invoice_number_as_read=invoice.get("invoice_number"),
        issue_date_as_read=invoice.get("issue_date"),
        printed_total_as_read=invoice.get("printed_total"),
        record_path=str(record.get("record_path", "")),
    )


def build_queue(records: Sequence[Mapping]) -> ReviewQueue:
    """Collect what needs a person out of a batch's run records.

    A record reaches the queue unless it was registered, or unless every finding on it is
    one the system handled by itself. Everything else — stopped locally, unreadable,
    refused at the boundary — is somebody's decision, and the point of this artifact is
    that there is exactly one place to find all of them.

    Input order is preserved within a group, so the queue reads in the same order as the
    run that produced it.
    """
    items: list[ReviewItem] = []
    handled: list[HandledWithoutAPerson] = []
    registered: list[str] = []

    for record in records:
        source = str(record.get("source", ""))
        outcome = str(record.get("outcome", ""))

        if outcome == REGISTERED:
            registered.append(source)
            continue

        findings = [_finding_from(raw) for raw in record.get("findings") or []]

        if findings and all(finding.group == ALREADY_HANDLED for finding in findings):
            handled.append(
                HandledWithoutAPerson(
                    source=source,
                    code=findings[0].code,
                    title=findings[0].title,
                )
            )
            continue

        if not findings:
            # A record that is neither registered nor carrying a reason is a hole in the
            # pipeline, not an empty result. Surfacing it as an unclassified item is the
            # loud failure; dropping it would be the quiet one.
            findings = [
                _finding_from(
                    {
                        "code": "NO_REASON_RECORDED",
                        "message": (
                            "This document did not register and recorded no reason why. "
                            "That is a defect in the pipeline, not a property of the "
                            "invoice."
                        ),
                        "evidence": {"outcome_recorded": outcome or "(none)"},
                    }
                )
            ]

        items.append(_item_from(record, findings))

    return ReviewQueue(
        items=tuple(items),
        handled_without_a_person=tuple(handled),
        registered=tuple(registered),
        document_count=len(records),
    )
