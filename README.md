# Invoice Intake

Reads Japanese supplier invoices — PDFs, scans, and scanned PDFs — verifies what was read,
and registers it into an existing accounting system. Anything that cannot be verified goes
to a human instead of into the ledger.

> **Status: in development.** The run command below is the target interface, not yet the
> shipped one. This notice comes out when it does.

---

## Run it

Two terminals. The accounting system runs in one, the pipeline in the other.

**1 — start the mock accounting system** (Python 3.9+, no dependencies):

```bash
python accounting_api.py
```

**2 — run the pipeline:**

```bash
python -m src.main
```

### First-time setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
cp .env.example .env            # then paste your key in
```

**You need a Google AI Studio API key** — free tier, no card required, about two minutes
at <https://aistudio.google.com/apikey>. Put it in `.env` as `GEMINI_API_KEY=...`.

The provider sits behind a single function, so it is not load-bearing; the reasoning for
choosing it is in `SUBMISSION.md` section 4.

---

## What it does

```
invoices/  →  route  →  extract  →  verify  →  register  →  accounting API
                                       │
                                       └──  review queue  →  a human
```

- **route** — a PDF with a usable text layer is read as text; everything else is rendered
  and sent to a vision model. Routing is on detected content, never on file extension.
- **extract** — one model call per document, into a typed schema. The raw response is
  written to disk before anything parses it.
- **verify** — deterministic, offline, and free. Amounts are recomputed from the line
  items using the accounting system's own formula; the supplier is matched against the
  partner master; dates are normalised; duplicates are caught on
  `(partner, invoice number)` before anything is submitted.
- **register** — only invoices that passed every local check are POSTed.
- **review queue** — everything else, each with a structured reason and the evidence for
  it, so a person can act without reopening the source document.

Not every invoice can be registered, and that is by design rather than by failure. A
supplier absent from the partner master, or a second copy of an invoice already entered,
is a decision for a person — not something to retry until it succeeds.

---

## Tests

```bash
pytest
```

`tests/test_contract.py` enforces the structural claims `CLAUDE.md` makes about this
codebase — that `verify/` is pure, that nothing branches on a sample filename, that no
amount is a float. It is static, needs no API key, and runs in well under a second.

---

## Layout

| Path | |
|---|---|
| `src/extract/` | Document → structured data. The only place a model is called. |
| `src/verify/` | Pure functions. No I/O, no model, no network. |
| `src/register/` | The accounting API client. |
| `src/review/` | The human queue. |
| `invoices/` | Sample input. Read-only. |
| `out/` | Run artifacts — raw responses, extractions, decisions. Gitignored. |
| `accounting_api.py` | The mock accounting system, verbatim from the assignment. Unmodified. |
| `CLAUDE.md` | The engineering contract this codebase is written against. |

`accounting_api.py` is included so this repository runs from a cold clone. Its behaviour
is not modified — it is treated as a system owned by another team.
