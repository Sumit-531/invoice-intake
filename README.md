# Invoice Intake

Reads Japanese supplier invoices — PDFs, scans, and scanned PDFs — verifies what was read,
and registers it into an existing accounting system. Anything that cannot be verified goes
to a human instead of into the ledger.

> **Status: in development.** The whole folder runs end to end today — both routes, all
> twelve documents, each routed, extracted, verified against the accounting system's own
> arithmetic and master data, and either registered or stopped with a reason. What is not
> built yet is the review queue as a first-class artifact: a stopped invoice reports its
> findings and writes them to `out/runs/`, but there is no single file collecting them for
> a reviewer. This notice comes out when there is.

---

## Run it

Two terminals. The accounting system runs in one, the pipeline in the other.

**1 — start the mock accounting system** (Python 3.9+, no dependencies):

```bash
python accounting_api.py
```

**2 — run the pipeline.** Point it at the folder for the whole set:

```bash
python -m src.main invoices/
```

Or at a single document, which prints the full evidence for every finding:

```bash
python -m src.main invoices/<file>
```

A batch ends with a per-invoice outcome table, also written to `out/outcomes.md`. It exits
`0` when every document reached a decision — registered, or stopped with a reason — and
`2` when any did not. **A stopped invoice is a correct outcome, not a failure of the run.**
A full pass over the sample set registers 7, stops 1 as a duplicate, and sends 4 to a
person; a run reporting 12 of 12 registered would mean something was wrong.

A single-document run exits `0` when the invoice was registered and `1` when it was
stopped. Either way the findings and the evidence go to `out/runs/<name>.json`.

Extraction is cached on disk, keyed by file content, so re-running costs no API requests
and takes seconds. Uncached calls in a batch are spaced 13 seconds apart to stay inside the
free tier's 5-per-minute limit.

If something on your machine already owns port 8080 on loopback, set `ACCOUNTING_API_URL`
in `.env`; `accounting_api.py` binds `0.0.0.0`, so it stays reachable on the machine's own
hostname.

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

Ninety-three tests, all offline. **No API key, no running accounting system, no network.**
That is a property of the design rather than of the tests: `verify/` is pure, so every
check can be run against a fabricated invoice for free.

- `tests/test_contract.py` — the structural claims `CLAUDE.md` makes about this codebase:
  that `verify/` is pure, that nothing branches on a sample filename, that no amount is a
  float. Static analysis of the source itself.
- `tests/test_verify.py` — each check watched failing on a corrupted extraction. A sign
  flipped, a row dropped at a page break, a digit slipped, an era year converted wrongly,
  the same invoice arriving twice in two formats. Read the test names as a list of the
  failure modes this system is known to catch.
- `tests/test_routing.py` — renames a text-layer PDF to `.jpg` and asserts the route does
  not move, and the reverse. The contract test proves no filename is *named*; this proves
  the extension is not consulted either.

There is also a sabotage driver, which corrupts a real extraction eleven ways and shows
each one stopped:

```bash
python -m tests.sabotage invoices/<file>
```

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
