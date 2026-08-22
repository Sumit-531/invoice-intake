"""The verification layer, exercised against corrupted extractions.

Every case here is a misreading an extraction model actually makes: a sign lost, a row
dropped at a page break, a digit slipped, an era year converted wrongly, the same invoice
arriving twice in two formats. The test asserts that the check *fires* — because a check
nobody has watched fail is not a check, it is a hope.

These began as a throwaway sabotage harness in Session 1. It printed
`notes/session1_sabotage.txt` and was then deleted, which meant the evidence survived and
the guarantee did not: nothing would have caught a regression in `arithmetic.py` the
following week. This file is that harness made permanent.

Read the test names as sentences. `pytest -v` prints them as a list of the failure modes
this system is known to catch — which is a more honest answer to "how do you know your
verification works" than any paragraph of prose.

No network, no API key, no model, no accounting system running. `verify/` is pure, and
this file is what that purity was for: every case below is a fabricated object, and the
whole suite runs in well under a second for free.
"""

from __future__ import annotations

import pytest

from src.models import ExtractedInvoice, ExtractedLine, Partner, RegisteredInvoice, TaxCode
from src.verify import verify_extraction

# ---------------------------------------------------------------------------
# Fixtures — the accounting system's masters, as constants.
#
# Copied rather than fetched, deliberately. These tests must run with nothing on :8080,
# and a check that silently skips when a server is missing is a check that will be missing
# on the day it matters.
# ---------------------------------------------------------------------------

PARTNERS = [
    Partner(
        partner_code="P-1001",
        name="株式会社山田製作所",
        aliases=["ヤマダ製作所", "山田製作所"],
        registration_no="T1010001000101",
    ),
    Partner(
        partner_code="P-1002",
        name="有限会社佐藤商店",
        aliases=["佐藤商店"],
        registration_no="T2020002000202",
    ),
    Partner(
        partner_code="P-1005",
        name="みらいITソリューションズ株式会社",
        aliases=["みらいIT", "みらいITソリューションズ"],
        registration_no="T5050005000505",
    ),
]

TAX_CODES = [
    TaxCode(tax_code="T10", rate=0.10, label="標準税率"),
    TaxCode(tax_code="T08", rate=0.08, label="軽減税率"),
]

NOTHING_REGISTERED: list[RegisteredInvoice] = []


def baseline() -> ExtractedInvoice:
    """The Session 1 extraction, exactly as the model returned it. Known good.

    A fresh object every call, so a test may corrupt it freely without leaking that
    corruption into the next one.
    """
    return ExtractedInvoice(
        invoice_number="YM-2026-0107",
        supplier_name="株式会社山田製作所",
        supplier_registration_no="T1010001000101",
        issue_date="2026-01-07",
        issue_date_raw="2026年1月7日",
        due_date="2026-02-28",
        due_date_raw="2026年2月28日",
        printed_subtotal=304000,
        printed_tax_amount=30400,
        printed_total=334400,
        lines=[
            ExtractedLine(
                description="精密部品A-100",
                quantity=120,
                unit="個",
                unit_price=1250,
                amount=150000,
                tax_rate_percent=10,
            ),
            ExtractedLine(
                description="精密部品B-220",
                quantity=40,
                unit="個",
                unit_price=3400,
                amount=136000,
                tax_rate_percent=10,
            ),
            ExtractedLine(
                description="梱包・輸送費",
                quantity=None,
                unit="式",
                unit_price=None,
                amount=18000,
                tax_rate_percent=10,
            ),
        ],
    )


def codes_for(invoice, already_registered=NOTHING_REGISTERED) -> tuple[str, ...]:
    return verify_extraction(invoice, PARTNERS, TAX_CODES, already_registered).codes


def findings_for(invoice, already_registered=NOTHING_REGISTERED):
    return verify_extraction(invoice, PARTNERS, TAX_CODES, already_registered).findings


# ---------------------------------------------------------------------------
# The baseline
# ---------------------------------------------------------------------------


def test_the_session_1_baseline_extraction_passes_every_check():
    """Nothing below means anything if a correct invoice does not survive the checks.

    A validator that rejects everything catches every error and is worthless. This is the
    control case, and it runs first for that reason.
    """
    verification = verify_extraction(
        baseline(), PARTNERS, TAX_CODES, NOTHING_REGISTERED
    )
    assert verification.ok, f"a known-good extraction was rejected: {verification.codes}"
    assert verification.partner_code == "P-1001"
    assert verification.tax_code_by_line == ("T10", "T10", "T10")
    assert (verification.subtotal, verification.tax_amount, verification.total_amount) == (
        304000,
        30400,
        334400,
    )


