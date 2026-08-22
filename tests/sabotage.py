"""Break a real extraction on purpose and watch the validator stop it.

    python -m tests.sabotage invoices/<file>              every case
    python -m tests.sabotage invoices/<file> --case sign  one case
    python -m tests.sabotage --list                       what the cases are

A check nobody has watched fail is not a check, it is a hope. `tests/test_verify.py` holds
the durable version of this — it runs in half a second and needs nothing — but a passing
test is an assertion, not a demonstration. This is the demonstration: a real document, its
real extraction, one field corrupted, and the rejection printed with its evidence.

COSTS NOTHING TO RUN. The extraction comes from the raw cache, so every case below replays
a response already paid for. The masters come from the accounting system, because the whole
point is that the check runs against real ground truth rather than a fixture.

Each corruption is structural — "negate the last line", "drop a row" — never "line 3 of
this particular invoice". Point it at any document that extracts cleanly and the same cases
apply.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.extract import extract_invoice, load_document
from src.models import ExtractedInvoice, RegisteredInvoice
from src.register import AccountingClient
from src.verify import verify_extraction

# A name chosen to be absent from any real partner master. Not a real company.
A_SUPPLIER_NOBODY_HAS_REGISTERED = "株式会社架空商会"


def _largest_line(invoice: ExtractedInvoice) -> int:
    return max(range(len(invoice.lines)), key=lambda i: abs(invoice.lines[i].amount))


def sign_error(invoice: ExtractedInvoice) -> str | None:
    """A charge read as a credit, or a discount read as a charge. Wrong by twice the line."""
    line = invoice.lines[-1]
    before = line.amount
    line.amount = -before
    return f"last line {before:,} read as {line.amount:,}"


def dropped_line(invoice: ExtractedInvoice) -> str | None:
    """What a page break does to a multi-page line table."""
    if len(invoice.lines) < 2:
        return None
    dropped = invoice.lines.pop()
    return f"row removed: {dropped.description} ({dropped.amount:,})"


def digit_slip(invoice: ExtractedInvoice) -> str | None:
    """One digit lost from the largest amount on the page."""
    index = _largest_line(invoice)
    line = invoice.lines[index]
    before = line.amount
    line.amount = before // 10
    return f"line {index + 1}: {before:,} read as {line.amount:,}"


def swapped_tax_code(invoice: ExtractedInvoice) -> str | None:
    """The subtotal still agrees. Only recomputing tax per code notices this."""
    line = invoice.lines[0]
    before = line.tax_rate_percent
    line.tax_rate_percent = 8 if before != 8 else 10
    return f"line 1 read at {line.tax_rate_percent}% instead of {before}%"


def unknown_tax_rate(invoice: ExtractedInvoice) -> str | None:
    """A real historical Japanese rate that this ledger does not accept."""
    invoice.lines[0].tax_rate_percent = 5
    return "line 1 read as 5% consumption tax"


def era_year_misconverted(invoice: ExtractedInvoice) -> str | None:
    """The conversion is where era dates go wrong: 令和8年 is 2026, not 2025."""
    if invoice.due_date is None:
        return None
    year, rest = invoice.due_date.split("-", 1)
    invoice.due_date = f"{int(year) - 1}-{rest}"
    return f"due date converted to {invoice.due_date} instead of the printed year"


def due_date_lost(invoice: ExtractedInvoice) -> str | None:
    """A missing due date must stay missing — not become issue date plus thirty."""
    if invoice.due_date is None:
        return None
    invoice.due_date = None
    invoice.due_date_raw = None
    return "due date not read at all"


def unit_lost(invoice: ExtractedInvoice) -> str | None:
    """The accounting system requires a unit on every line. Nothing is invented."""
    invoice.lines[-1].unit = None
    return f"last line ({invoice.lines[-1].description}) has no unit"


def total_not_printed(invoice: ExtractedInvoice) -> str | None:
    """Without a printed summary there is only one reading of the document."""
    if invoice.printed_total is None:
        return None
    invoice.printed_total = None
    return "printed total not read, so nothing cross-checks the line items"


def off_by_one_yen(invoice: ExtractedInvoice) -> str | None:
    """The tolerance is zero, because the accounting system's tolerance is zero."""
    if invoice.printed_total is None:
        return None
    invoice.printed_total += 1
    return f"printed total read as {invoice.printed_total:,}, one yen high"


