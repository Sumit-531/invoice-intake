"""Run the pipeline: route → extract → verify → register.

    python -m src.main invoices/<file>     one document, in full detail
    python -m src.main invoices/           every document, paced, with a summary table

Exit status, for one document: 0 registered, 1 stopped (locally or by the accounting
system), 2 could not run at all. A blocked invoice is a correct outcome, not a crash — but
it must never look like a success to whatever runs this.

Exit status for a directory is a different question, because there a stopped invoice is
the *expected* result and not a failure of the run. A batch exits 0 when every document
reached a decision, and 2 when any did not — either because it could not be read at all,
or because the accounting system refused something the local checks passed. That second
case is deliberately an error rather than a decision: a refusal downstream means the local
checks have a hole, and a run containing one must not report success.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import (
    ACCOUNTING_API_URL,
    MODEL_MIN_SPACING_SECONDS,
    OUT_DIR,
    RUNS_DIR,
    ensure_out_dirs,
)
from .extract import SourceDocument, extract_invoice, is_cached, load_document
from .extract.extractor import ExtractionParseFailed
from .extract.gemini import ExtractionCallFailed
from .models import Partner, RegisteredInvoice, TaxCode
from .register import AccountingClient, AccountingUnreachable, build_payload
from .verify import verify_extraction

EXIT_REGISTERED = 0
EXIT_STOPPED = 1
EXIT_ERROR = 2

# The reason code `verify/` emits for a second copy, as distinct from the outcome name
# below. They read alike because they describe the same event from two sides — the check
# that fired, and what the run decided to do about it.
DUPLICATE_CODE = "ALREADY_REGISTERED"

REGISTERED = "registered"
ALREADY_REGISTERED = "already_registered"
STOPPED_LOCALLY = "stopped_locally"
REJECTED_BY_ACCOUNTING_SYSTEM = "rejected_by_accounting_system"
COULD_NOT_RUN = "could_not_run"

# Outcomes that mean the pipeline did its job. The two absent from this set are the two
# that mean it did not: one document could not be read, or one crossed the boundary and
# came back refused.
DECIDED = frozenset({REGISTERED, ALREADY_REGISTERED, STOPPED_LOCALLY})

# Extensions PyMuPDF will open. Note what this is and is not: a filter on what can be
# *opened*, applied when walking a directory, so a stray README does not become a failed
# document. It is not a routing decision — the route is still measured from the content of
# whatever this admits.
READABLE_SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"})


@dataclass(frozen=True)
class Outcome:
    """One document's result, in the shape the summary table needs."""

    source: str
    route: str
    pages: int
    outcome: str
    detail: str
    total_tokens: int
    elapsed_seconds: float
    from_cache: bool


def _emit(label: str, value: object = "") -> None:
    print(f"{label:<14} {value}" if value != "" else label)