# ---------------------------------------------------------------------------
# Check 1 — arithmetic. The strongest check: deterministic, free, offline.
# ---------------------------------------------------------------------------


def test_a_sign_error_on_a_line_fails_the_arithmetic():
    """A positive charge read as negative. Wrong by twice the line, so it cannot hide."""
    invoice = baseline()
    invoice.lines[2].amount = -18000

    assert "SUBTOTAL_MISMATCH" in codes_for(invoice)


def test_a_discount_read_as_positive_fails_by_twice_its_value():
    """The hazard in its real direction: `△18,000` is a *minus*, and reading it as a plus
    inflates the total. This passes a naive eye and cannot pass arithmetic."""
    invoice = baseline()
    invoice.lines[2].description = "△ 年間取引割引"
    invoice.lines[2].amount = -18000
    invoice.printed_subtotal = 268000
    invoice.printed_tax_amount = 26800
    invoice.printed_total = 294800
    assert codes_for(invoice) == (), "a genuine negative discount line must verify cleanly"

    misread_as_positive = invoice.model_copy(deep=True)
    misread_as_positive.lines[2].amount = 18000

    assert "SUBTOTAL_MISMATCH" in codes_for(misread_as_positive)


def test_a_line_dropped_at_a_page_break_fails_the_arithmetic():
    """Multi-page tables put the totals on the last page and the rows everywhere else.

    A dropped row is the failure mode of that layout, and the printed total is the only
    thing that knows the row existed.
    """
    invoice = baseline()
    del invoice.lines[1]

    assert "SUBTOTAL_MISMATCH" in codes_for(invoice)


def test_a_digit_slipped_in_a_six_figure_amount_fails_the_arithmetic():
    """150,000 read as 15,000 — a plausible OCR slip and a 135,000 yen error."""
    invoice = baseline()
    invoice.lines[0].amount = 15000

    assert "SUBTOTAL_MISMATCH" in codes_for(invoice)


def test_a_total_wrong_by_one_yen_is_still_caught():
    """The tolerance is zero. There is no rounding allowance, because the accounting
    system has none either — it recomputes and compares exactly."""
    invoice = baseline()
    invoice.printed_total = 334401

    assert codes_for(invoice) == ("TOTAL_MISMATCH",)


def test_an_invoice_with_no_printed_total_has_nothing_to_check_against():
    """Without a printed summary there is only one reading of the document, and comparing
    the model's rows against the model's own sum proves nothing. That goes to a person
    rather than to the ledger."""
    invoice = baseline()
    invoice.printed_total = None

    assert codes_for(invoice) == ("TOTAL_NOT_PRINTED",)


def test_mixed_rates_in_one_invoice_accrue_tax_per_code():
    """Tax is floored per tax code, on that code's own subtotal — not on the invoice total.

    Flooring the sum instead of the parts gives a different answer, and the accounting
    system floors the parts. The second line is chosen so the rounding is visible:
    10,001 x 8% is 800.08, which floors to 800.
    """
    invoice = baseline()
    invoice.lines = [
        ExtractedLine(description="標準税率品", unit="個", amount=10000, tax_rate_percent=10),
        ExtractedLine(description="軽減税率品", unit="個", amount=10001, tax_rate_percent=8),
    ]
    invoice.printed_subtotal = 20001
    invoice.printed_tax_amount = 1800  # 1,000 + 800, floored separately
    invoice.printed_total = 21801

    verification = verify_extraction(invoice, PARTNERS, TAX_CODES, NOTHING_REGISTERED)

    assert verification.ok, verification.codes
    assert verification.tax_code_by_line == ("T10", "T08")
    assert dict(verification.tax_by_code) == {"T10": 1000, "T08": 800}


def test_a_tax_code_swapped_for_the_reduced_rate_fails_the_tax_check():
    """The subtotal still agrees — only the tax moves. Nothing but recomputing the tax
    per code would notice this."""
    invoice = baseline()
    invoice.lines[0].tax_rate_percent = 8

    assert "TAX_MISMATCH" in codes_for(invoice)
    assert "SUBTOTAL_MISMATCH" not in codes_for(invoice)


