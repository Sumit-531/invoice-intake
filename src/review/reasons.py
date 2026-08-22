"""What a reason code means to the person who has to act on it.

`verify/` states facts: the tax printed on the document is 5,400 and the tax recomputed
from its lines is 54,000. That is all it should ever say. It is pure, it is tested against
fabricated inputs, and it has no business holding an opinion about who fixes what.

This table holds the second dimension a reviewer needs and `verify/` must not grow: the
decision that belongs to a person, and — just as important — **what the system deliberately
did not do on its own.** That second field is the automation boundary written down. A
queue that only lists faults invites the question "why didn't it just fix this?"; a queue
that answers it in the same breath is the argument for the design.

Two properties this table must keep:

  - **Every code `verify/` can emit has an entry here.** A test walks the verify package
    and fails if one is missing, so a new check cannot ship without deciding who owns its
    outcome.
  - **An unknown code still renders.** A missing entry falls back to UNCLASSIFIED rather
    than raising. A queue that crashes on an unfamiliar finding is a queue that hides the
    finding, which is the opposite of the point.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Groups, in the order a reviewer should meet them.
#
# The ordering is not severity in the abstract — it is "what does this person do next".
# A verification gap comes first because it is an engineering defect wearing an invoice as
# a costume. Handwriting comes before arithmetic because a redirected payment is
# unrecoverable and a mistyped subtotal is not.
# ---------------------------------------------------------------------------

VERIFICATION_GAP = "verification_gap"
UNREADABLE = "unreadable"
HANDWRITING = "handwriting"
SUPPLIER = "supplier"
FIGURES = "figures"
TAX_CODE = "tax_code"
DATES = "dates"
LINE_DETAIL = "line_detail"
UNCLASSIFIED = "unclassified"

# Not a queue section. Findings in this group were handled by the system and need no
# person, so an item whose findings are all of this kind never reaches the queue at all.
# It is a group rather than a special case in the builder so that the policy lives in this
# table with every other policy, and not as a bare string comparison somewhere downstream.
ALREADY_HANDLED = "already_handled"

GROUPS: tuple[tuple[str, str, str], ...] = (
    (
        VERIFICATION_GAP,
        "Refused by the accounting system",
        "A refusal at the boundary means a local check has a hole. The invoice is the "
        "symptom; the missing check is the defect. Fix the check, then re-run.",
    ),
    (
        UNREADABLE,
        "Could not be read",
        "Nothing was extracted from these, so there is nothing to correct — only a file "
        "to look at.",
    ),
    (
        HANDWRITING,
        "Handwriting that changes the instruction",
        "Someone wrote on the document and what they wrote alters what it instructs. "
        "Transcribed, never applied.",
    ),
    (
        SUPPLIER,
        "Supplier not in the partner master",
        "The master is the authority on who may be paid. Nothing outside it can be "
        "registered, and nothing may be added to it automatically.",
    ),
    (
        FIGURES,
        "Printed figures disagree with the line items",
        "The line table and the printed summary are two independent readings of the same "
        "document. When they disagree, one of them was misread — and which one is a "
        "question about the paper, not about the arithmetic.",
    ),
    (
        TAX_CODE,
        "Tax code cannot be resolved",
        "A tax code, never a rate, crosses the boundary into the accounting system. "
        "Where the code is unknown or ambiguous, a person chooses it.",
    ),
    (
        DATES,
        "Dates",
        "Every date below is carried with the string exactly as the document printed it, "
        "so a calendar conversion can be audited without reopening the file.",
    ),
    (
        LINE_DETAIL,
        "Line detail missing",
        "The accounting system requires detail the document does not print. Nothing is "
        "invented on the invoice's behalf.",
    ),
    (
        UNCLASSIFIED,
        "Unclassified",
        "Stopped by a check newer than this guidance table. The finding and its evidence "
        "are below; the judgement is entirely yours.",
    ),
)

GROUP_ORDER: dict[str, int] = {key: index for index, (key, _, _) in enumerate(GROUPS)}
GROUP_HEADINGS: dict[str, str] = {key: heading for key, heading, _ in GROUPS}
GROUP_BLURBS: dict[str, str] = {key: blurb for key, _, blurb in GROUPS}


@dataclass(frozen=True)
class Reason:
    """Guidance for one reason code. Prose for a person; nothing parses these."""

    group: str
    title: str
    decision: str
    not_done: str


# Codes this package raises itself, for failures that happen outside `verify/` — a file
# that will not open, a model call that returns nothing usable, a refusal at the boundary.
# They are declared here rather than invented at the call site so that everything a
# reviewer can encounter is described in exactly one place.
DOCUMENT_UNREADABLE = "DOCUMENT_UNREADABLE"
EXTRACTION_FAILED = "EXTRACTION_FAILED"
REJECTED_BY_ACCOUNTING_SYSTEM = "REJECTED_BY_ACCOUNTING_SYSTEM"


REASONS: dict[str, Reason] = {
    REJECTED_BY_ACCOUNTING_SYSTEM: Reason(
        group=VERIFICATION_GAP,
        title="The accounting system refused an invoice the local checks passed",
        decision=(
            "Treat this as an engineering defect before treating it as a review item. "
            "Every check that should have caught this runs locally and runs for free; a "
            "refusal means one of them is missing or wrong. Find the hole, close it, and "
            "re-run the document."
        ),
        not_done=(
            "Nothing was retried and nothing was adjusted to make the submission fit. "
            "Retrying a rejection into acceptance is precisely the failure this pipeline "
            "exists to prevent."
        ),
    ),
    DOCUMENT_UNREADABLE: Reason(
        group=UNREADABLE,
        title="The file could not be opened",
        decision=(
            "Look at the file itself. It may be corrupt, empty, or not the format its "
            "extension claims — an extension is a promise the content need not keep."
        ),
        not_done=(
            "No extraction was attempted and nothing was submitted. The batch continued "
            "past it rather than stopping, so the rest of the set still ran."
        ),
    ),
    EXTRACTION_FAILED: Reason(
        group=UNREADABLE,
        title="Extraction returned nothing usable",
        decision=(
            "Read the raw model response in `out/raw/`. It was written to disk before "
            "anything tried to parse it, so what the model actually said is recoverable "
            "without paying for the call again. Then decide: re-run, or handle by hand."
        ),
        not_done=(
            "No partial extraction was salvaged into a payload. A half-read invoice is "
            "not a cheaper invoice, it is a wrong one."
        ),
    ),
    "HANDWRITING_ANNOTATION": Reason(
        group=HANDWRITING,
        title="Handwriting changes what the invoice instructs",
        decision=(
            "Read the annotation against the printed document and decide what the invoice "
            "actually instructs. If it redirects payment, it is a payment-security "
            "question before it is an accounting one — confirm it with the supplier "
            "through a channel that is not this piece of paper."
        ),
        not_done=(
            "The handwriting was transcribed and not applied. No field was altered by it "
            "and no bank detail was read off a photograph: a misread digit in an account "
            "number sends the money to a stranger, and no arithmetic downstream can catch "
            "that. This is the one hazard where the local stop is not the first line of "
            "defence but the only one."
        ),
    ),
    "PARTNER_NOT_FOUND": Reason(
        group=SUPPLIER,
        title="Supplier is not in the partner master",
        decision=(
            "Decide whether this supplier should be onboarded into the accounting system, "
            "or whether the invoice should be rejected outright. Only a person can make "
            "that call."
        ),
        not_done=(
            "No partner was created and no near-miss was accepted as a match. The printed "
            "name, every registered alias, and the registration number were all tried "
            "against the master; none of them resolved."
        ),
    ),
    "SUBTOTAL_MISMATCH": Reason(
        group=FIGURES,
        title="Subtotal disagrees with the line items",
        decision=(
            "Open the document and confirm which subtotal it actually prints. Compare it "
            "against the line amounts listed in the evidence — a dropped row and a "
            "misread digit look very different there."
        ),
        not_done=(
            "Nothing was submitted. The recomputed figure was not registered on the "
            "assumption that the lines must be the correct reading; either reading could "
            "be the misread one."
        ),
    ),
    "TAX_MISMATCH": Reason(
        group=FIGURES,
        title="Tax disagrees with the line items",
        decision=(
            "Confirm the tax figure printed on the document. Tax here is recomputed per "
            "tax code, on that code's own subtotal, rounded down — the same formula the "
            "accounting system applies — so the recomputed column is what would have been "
            "registered had this passed."
        ),
        not_done=(
            "Nothing was submitted. Note that a check comparing only the total would have "
            "let this through when the subtotal and total happen to agree, which is why "
            "tax is recomputed per code as an independent check rather than inferred."
        ),
    ),
    "TOTAL_MISMATCH": Reason(
        group=FIGURES,
        title="Total disagrees with the line items",
        decision=(
            "Confirm the total printed on the document. A gap of one or two yen is "
            "usually the supplier's own rounding rather than a misreading — the document "
            "may simply be internally inconsistent, which is still a person's call and "
            "not the system's."
        ),
        not_done=(
            "Nothing was submitted, and the difference was not absorbed as a rounding "
            "tolerance. A tolerance wide enough to swallow a supplier's rounding is wide "
            "enough to swallow a real error."
        ),
    ),
    "TOTAL_NOT_PRINTED": Reason(
        group=FIGURES,
        title="No printed total to check the line items against",
        decision=(
            "Confirm the invoice total by eye. Without a printed summary there is no "
            "second reading of the document, so the recomputed figure is unverified "
            "rather than verified."
        ),
        not_done=(
            "The amount computed from the line items was not registered unchecked. Rows "
            "the extractor may have misread are not evidence about themselves."
        ),
    ),
    "UNKNOWN_TAX_RATE": Reason(
        group=TAX_CODE,
        title="A line carries a tax rate the accounting system does not recognise",
        decision=(
            "Confirm the rate printed on that line. If it is genuine, the tax code master "
            "needs the code added before this invoice can be registered."
        ),
        not_done=(
            "No rate was rounded to the nearest recognised one and no tax code was "
            "guessed from context."
        ),
    ),
    "AMBIGUOUS_TAX_RATE": Reason(
        group=TAX_CODE,
        title="A line's tax rate maps to more than one tax code",
        decision=(
            "Choose the tax code that applies. The master offers more than one at this "
            "rate and the document does not say which is meant."
        ),
        not_done=(
            "Neither candidate was picked. An arbitrary choice would be right some of the "
            "time and silently wrong the rest, and the ledger would not record which."
        ),
    ),
    "ISSUE_DATE_UNUSABLE": Reason(
        group=DATES,
        title="Issue date could not be read as a real date",
        decision=(
            "Read the issue date off the document. The string exactly as printed is in "
            "the evidence below, so an era-year conversion can be checked without "
            "reopening the file."
        ),
        not_done=(
            "No date was inferred from the file's name, its timestamp, or the surrounding "
            "text."
        ),
    ),
    "DUE_DATE_MISSING": Reason(
        group=DATES,
        title="No payment due date is printed",
        decision=(
            "Establish the due date from the supplier's agreed payment terms, or from the "
            "supplier. The accounting system requires one."
        ),
        not_done=(
            "The due date was not defaulted to issue date plus thirty days, or to "
            "anything else. A missing due date is missing, not assumed."
        ),
    ),
    "DUE_DATE_UNUSABLE": Reason(
        group=DATES,
        title="Due date could not be read as a real date",
        decision=(
            "Read the due date off the document; it appears below exactly as printed."
        ),
        not_done="No date was inferred and no partial date was completed.",
    ),
    "DUE_DATE_BEFORE_ISSUE_DATE": Reason(
        group=DATES,
        title="Due date falls before the issue date",
        decision=(
            "Check both dates against the document. This ordering usually means an era "
            "year was converted wrongly, and both raw strings are below for comparison."
        ),
        not_done=(
            "The two dates were not swapped to make the ordering sensible. The accounting "
            "system would reject the pair anyway — but it would reject it after a round "
            "trip, and after the wrong one had already been believed."
        ),
    ),
    "LINE_UNIT_MISSING": Reason(
        group=LINE_DETAIL,
        title="A line prints no unit",
        decision=(
            "Supply the unit for that line, or confirm the document genuinely omits it."
        ),
        not_done="No unit was invented for the line.",
    ),
    "ALREADY_REGISTERED": Reason(
        group=ALREADY_HANDLED,
        title="The same invoice has already been registered",
        decision=(
            "None. Nothing is wrong with the document — it arrived twice, and the second "
            "copy was recognised on the accounting system's own identity, "
            "(partner code, invoice number), before anything was sent."
        ),
        not_done=(
            "The second copy was not submitted and then rejected. Learning about a "
            "duplicate from a 409 means the money was one accepted response away."
        ),
    ),
}


UNKNOWN_REASON = Reason(
    group=UNCLASSIFIED,
    title="Stopped by a check with no entry in the guidance table",
    decision=(
        "Read the finding and its evidence below and judge it directly. A code with no "
        "guidance means a check shipped without deciding who owns its outcome — worth "
        "fixing, but not a reason to hide the finding from you now."
    ),
    not_done="Nothing was submitted.",
)


def reason_for(code: str) -> Reason:
    """Guidance for a code, never raising on one this table has not met."""
    return REASONS.get(code, UNKNOWN_REASON)