CASES = {
    "sign": sign_error,
    "drop-line": dropped_line,
    "digit-slip": digit_slip,
    "swap-tax-code": swapped_tax_code,
    "unknown-rate": unknown_tax_rate,
    "era-year": era_year_misconverted,
    "no-due-date": due_date_lost,
    "no-unit": unit_lost,
    "no-total": total_not_printed,
    "one-yen": off_by_one_yen,
}


def _report(label: str, detail: str | None, verification) -> None:
    status = "PASSED " if verification.ok else "STOPPED"
    print(f"\n{status}  {label}" + (f": {detail}" if detail else ""))
    for finding in verification.findings:
        print(f"         [{finding.code}] {finding.message}")
        for key, value in finding.evidence.items():
            print(f"             {key}: {value}")


def run(path: Path, only: str | None) -> int:
    document = load_document(path)
    extraction = extract_invoice(document)
    print(f"document   {document.name}")
    print(
        "extraction "
        + (
            "served from the raw cache — no request spent"
            if extraction.from_cache
            else f"{extraction.raw.total_tokens} tokens spent"
        )
    )

    client = AccountingClient()
    partners = client.partners()
    tax_codes = client.tax_codes()

    # The document cases run as if nothing were registered, deliberately. Reading the live
    # ledger would make this driver's output depend on whether the invoice happened to be
    # registered a minute ago — the baseline would fail as a duplicate, and every case
    # below it would be skipped. A demonstration whose result changes with invisible state
    # is not a demonstration. The duplicate check gets its own section, with its own
    # explicit world.
    nothing_registered: list[RegisteredInvoice] = []

    print("\n" + "=" * 78)
    print("BASELINE — the extraction exactly as the model returned it")
    print("=" * 78)
    baseline = verify_extraction(
        extraction.invoice, partners, tax_codes, nothing_registered
    )
    _report("untouched", None, baseline)

    if not baseline.ok:
        print(
            "\nThe baseline does not pass, so nothing below proves anything: a validator "
            "that rejects everything catches every error and is worthless. Fix the "
            "baseline, or point this at a document that extracts cleanly."
        )
        return 1

    print("\n" + "=" * 78)
    print("SABOTAGE — one field corrupted per case, in memory only")
    print("=" * 78)

    selected = {only: CASES[only]} if only else CASES
    missed: list[str] = []

    for name, corrupt in selected.items():
        broken = extraction.invoice.model_copy(deep=True)
        detail = corrupt(broken)
        if detail is None:
            print(f"\nSKIPPED  {name}: does not apply to this document")
            continue
        verification = verify_extraction(broken, partners, tax_codes, nothing_registered)
        _report(name, detail, verification)
        if verification.ok:
            missed.append(name)

    print("\n" + "=" * 78)
    print("DUPLICATE — the document is untouched; the world is not")
    print("=" * 78)
    as_if_already_held = [
        RegisteredInvoice(
            accounting_id="ACC-XXXX",
            partner_code=baseline.partner_code or "",
            invoice_number=extraction.invoice.invoice_number,
            issue_date=extraction.invoice.issue_date,
            total_amount=baseline.total_amount,
        ),
    ]
    duplicate = verify_extraction(
        extraction.invoice, partners, tax_codes, as_if_already_held
    )
    _report("this invoice has already been registered", None, duplicate)
    if duplicate.ok:
        missed.append("duplicate")

    if missed:
        print(
            f"\n{len(missed)} corruption(s) went undetected: {', '.join(missed)}. "
            "That is a hole in verification, and it is the interesting result."
        )
        return 1

    print("\nEvery corruption was stopped locally. Nothing reached the accounting system.")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if "--list" in argv:
        print("Cases:\n")
        for name, corrupt in CASES.items():
            summary = (corrupt.__doc__ or "").strip().splitlines()[0]
            print(f"  {name:<15} {summary}")
        print(f"\n  {'duplicate':<15} The same invoice, already registered. Always runs.")
        return 0

    only = None
    if "--case" in argv:
        index = argv.index("--case")
        only = argv[index + 1] if index + 1 < len(argv) else None
        if only not in CASES:
            print(f"Unknown case: {only}. Try --list.")
            return 2
        del argv[index : index + 2]

    if len(argv) != 1:
        print(__doc__)
        return 2

    path = Path(argv[0])
    if not path.is_file():
        print(f"No such file: {path}")
        return 2

    return run(path, only)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
