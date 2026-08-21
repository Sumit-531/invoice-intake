"""Date checks.

Parsing happened once, at extraction. From here inward the format is invariant, and this
module's job is to prove that claim rather than assume it — a model asked for YYYY-MM-DD
will sometimes return 2026/01/07, and the accounting system rejects that with a 422 we
should never have provoked.

A missing due date is missing. It is not "issue date + 30". No silent defaults.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import ExtractedInvoice
from .result import Finding

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse(value: str) -> date | None:
    if not ISO_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_dates(invoice: ExtractedInvoice) -> list[Finding]:
    findings: list[Finding] = []

    issue = _parse(invoice.issue_date)
    if issue is None:
        findings.append(
            Finding(
                "ISSUE_DATE_UNUSABLE",
                "Issue date is not a real YYYY-MM-DD date.",
                {"normalised": invoice.issue_date, "as_printed": invoice.issue_date_raw},
            )
        )

    if invoice.due_date is None:
        findings.append(
            Finding(
                "DUE_DATE_MISSING",
                "No payment due date is printed on the invoice. A due date is required "
                "to register and must not be assumed from payment terms.",
                {"as_printed": invoice.due_date_raw},
            )
        )
        return findings

    due = _parse(invoice.due_date)
    if due is None:
        findings.append(
            Finding(
                "DUE_DATE_UNUSABLE",
                "Due date is not a real YYYY-MM-DD date.",
                {"normalised": invoice.due_date, "as_printed": invoice.due_date_raw},
            )
        )
        return findings

    if issue is not None and due < issue:
        findings.append(
            Finding(
                "DUE_DATE_BEFORE_ISSUE_DATE",
                "The payment due date falls before the issue date, which usually means "
                "one of the two was misread — often an era-year conversion.",
                {
                    "issue_date": invoice.issue_date,
                    "issue_date_as_printed": invoice.issue_date_raw,
                    "due_date": invoice.due_date,
                    "due_date_as_printed": invoice.due_date_raw,
                },
            )
        )

    return findings