def _write_run_record(name: str, record: dict) -> Path:
    ensure_out_dirs()
    path = RUNS_DIR / f"{Path(name).stem}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def process(
    document: SourceDocument,
    client: AccountingClient,
    partners: list[Partner],
    tax_codes: list[TaxCode],
    already_registered: list[RegisteredInvoice],
    *,
    detailed: bool,
) -> Outcome:
    """Extract, verify, and register one document. Writes its run record either way.

    `already_registered` is mutated on a successful registration, deliberately. Within one
    batch the second copy of an invoice must be stopped by the first copy having just been
    registered — the accounting system's list was fetched before either was read, so
    nothing else in the run knows about it yet. This is the in-run half of duplicate
    detection; the fetch at startup is the across-run half.
    """
    _emit("document", f"{document.name}  ({document.page_count} page(s))")
    _emit(
        "route",
        f"{document.route.value}  — {document.text_char_count} characters in the text "
        f"layer, detected, not assumed from the extension",
    )

    extraction = extract_invoice(document)
    invoice = extraction.invoice
    raw = extraction.raw
    _emit(
        "extract",
        f"{raw.model}  prompt {raw.prompt_version}  "
        + (
            "served from cache — no request spent"
            if extraction.from_cache
            else f"{raw.total_tokens} tokens, {raw.elapsed_seconds}s"
        ),
    )
    _emit("read", f"{invoice.supplier_name}  {invoice.invoice_number}")

    verification = verify_extraction(invoice, partners, tax_codes, already_registered)

    record: dict = {
        "source": document.name,
        "source_sha256": document.sha256,
        "route": document.route.value,
        "extraction": {
            "model": raw.model,
            "prompt_version": raw.prompt_version,
            "from_cache": extraction.from_cache,
            "page_images": raw.page_images,
            "prompt_tokens": raw.prompt_tokens,
            "response_tokens": raw.response_tokens,
            "total_tokens": raw.total_tokens,
            "elapsed_seconds": raw.elapsed_seconds,
        },
        "invoice": invoice.model_dump(),
        "findings": [asdict(finding) for finding in verification.findings],
    }

    def _outcome(name: str, detail: str) -> Outcome:
        record["outcome"] = name
        _emit("record", _write_run_record(document.name, record))
        return Outcome(
            source=document.name,
            route=document.route.value,
            pages=document.page_count,
            outcome=name,
            detail=detail,
            total_tokens=0 if extraction.from_cache else raw.total_tokens,
            elapsed_seconds=0.0 if extraction.from_cache else raw.elapsed_seconds,
            from_cache=extraction.from_cache,
        )

    if not verification.ok:
        # A duplicate is not a defect. Nothing is wrong with the document — it arrived
        # twice — and a reviewer told "STOPPED" goes looking for a fault that is not there.
        already_seen = verification.codes == (DUPLICATE_CODE,)
        _emit(
            "verify",
            "ALREADY REGISTERED — not submitted again"
            if already_seen
            else f"STOPPED — {len(verification.findings)} finding(s)",
        )
        for finding in verification.findings:
            print(f"\n  [{finding.code}] {finding.message}")
            if detailed:
                for key, value in finding.evidence.items():
                    print(f"      {key}: {value}")
        print()
        return _outcome(
            ALREADY_REGISTERED if already_seen else STOPPED_LOCALLY,
            ", ".join(verification.codes),
        )

    _emit(
        "verify",
        f"passed — subtotal {verification.subtotal:,}  "
        f"tax {verification.tax_amount:,}  total {verification.total_amount:,}  "
        f"(recomputed from {len(invoice.lines)} lines, matches the printed figures)",
    )

    payload = build_payload(invoice, verification)
    record["payload"] = payload

    registration = client.create_invoice(payload)
    record["registration"] = asdict(registration)

    if registration.accepted:
        _emit("register", f"201 Created — {registration.accounting_id}")
        already_registered.append(
            RegisteredInvoice(
                accounting_id=registration.accounting_id or "",
                partner_code=verification.partner_code or "",
                invoice_number=invoice.invoice_number,
                issue_date=invoice.issue_date,
                total_amount=verification.total_amount,
            )
        )
        return _outcome(REGISTERED, registration.accounting_id or "")

    # A refusal here means the local checks have a hole. The invoice is the symptom.
    _emit("register", f"{registration.status} {registration.error_code}")
    print(f"      {registration.error_message}")
    if registration.error_details:
        print(f"      {registration.error_details}")
    print(
        "\n  The accounting system refused something the local checks passed. That is a "
        "gap in verification, not just a bad invoice."
    )
    return _outcome(
        REJECTED_BY_ACCOUNTING_SYSTEM,
        f"{registration.status} {registration.error_code}",
    )


# ---------------------------------------------------------------------------
# The summary table — emitted by the run, never typed out by hand afterwards.
# ---------------------------------------------------------------------------

_COLUMNS = ("invoice", "route", "pages", "outcome", "detail", "tokens", "seconds")


def _rows(outcomes: list[Outcome]) -> list[tuple[str, ...]]:
    rows = []
    for outcome in outcomes:
        rows.append(
            (
                outcome.source,
                outcome.route,
                str(outcome.pages),
                outcome.outcome,
                outcome.detail,
                "cached" if outcome.from_cache else str(outcome.total_tokens),
                "cached" if outcome.from_cache else f"{outcome.elapsed_seconds:.1f}",
            )
        )
    return rows