def test_a_rate_the_accounting_system_does_not_know_is_rejected_locally():
    """5% is a real historical Japanese rate and not one this ledger accepts. Catching it
    here costs nothing; catching it as an UNKNOWN_TAX_CODE costs a round trip."""
    invoice = baseline()
    invoice.lines[0].tax_rate_percent = 5

    assert "UNKNOWN_TAX_RATE" in codes_for(invoice)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def test_an_era_year_misconverted_puts_the_due_date_before_the_issue_date():
    """令和8年 is 2026, not 2025. The conversion is where era dates go wrong, and a due
    date landing before its issue date is the shape that mistake takes."""
    invoice = baseline()
    invoice.due_date = "2025-02-28"
    invoice.due_date_raw = "令和8年2月28日"

    assert codes_for(invoice) == ("DUE_DATE_BEFORE_ISSUE_DATE",)


def test_a_missing_due_date_is_missing_and_not_issue_date_plus_thirty():
    """No silent defaults. Inventing a payment date is inventing a payment obligation."""
    invoice = baseline()
    invoice.due_date = None
    invoice.due_date_raw = None

    assert codes_for(invoice) == ("DUE_DATE_MISSING",)


def test_a_date_left_in_the_printed_format_is_rejected_at_the_boundary():
    """Asked for YYYY-MM-DD, a model will sometimes return 2026/01/07 anyway. The
    accounting system answers that with a 422 we should never have provoked."""
    invoice = baseline()
    invoice.issue_date = "2026/01/07"

    assert "ISSUE_DATE_UNUSABLE" in codes_for(invoice)


# ---------------------------------------------------------------------------
# Check 2 — master data. External ground truth; the model cannot argue with it.
# ---------------------------------------------------------------------------


def test_a_supplier_absent_from_the_master_can_never_be_registered():
    """Not a bug, not a retry, and above all not a partner created on the fly. A human
    decision, with the printed name and number handed over as evidence."""
    invoice = baseline()
    invoice.supplier_name = "株式会社架空商会"
    invoice.supplier_registration_no = None

    assert codes_for(invoice) == ("PARTNER_NOT_FOUND",)


def test_a_supplier_printed_as_a_short_form_still_resolves_through_its_alias():
    """Suppliers print trading names and abbreviations. The master carries the aliases,
    so this must resolve rather than land in the queue."""
    invoice = baseline()
    invoice.supplier_name = "山田製作所"
    invoice.supplier_registration_no = None

    assert codes_for(invoice) == ()


def test_a_supplier_name_in_full_width_characters_still_matches_the_master():
    """Width is presentation. `ＩＴ` and `IT` are the same two letters, and treating them
    as different companies is a false rejection, not a safety measure."""
    invoice = baseline()
    invoice.supplier_name = "みらいＩＴソリューションズ株式会社"
    invoice.supplier_registration_no = None

    assert codes_for(invoice) == ()


def test_a_company_form_abbreviated_to_the_kabu_ligature_still_matches():
    """`㈱山田製作所` is `株式会社山田製作所`. NFKC gets it to `(株)`; the expansion to the
    long form finishes the job."""
    invoice = baseline()
    invoice.supplier_name = "㈱山田製作所"
    invoice.supplier_registration_no = None

    assert codes_for(invoice) == ()


def test_a_registration_number_in_full_width_digits_still_matches():
    """`str.isalnum()` is true for full-width digits, so stripping punctuation alone would
    leave `Ｔ１０１…` intact and unmatched. The NFKC pass is what makes this work."""
    invoice = baseline()
    invoice.supplier_registration_no = "Ｔ１０１０００１０００１０１"

    assert codes_for(invoice) == ()


def test_the_registration_number_outranks_a_name_that_does_not_match():
    """The strongest key wins. A supplier may print a division or a trading name the
    master has never seen; the national registration number is the same number every
    time."""
    invoice = baseline()
    invoice.supplier_name = "山田製作所 第二工場"

    verification = verify_extraction(
        invoice, PARTNERS, TAX_CODES, NOTHING_REGISTERED
    )

    assert verification.partner_code == "P-1001"


def test_a_line_with_no_printed_unit_is_not_given_one():
    """The accounting system requires a unit on every line. Supplying `式` on the
    supplier's behalf would be this system asserting something the document does not
    say."""
    invoice = baseline()
    invoice.lines[2].unit = None

    assert codes_for(invoice) == ("LINE_UNIT_MISSING",)


# ---------------------------------------------------------------------------
# Duplicates — the client's stated fear, caught before the POST rather than by a 409.
# ---------------------------------------------------------------------------

ALREADY_HELD = [
    RegisteredInvoice(
        accounting_id="ACC-0001",
        partner_code="P-1001",
        invoice_number="YM-2026-0107",
        issue_date="2026-01-07",
        total_amount=334400,
    )
]


