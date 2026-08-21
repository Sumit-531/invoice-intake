"""Run one invoice end to end: route → extract → verify → register.

    python -m src.main invoices/<file>

One document per run for now. Batching is the next slice; nothing here assumes a single
document except the argument parsing.

Exit status: 0 registered, 1 stopped (locally or by the accounting system), 2 could not
run at all. A blocked invoice is a correct outcome, not a crash — but it must never look
like a success to whatever runs this.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import ACCOUNTING_API_URL, RUNS_DIR, ensure_out_dirs
from .extract import Route, extract_invoice, load_document
from .extract.extractor import ExtractionParseFailed, RouteNotImplemented
from .extract.gemini import ExtractionCallFailed
from .register import AccountingClient, AccountingUnreachable, build_payload
from .verify import verify_extraction

EXIT_REGISTERED = 0
EXIT_STOPPED = 1
EXIT_ERROR = 2


def _emit(label: str, value: object = "") -> None:
    print(f"{label:<14} {value}" if value != "" else label)


def _write_run_record(name: str, record: dict) -> Path:
    ensure_out_dirs()
    path = RUNS_DIR / f"{Path(name).stem}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run(path: Path) -> int:
    document = load_document(path)
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

    client = AccountingClient()
    partners = client.partners()
    tax_codes = client.tax_codes()

    verification = verify_extraction(invoice, partners, tax_codes)

    record: dict = {
        "source": document.name,
        "source_sha256": document.sha256,
        "route": document.route.value,
        "extraction": {
            "model": raw.model,
            "prompt_version": raw.prompt_version,
            "from_cache": extraction.from_cache,
            "prompt_tokens": raw.prompt_tokens,
            "response_tokens": raw.response_tokens,
            "total_tokens": raw.total_tokens,
            "elapsed_seconds": raw.elapsed_seconds,
        },
        "invoice": invoice.model_dump(),
        "findings": [asdict(finding) for finding in verification.findings],
    }

    if not verification.ok:
        _emit("verify", f"STOPPED — {len(verification.findings)} finding(s)")
        for finding in verification.findings:
            print(f"\n  [{finding.code}] {finding.message}")
            for key, value in finding.evidence.items():
                print(f"      {key}: {value}")
        record["outcome"] = "stopped_locally"
        print()
        _emit("record", _write_run_record(document.name, record))
        return EXIT_STOPPED

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
        record["outcome"] = "registered"
        _emit("record", _write_run_record(document.name, record))
        return EXIT_REGISTERED

    # A refusal here means the local checks have a hole. The invoice is the symptom.
    _emit("register", f"{registration.status} {registration.error_code}")
    print(f"      {registration.error_message}")
    if registration.error_details:
        print(f"      {registration.error_details}")
    print(
        "\n  The accounting system refused something the local checks passed. That is a "
        "gap in verification, not just a bad invoice."
    )
    record["outcome"] = "rejected_by_accounting_system"
    _emit("record", _write_run_record(document.name, record))
    return EXIT_STOPPED


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
    if not path.is_file():
        print(f"No such file: {path}")
        return EXIT_ERROR

    _emit("accounting", ACCOUNTING_API_URL)

    try:
        return run(path)
    except RouteNotImplemented as exc:
        _emit("route", f"UNSUPPORTED — {exc}")
        return EXIT_STOPPED
    except (ExtractionCallFailed, ExtractionParseFailed) as exc:
        _emit("extract", f"FAILED — {exc}")
        return EXIT_ERROR
    except AccountingUnreachable as exc:
        _emit("accounting", f"UNREACHABLE — {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
