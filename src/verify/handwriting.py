"""Handwriting that changes what the invoice means.

Two kinds appear on these documents and the distinction is the whole check. A received
stamp, a filing mark or a set of initials is office noise: it says something about how the
paper was handled, nothing about what is owed. An annotation altering bank details, an
amount or a date changes the instruction the invoice carries.

The extraction prompt already draws that line — it is told to ignore the first kind and to
transcribe the second into `handwriting_note`, verbatim, without applying it. This module
is what makes that transcription *do* something. Without it, an invoice whose payee account
was crossed out and rewritten by hand extracts cleanly, verifies cleanly, and registers
against the printed bank details, with the note sitting unread in a JSON file.

WHY THIS BLOCKS RATHER THAN WARNS
No API field carries a bank account, so there is nothing to submit and nothing to compare
against — meaning no downstream check can ever catch this. The accounting system will
accept the invoice happily. That makes this the one hazard class where a local stop is not
the first line of defence but the only one.

It is also the automation boundary stated deliberately rather than discovered by failing:
the system detects handwriting and hands it to a person. It does not read a bank account
off a photograph and pay it. A misread digit in an account number is unrecoverable in a way
that a misread line amount is not — the money is simply gone, to someone else.
"""

from __future__ import annotations

from ..models import ExtractedInvoice
from .result import Finding


def check_handwriting(invoice: ExtractedInvoice) -> list[Finding]:
    """Route to a person when the document carries a meaning-changing annotation.

    Absence of a note is not evidence of absence of handwriting — it is the extractor
    having judged what it saw to be office noise. That judgement is a model's, and it is
    accepted here for one reason: the alternative is queueing every document that has ever
    been stamped, which is all of them, and a review queue everything lands in is a queue
    nobody reads.
    """
    note = invoice.handwriting_note

    if note is None or not note.strip():
        return []

    return [
        Finding(
            "HANDWRITING_ANNOTATION",
            "This invoice carries handwriting that appears to change its meaning — "
            "payment instructions, an amount, or a date. It has been transcribed and "
            "not applied. A person must decide what the document actually instructs.",
            {
                "handwriting_as_read": note.strip(),
                # The printed values the annotation sits alongside. A reviewer comparing
                # "what the supplier printed" against "what someone wrote on it" needs
                # both in one place, and only one of them is in the note.
                "printed_invoice_number": invoice.invoice_number,
                "printed_supplier": invoice.supplier_name,
                "printed_issue_date": invoice.issue_date,
                "printed_due_date": invoice.due_date,
                "printed_total": invoice.printed_total,
                "note": "Nothing on this invoice was altered by the handwriting. Every "
                        "field above is what the document prints.",
            },
        )
    ]