def test_nothing_is_a_duplicate_against_an_empty_accounting_system():
    """The first run of the day, against a freshly restarted ledger."""
    assert codes_for(baseline(), []) == ()


def test_the_same_invoice_arriving_twice_is_caught_before_the_post():
    """The whole point. This must fail locally — never by catching a 409, because by then
    a payment instruction has already crossed the boundary."""
    assert codes_for(baseline(), ALREADY_HELD) == ("ALREADY_REGISTERED",)


def test_a_duplicate_is_recognised_through_an_alias_because_the_key_is_the_partner_code():
    """The two copies print the supplier differently — the full legal name on the PDF, a
    short form on the photograph. They collapse to one partner code first, and only then
    can they be seen as one invoice. This is why the check runs after partner
    resolution."""
    second_copy = baseline()
    second_copy.supplier_name = "ヤマダ製作所"
    second_copy.supplier_registration_no = None

    assert codes_for(second_copy, ALREADY_HELD) == ("ALREADY_REGISTERED",)


@pytest.mark.parametrize(
    "as_read_on_the_second_copy",
    ["YM-2026-0107", "YM 2026 0107", "YM20260107", "ym-2026-0107", "ＹＭ－２０２６－０１０７"],
)
def test_a_separator_read_differently_is_still_the_same_invoice(as_read_on_the_second_copy):
    """OCR renders a separator as a hyphen, a space, or nothing, depending on the scan.

    Punctuation is dropped from the duplicate key for that reason. The two errors are not
    symmetric: over-normalising can only merge documents that were not the same invoice,
    which stops and goes to a person, while under-normalising lets a real duplicate through
    and pays it twice.
    """
    second_copy = baseline()
    second_copy.invoice_number = as_read_on_the_second_copy

    assert codes_for(second_copy, ALREADY_HELD) == ("ALREADY_REGISTERED",)


def test_a_match_made_only_after_normalising_says_so_in_its_evidence():
    """A duplicate always goes to a person, so the useful question is not *whether* it
    matched but *how*. Two numbers that differ on the page and agree only after punctuation
    was dropped are the case where a false duplicate could hide, and the reviewer should be
    told that without being sent back to compare the strings themselves."""
    second_copy = baseline()
    second_copy.invoice_number = "YM 2026 0107"

    assert findings_for(second_copy, ALREADY_HELD)[0].evidence["matched_on"].startswith(
        "normalised"
    )


def test_a_match_on_identical_strings_says_it_was_exact():
    exact = findings_for(baseline(), ALREADY_HELD)[0]

    assert exact.evidence["matched_on"] == "exact"


def test_a_second_copy_with_a_different_total_is_still_a_duplicate():
    """Identity is (partner_code, invoice_number) and nothing else. The same number
    carrying two different amounts is more alarming, not less — so both totals go into
    the evidence for a person to compare."""
    second_copy = baseline()
    second_copy.lines[0].amount = 160000
    second_copy.printed_subtotal = 314000
    second_copy.printed_tax_amount = 31400
    second_copy.printed_total = 345400

    assert "ALREADY_REGISTERED" in codes_for(second_copy, ALREADY_HELD)


def test_the_same_number_from_a_different_supplier_is_not_a_duplicate():
    """Invoice numbers are unique per supplier, not globally. Two suppliers may both run a
    sequence that produces the same string, and blocking the second would be wrong."""
    other_supplier = baseline()
    other_supplier.supplier_name = "有限会社佐藤商店"
    other_supplier.supplier_registration_no = "T2020002000202"

    assert codes_for(other_supplier, ALREADY_HELD) == ()


def test_a_duplicate_carries_the_existing_accounting_id_as_evidence():
    """A duplicate is not a defect — nothing is wrong with the document. The reviewer's
    action is 'confirm and close', which requires knowing *which* registration this
    already is, without reopening either file."""
    finding = findings_for(baseline(), ALREADY_HELD)[0]

    assert finding.evidence["already_registered_as"] == "ACC-0001"
    assert finding.evidence["registered_total"] == 334400
    assert finding.evidence["this_copy_printed_total"] == 334400


def test_a_duplicate_of_an_unresolvable_supplier_reports_only_the_real_failure():
    """With no partner code there is no key to compare, and the invoice is already blocked
    by the partner failure. A second finding derived from the first is noise in a report
    a person has to read."""
    invoice = baseline()
    invoice.supplier_name = "株式会社架空商会"
    invoice.supplier_registration_no = None

    assert codes_for(invoice, ALREADY_HELD) == ("PARTNER_NOT_FOUND",)


# ---------------------------------------------------------------------------
# Handwriting — the automation boundary, not a check on a number.
# ---------------------------------------------------------------------------


