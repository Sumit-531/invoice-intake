"""Turning a verified extraction into the request body the accounting system expects.

Nothing is decided here. Every value has already been read from the document or resolved
against a master, and this module only arranges them. If a field looks like it needs a
default at this point, the mistake was made upstream.

The amounts submitted are the *recalculated* ones, not the printed ones. They are equal —
verification would have blocked otherwise — but the recalculation is the figure derived
from the same line items the accounting system will use, so submitting it means the two
sides are computing from identical inputs.
"""

from __future__ import annotations

from ..models import ExtractedInvoice
from ..verify import Verification


class NotRegistrable(RuntimeError):
    """Asked to build a payload from something that did not pass verification.

    A guard against the failure mode this system exists to prevent: never construct a
    submission for an invoice with an unresolved field.
    """


def build_payload(invoice: ExtractedInvoice, verification: Verification) -> dict:
    if not verification.ok:
        raise NotRegistrable(
            "Verification did not pass: " + ", ".join(verification.codes)
        )
    if verification.partner_code is None or invoice.due_date is None:
        raise NotRegistrable("Verification passed without resolving a required field.")

    return {
        "partner_code": verification.partner_code,
        "invoice_number": invoice.invoice_number,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "currency": "JPY",
        "subtotal": verification.subtotal,
        "tax_amount": verification.tax_amount,
        "total_amount": verification.total_amount,
        "lines": [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": line.unit_price,
                "amount": line.amount,
                "tax_code": tax_code,
            }
            for line, tax_code in zip(invoice.lines, verification.tax_code_by_line)
        ],
    }
