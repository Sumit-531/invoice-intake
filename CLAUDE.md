# Invoice Intake

Automated intake of supplier invoices into an existing accounting system.
Japanese business documents — mixed formats, mixed layouts, mixed quality.

**Human-architected, agent-executed.** The approach is stated in plain terms and agreed
before code is written. This file is the contract between the two.

---

## Prime Directive

> **Every extraction error must produce a fast, deterministic, local failure — before
> anything reaches the accounting system.**

An extraction model *will* misread a document. That is assumed, not feared. What is
unacceptable is a misread that registers silently and becomes a payment.

When you propose a change, ask: **does this make a wrong extraction louder, or quieter?**
If quieter, don't.

---

## Verification doctrine

**A model cannot verify its own extraction.** The extractor and the checker share one
understanding of the document, so a defect living in that understanding survives both.
Asking a model to re-read a field it just misread is not a second opinion.

Verification is ranked. Strongest first:

| # | Check | Property |
|---|---|---|
| 1 | **Arithmetic** — recompute subtotal, per-code tax, and total from the lines | Deterministic, free, offline. Catches sign errors, dropped lines, digit slips. |
| 2 | **Master data** — partner list, tax codes | External ground truth. The model cannot argue with it. |
| 3 | **The accounting API** — it recalculates and rejects | Genuinely independent, but costs a round trip and arrives last. |
| 4 | **Model self-consistency / stated confidence** | A *signal* for routing. Never a gate. |

A field that fails 1–3 is **not** retried into submission. It goes to a human.

Checks 1 and 2 must pass locally before any POST is attempted. Discovering an error via a
`422` from the accounting system means the local checks have a hole — fix the hole, not
just the invoice.

---

## The accounting system — LOCKED

Its specification cannot change. Treat it as a system owned by another team.

- `http://localhost:8080`, header `X-API-Key: demo-key-1234`
- `GET /partners` — **only suppliers in this master may be registered.** No exceptions,
  no fallback, no "create if missing."
- `GET /tax-codes` — a tax **code** (`T10` / `T08`), never a rate, crosses the boundary
- `POST /invoices` — registers. `GET` lists, `DELETE` clears (in-memory; restart resets).
- Dates: `YYYY-MM-DD` only. Amounts: **integer JPY**, no decimals. Currency: `JPY` only.
- Lines: at least one. `quantity` and `unit_price` may be `null`; `amount` may not.

**It recalculates every amount from the line items.** Tax is computed per tax code, on
that code's subtotal, **rounded down**. Our numbers are never taken at face value — which
is why check 1 above mirrors that formula exactly. If our arithmetic and theirs disagree,
theirs is right and ours has a bug.

**Mirror their formula exactly — floating-point included.** Tax is
`floor(subtotal_for_code × rate)`, computed the way they compute it. Reimplementing it in
integer arithmetic is arguably *more* correct and is therefore wrong here: the two can
disagree at the rounding boundary, and they are the authority. This is the one place a
float is legitimate.

Error codes are structured (`PARTNER_NOT_FOUND`, `DUPLICATE_INVOICE`, `AMOUNT_MISMATCH`,
`UNKNOWN_TAX_CODE`, `DUE_DATE_BEFORE_ISSUE_DATE`, `VALIDATION_ERROR`). Branch on the code,
never on the message string.

---

## Document hazards — classes, not cases

Properties of Japanese supplier invoices in general. The sample set exercises each one.
**Handle the class. Never the sample.**

- **Era dates** — `令和8年2月5日` is 2026-02-05. Also `2026年1月7日` and `2026/01/18`.
- **Negative lines** — `△` or `▲` prefixes a minus. A discount read as positive passes a
  naive eye and fails arithmetic by twice its value.
- **Mixed tax rates within one invoice** — per-line rate; tax accrues per code.
- **Supplier printed as an alias or short form** — the master carries aliases; match
  against them, and against the registration number, which is the strongest key available.
- **Supplier absent from the master entirely** — this invoice can never be registered.
  Not a bug. Not a retry. A human decision.
- **The same invoice arriving twice** in different formats — this is the client's stated
  fear. Detect it on `(partner, invoice_number)` *before* submitting, not by catching a
  `409`.
- **Handwriting** — two kinds, and the distinction matters. A received-stamp is noise and
  must not enter the payload. An annotation changing bank details changes *meaning* and
  belongs in front of a human, even though no API field carries it.
- **Multi-page line tables** — the totals sit on the last page; the lines do not.
- **PDFs with no text layer** — a `.pdf` extension promises nothing. Detect, then fall back.

> **Never branch on a filename or a hardcoded invoice number.** If a check only works
> because you knew which file it was, it does not work. Any such branch is a defect
> regardless of the output it produces.

---

## Architecture

```
invoices/          The input set. Read-only. Never modified.
src/
  extract/         Document → structured data. The only place a model is called.
  verify/          Pure functions. Deterministic. No I/O, no model, no network.
  register/        The accounting API client. The only place that talks to :8080.
  review/          The human queue: what could not be automated, and why.
out/               Run artifacts — extractions, decisions, the review queue. Gitignored.
```

**`verify/` is pure.** If you are about to import an HTTP client or a model SDK into it,
stop — you are solving the problem in the wrong place. Its whole value is that it can be
tested against fabricated inputs, instantly, for free, with no key.

**Routing is a cost decision, not a convenience.** A PDF with a usable text layer must not
be sent to a vision model — that pays image rates for text already in hand. Route on
detected content, never on file extension, and fall back when detection says the layer is
empty.

---

## Rules

- **Money is an integer in JPY.** No amount is ever typed `float` or `Decimal`. A float
  appears in exactly one place — the tax formula above — and never as an amount.
- **Dates are `YYYY-MM-DD` at every boundary.** Parsing happens once, at extraction; from
  there inward the format is invariant.
- **Never auto-register an invoice with an unresolved field.** Ambiguity routes to review.
  Registering "our best guess" is the failure mode this system exists to prevent.
- **Every rejection carries a structured reason and the evidence for it** — enough for a
  person to act without reopening the source document.
- **No silent defaults.** A missing due date is not "issue date + 30." It is missing.
- **A model call is a network call.** It gets an explicit timeout, and its raw response is
  recorded before anything parses it.
- **Raw model output is persisted before parsing.** When something is wrong, the question
  is always "what did it actually say," and that answer must not require paying again.
- **Duplicate identity is `(partner_code, invoice_number)`** — detected locally, before
  submission, never by catching a `409`.
- Every extraction records its input, its prompt version, and its raw output — enough to
  reproduce the conditions, if not the bytes.

---

## Scope

**This is a working core, not a product.** Scope is capped deliberately; breadth is not a
goal and unrequested features are not a contribution. Absences are recorded and defended
in `SUBMISSION.md`, not quietly filled in.

Deliberately out of scope: authentication, persistence beyond flat files, multi-currency,
concurrent runs, retraining or fine-tuning, and any deployment target other than local.

If a new top-level folder or a new dependency seems necessary — **stop and ask.**
