"""The strongest check available: recompute the money and see whether it agrees.

Deterministic, free, offline. It catches the errors an extraction model actually makes —
a dropped row on a page break, a discount read without its minus sign, a digit slipped in
a six-figure amount — and it catches them before anything is submitted.

MIRRORING, NOT REIMPLEMENTING
The accounting system recalculates every amount from the line items and rejects ours if
they disagree. So this function reproduces its formula exactly, floating-point included:

    tax_for_code = floor(subtotal_for_that_code * rate)

Doing this in integer arithmetic would arguably be *more* correct and is therefore wrong
here. The two can disagree by one yen at a rounding boundary, and the accounting system is
the authority. If our number and theirs ever differ, theirs is right and this file has a
bug. This is the one place in the codebase where a float is legitimate — and it is a
multiplier, never an amount.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import ExtractedInvoice
from .result import Finding


@dataclass(frozen=True)
class Amounts:
    subtotal: int
    tax_amount: int
    total_amount: int
    tax_by_code: tuple[tuple[str, int], ...]


def recompute(
    invoice: ExtractedInvoice,
    tax_code_by_line: tuple[str, ...],
    rate_by_code: dict[str, float],
) -> Amounts:
    """Rebuild every figure from the line items, the way the accounting system does."""
    subtotal = sum(line.amount for line in invoice.lines)

    subtotal_by_code: dict[str, int] = {}
    for line, code in zip(invoice.lines, tax_code_by_line):
        subtotal_by_code[code] = subtotal_by_code.get(code, 0) + line.amount

    tax_by_code = {
        code: math.floor(amount_for_code * rate_by_code[code])
        for code, amount_for_code in subtotal_by_code.items()
    }
    tax_amount = sum(tax_by_code.values())

    return Amounts(
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=subtotal + tax_amount,
        tax_by_code=tuple(sorted(tax_by_code.items())),
    )


def check_amounts(invoice: ExtractedInvoice, computed: Amounts) -> list[Finding]:
    """Compare the recalculation against the figures printed on the document.

    The printed summary is a second, independent reading of the same invoice. The lines
    say one thing, the supplier's own total says another; agreement between them is the
    evidence that the rows were read correctly. Without a printed total there is no second
    reading, and a total derived only from rows the model may have misread is not a check —
    so an invoice with no printed total goes to a person rather than to the ledger.
    """
    findings: list[Finding] = []

    if invoice.printed_total is None:
        findings.append(
            Finding(
                "TOTAL_NOT_PRINTED",
                "No total was read from the invoice, so the amounts recalculated from the "
                "line items cannot be cross-checked against anything.",
                {"recomputed_total": computed.total_amount},
            )
        )

    checks = (
        ("SUBTOTAL_MISMATCH", "subtotal", invoice.printed_subtotal, computed.subtotal),
        ("TAX_MISMATCH", "tax", invoice.printed_tax_amount, computed.tax_amount),
        ("TOTAL_MISMATCH", "total", invoice.printed_total, computed.total_amount),
    )

    for code, label, printed, recomputed in checks:
        if printed is None or printed == recomputed:
            continue
        findings.append(
            Finding(
                code,
                f"The {label} printed on the invoice does not match the {label} "
                "recalculated from its line items. One of the two was misread.",
                {
                    f"printed_{label}": printed,
                    f"recomputed_{label}": recomputed,
                    "difference": printed - recomputed,
                    "lines": [
                        {"description": line.description, "amount": line.amount}
                        for line in invoice.lines
                    ],
                    "recomputed_tax_by_code": dict(computed.tax_by_code),
                },
            )
        )

    return findings