def _print_table(outcomes: list[Outcome]) -> None:
    rows = [_COLUMNS, *_rows(outcomes)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(_COLUMNS))]

    for index, row in enumerate(rows):
        print("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:
            print("  " + "  ".join("-" * width for width in widths))


def _write_outcome_table(outcomes: list[Outcome]) -> Path:
    """Write the per-invoice outcome table as Markdown.

    This file exists because the submission needs a per-invoice table and a cost figure,
    and a table reconstructed by hand at the end of a project is a table that quietly
    disagrees with what the run actually did. The run writes its own.
    """
    ensure_out_dirs()
    lines = [
        "# Run outcomes",
        "",
        "Emitted by `python -m src.main invoices/`. Not hand-written.",
        "",
        "| " + " | ".join(_COLUMNS) + " |",
        "|" + "|".join("---" for _ in _COLUMNS) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in _rows(outcomes))

    billed = [o for o in outcomes if not o.from_cache]
    lines.extend(
        [
            "",
            f"{len(outcomes)} document(s). "
            f"{len(billed)} model request(s) spent, "
            f"{len(outcomes) - len(billed)} served from cache.",
            "",
            f"Tokens across the requests actually spent: "
            f"{sum(o.total_tokens for o in billed):,}. "
            f"Wall clock in the model: {sum(o.elapsed_seconds for o in billed):.1f}s.",
        ]
    )

    path = OUT_DIR / "outcomes.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run_batch(directory: Path) -> int:
    paths = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in READABLE_SUFFIXES
    )
    if not paths:
        print(f"No readable documents in {directory}")
        return EXIT_ERROR

    client = AccountingClient()
    partners = client.partners()
    tax_codes = client.tax_codes()
    # Fetched once, then appended to as the batch registers. See `process`.
    already_registered = client.invoices()

    _emit("documents", f"{len(paths)} to process")
    _emit("masters", f"{len(partners)} partners, {len(tax_codes)} tax codes")
    _emit("registered", f"{len(already_registered)} invoice(s) already in the ledger")

    outcomes: list[Outcome] = []
    a_request_has_been_spent = False

    for path in paths:
        print("\n" + "─" * 78)

        try:
            document = load_document(path)
        except Exception as exc:  # an unreadable file must not end the batch
            _emit("document", path.name)
            _emit("FAILED", f"could not be opened — {type(exc).__name__}: {exc}")
            outcomes.append(
                Outcome(path.name, "unknown", 0, COULD_NOT_RUN, str(exc)[:60], 0, 0.0, False)
            )
            continue

        if not is_cached(document):
            if a_request_has_been_spent:
                _emit("pacing", f"{MODEL_MIN_SPACING_SECONDS}s — free tier allows 5/minute")
                time.sleep(MODEL_MIN_SPACING_SECONDS)
            a_request_has_been_spent = True

        try:
            outcomes.append(
                process(
                    document,
                    client,
                    partners,
                    tax_codes,
                    already_registered,
                    detailed=False,
                )
            )
        except (ExtractionCallFailed, ExtractionParseFailed) as exc:
            _emit("FAILED", f"extraction — {exc}")
            outcomes.append(
                Outcome(
                    path.name,
                    document.route.value,
                    document.page_count,
                    COULD_NOT_RUN,
                    f"{type(exc).__name__}",
                    0,
                    0.0,
                    False,
                )
            )

    print("\n" + "─" * 78 + "\n")
    _print_table(outcomes)
    print()

    tally: dict[str, int] = {}
    for outcome in outcomes:
        tally[outcome.outcome] = tally.get(outcome.outcome, 0) + 1
    _emit("summary", ", ".join(f"{count} {name}" for name, count in sorted(tally.items())))
    _emit("table", _write_outcome_table(outcomes))

    undecided = [o for o in outcomes if o.outcome not in DECIDED]
    if undecided:
        print(
            f"\n  {len(undecided)} document(s) did not reach a decision. A run is only "
            "clean when every document was either registered or stopped with a reason."
        )
        return EXIT_ERROR

    return EXIT_REGISTERED


def run_one(path: Path) -> int:
    client = AccountingClient()
    partners = client.partners()
    tax_codes = client.tax_codes()
    already_registered = client.invoices()

    document = load_document(path)
    outcome = process(
        document, client, partners, tax_codes, already_registered, detailed=True
    )

    return EXIT_REGISTERED if outcome.outcome == REGISTERED else EXIT_STOPPED


def main(argv: list[str]) -> int:
    # Japanese text on a Windows console defaults to cp1252 and raises on the first
    # kanji. The pipeline must not die printing its own result.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if len(argv) != 1:
        print(__doc__)
        return EXIT_ERROR

    path = Path(argv[0])
    if not path.exists():
        print(f"No such file or directory: {path}")
        return EXIT_ERROR

    _emit("accounting", ACCOUNTING_API_URL)

    try:
        return run_batch(path) if path.is_dir() else run_one(path)
    except (ExtractionCallFailed, ExtractionParseFailed) as exc:
        _emit("extract", f"FAILED — {exc}")
        return EXIT_ERROR
    except AccountingUnreachable as exc:
        _emit("accounting", f"UNREACHABLE — {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