def test_a_received_stamp_leaves_no_note_and_does_not_stop_the_invoice():
    """Office noise is the common case and must not queue anything. A review queue that
    every stamped document lands in is a queue nobody reads.

    The extractor is what decides this — it is told to ignore filing marks and leave the
    note null — so the case is expressed here the way it actually arrives: as an extraction
    with nothing in `handwriting_note`.
    """
    assert codes_for(baseline()) == ()


def test_a_handwritten_change_to_bank_details_goes_to_a_person():
    """The hazard in full. No API field carries a bank account, so nothing downstream can
    catch this: the accounting system will accept the invoice and pay the printed account.
    A local stop is not the first line of defence here, it is the only one."""
    invoice = baseline()
    invoice.handwriting_note = "振込先変更 みずほ銀行 渋谷支店 普通 1234567"

    assert codes_for(invoice) == ("HANDWRITING_ANNOTATION",)


def test_the_handwritten_change_is_transcribed_and_never_applied():
    """Detected and flagged, never interpreted. The system does not read an account number
    off a photograph and pay it — a misread digit there is money gone to a stranger, which
    is not recoverable the way a misread line amount is."""
    invoice = baseline()
    invoice.handwriting_note = "支払期日 3月31日に変更"

    finding = findings_for(invoice)[0]

    assert finding.evidence["handwriting_as_read"] == "支払期日 3月31日に変更"
    # The printed value is reported unchanged. Nothing derived the handwritten date into
    # the field the accounting system would act on.
    assert finding.evidence["printed_due_date"] == "2026-02-28"
    assert invoice.due_date == "2026-02-28"


def test_an_annotated_invoice_stops_even_when_its_arithmetic_is_perfect():
    """This is why the check exists. Every number on the page adds up, every master
    resolves, and the invoice is still not safe to register automatically."""
    invoice = baseline()
    invoice.handwriting_note = "振込先変更"

    verification = verify_extraction(invoice, PARTNERS, TAX_CODES, NOTHING_REGISTERED)

    assert not verification.ok
    # The arithmetic ran and agreed — the recomputed figures are right there. The invoice
    # is blocked anyway, and nothing but the handwriting is blocking it.
    assert verification.codes == ("HANDWRITING_ANNOTATION",)
    assert verification.total_amount == 334400


def test_whitespace_in_the_note_is_not_a_handwritten_annotation():
    """A model returning `" "` rather than null must not queue the document. An empty
    string is the absence of a note, however it was spelled."""
    invoice = baseline()
    invoice.handwriting_note = "   "

    assert codes_for(invoice) == ()


# ---------------------------------------------------------------------------
# The contract every finding must keep
# ---------------------------------------------------------------------------


def _sign_error():
    invoice = baseline()
    invoice.lines[2].amount = -18000
    return invoice


def _unknown_supplier():
    invoice = baseline()
    invoice.supplier_name = "株式会社架空商会"
    invoice.supplier_registration_no = None
    return invoice


def _unknown_rate():
    invoice = baseline()
    invoice.lines[0].tax_rate_percent = 5
    return invoice


def _missing_due_date():
    invoice = baseline()
    invoice.due_date = None
    invoice.due_date_raw = None
    return invoice


def _missing_unit():
    invoice = baseline()
    invoice.lines[2].unit = None
    return invoice


def _handwritten_bank_change():
    invoice = baseline()
    invoice.handwriting_note = "振込先変更 みずほ銀行 渋谷支店 普通 1234567"
    return invoice


@pytest.mark.parametrize(
    "build_broken_invoice",
    [
        _sign_error,
        _unknown_supplier,
        _unknown_rate,
        _missing_due_date,
        _missing_unit,
        _handwritten_bank_change,
    ],
    ids=[
        "sign_error",
        "unknown_supplier",
        "unknown_rate",
        "missing_due_date",
        "missing_unit",
        "handwritten_bank_change",
    ],
)
def test_every_rejection_carries_evidence_a_person_can_act_on(build_broken_invoice):
    """CLAUDE.md: 'Every rejection carries a structured reason and the evidence for it —
    enough for a person to act without reopening the source document.'

    A finding with an empty evidence dict sends the reviewer back to the PDF, which is the
    cost this rule exists to avoid.
    """
    findings = findings_for(build_broken_invoice())
    assert findings, "the corrupted invoice was not rejected at all"

    for finding in findings:
        assert finding.code and finding.code.isupper()
        assert finding.message.strip()
        assert finding.evidence, f"{finding.code} carries no evidence"
