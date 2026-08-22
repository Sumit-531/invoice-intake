"""Has this invoice already been registered?

The client's stated fear, in plain terms: the same invoice arrives twice — once as a PDF,
once as a photograph of the same sheet — and the supplier gets paid twice.

The accounting system does catch this. It returns `409 DUPLICATE_INVOICE`, keyed on exactly
`(partner_code, invoice_number)`. Relying on that is still wrong. By the time a 409 comes
back, a payment instruction has already crossed into a system we do not own, and we are
depending on another team's correctness to protect us. So the check runs here, before the
POST, and the 409 stays as a backstop — if it ever fires, this module has a hole and the
hole is the bug, not the invoice.

THE KEY IS THE PARTNER CODE, NOT THE PRINTED NAME
The two copies may print the supplier differently — the full legal name on the PDF, a short
form on the photo. They must collapse to one identity before they can be compared, which is
why this check runs *after* the partner has been resolved against the master, not before.

A duplicate is not an error. Nothing is wrong with the document; it has simply arrived
twice. The correct human action is "confirm and close", not "fix and resubmit", so the
finding carries the existing `accounting_id` and lets a reviewer settle it without
reopening either file.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import ExtractedInvoice, RegisteredInvoice
from .result import Finding
from .text import normalise_identifier


def check_not_already_registered(
    invoice: ExtractedInvoice,
    partner_code: str | None,
    already_registered: Sequence[RegisteredInvoice],
) -> list[Finding]:
    """Compare `(partner_code, invoice_number)` against what the system already holds.

    The invoice number is compared on its normalised form, which makes this check
    *stricter* than the accounting system's own — it compares raw strings. That asymmetry
    is deliberate and points the safe way: being stricter can only produce a false
    duplicate, which stops and goes to a person. Being looser would let a real duplicate
    through, and that is a second payment.
    """
    if partner_code is None:
        # The partner did not resolve, so there is no key to build. The invoice is already
        # blocked by that failure, and a second finding derived from the first would only
        # add noise to a report someone has to read.
        return []

    number = normalise_identifier(invoice.invoice_number)

    for existing in already_registered:
        if existing.partner_code != partner_code:
            continue
        if normalise_identifier(existing.invoice_number) != number:
            continue

        # How the match was made, not just that it was made — the same way
        # `resolve_partner` reports whether it matched on a registration number, a name or
        # an alias. "normalised" is the case where the two strings differ on the page and
        # were only equal after width and punctuation were dropped, which is exactly where
        # a false duplicate would hide. The reviewer should see that without being told to
        # go and compare the strings themselves.
        matched_on = (
            "exact"
            if existing.invoice_number == invoice.invoice_number
            else "normalised — the two numbers are not identical as printed"
        )

        return [
            Finding(
                "ALREADY_REGISTERED",
                "This invoice is already registered in the accounting system. Nothing is "
                "wrong with the document — it has arrived twice, and the second copy must "
                "not be registered again.",
                {
                    "partner_code": partner_code,
                    "invoice_number_as_printed": invoice.invoice_number,
                    "matched_on": matched_on,
                    "already_registered_as": existing.accounting_id,
                    "registered_invoice_number": existing.invoice_number,
                    "registered_issue_date": existing.issue_date,
                    # Both totals, side by side. Equal means a plain re-send. Unequal means
                    # the same invoice number carries two different amounts, which a person
                    # needs to see immediately.
                    "registered_total": existing.total_amount,
                    "this_copy_printed_total": invoice.printed_total,
                    "this_copy_issue_date": invoice.issue_date,
                },
            )
        ]

    return []
