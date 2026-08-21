"""The extraction prompt, and its version.

The version is part of the cache key. Change the prompt, change the version — otherwise a
cached response from the previous wording is served against the new schema and the run is
reproducible only by accident.

The instructions describe *classes* of Japanese invoice, never the documents in the
sample set. An instruction that only works because someone knew which file was coming is
not an instruction, it is a hardcoded answer.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """\
You are transcribing a Japanese supplier invoice (請求書) into structured data for an
accounting system. Transcribe only. Do not compute, infer, correct, or fill in anything
that is not printed on the document.

WHO THE SUPPLIER IS
The supplier is the company that ISSUED the invoice and expects to be paid. It is not the
addressee. The addressee is the party being billed and is usually printed first, marked
with 御中 or 様, sometimes with a department such as 経理部. Never report the addressee as
the supplier. The issuer's block is the one carrying a registration number (登録番号,
beginning with T), a phone number, or bank transfer details.

DATES
Report every date twice: once exactly as printed (`*_raw`), and once normalised to
YYYY-MM-DD.
- 2026年1月7日 and 2026/01/07 and 2026-01-07 are the same date.
- Japanese era years must be converted. 令和 year N is Gregorian 2018 + N. 平成 year N is
  1988 + N. So 令和8年2月5日 is 2026-02-05.
- If a due date (支払期日 / お支払期限 / 振込期日) is not printed, report null. Do not
  derive one from the issue date or from payment terms.

AMOUNTS
Every amount is a whole number of yen. Strip separators: 150,000 is 150000.
A leading △ or ▲ or ﹣ or ▽ marks a NEGATIVE amount — discounts, returns, and adjustments
are printed this way. 値引き, 返品 and 調整 rows are commonly negative. Report them as
negative numbers. Reporting a discount as positive is the single most damaging error you
can make here, because it moves the total by twice the discount.

LINE ITEMS
One entry per row of the line table, in the order printed.
- `description` is the 品名 / 摘要 text.
- `quantity`, `unit` (単位) and `unit_price` (単価) are null when that row does not print
  them. Service, freight and handling rows frequently print only an amount. Do not invent
  a value; null is the correct answer and is handled downstream.
- `amount` (金額) is the row's total and is always present.
- If the line table continues across several pages, include every row from every page.
  The summary block appears only on the last page; the rows do not.

TAX RATE PER LINE
`tax_rate_percent` is the consumption tax rate for that row as a whole number — for
Japanese invoices, 10 for the standard rate and 8 for the reduced rate on food and
beverages.
- If the invoice shows a single tax line covering everything, every row takes that rate.
- If the invoice breaks tax down by rate (10%対象 / 8%対象), or marks rows with ※ or a
  similar reduced-rate mark, assign each row the rate that applies to it. The per-rate
  subtotals printed in the summary tell you which rows belong to which rate.

THE PRINTED SUMMARY — TRANSCRIBE, DO NOT CALCULATE
`printed_subtotal` (小計), `printed_tax_amount` (消費税) and `printed_total` (合計 /
請求金額) must be the figures the supplier printed, character for character.
Do NOT add up the line items to produce them. These figures are checked against an
independent recalculation from the lines, and that check is the main defence against a
misread row. If you calculate them yourself, the check compares your arithmetic to your
own arithmetic and catches nothing. If a figure is genuinely not printed, report null.

HANDWRITING
If handwriting appears on the document, judge whether it changes what the invoice means.
- A received stamp, a date stamp, a filing mark, initials or a 受領/検収 stamp are office
  noise. Ignore them entirely.
- Handwriting that alters payment instructions, bank details, an amount, or a date does
  change the meaning. Transcribe it verbatim into `handwriting_note` and leave every other
  field showing what is PRINTED. Do not apply the handwritten change yourself.

If a field is unreadable or absent, report null. A guess is worse than a gap: a gap stops
the invoice and brings in a person, a guess becomes a payment.
"""


def build_prompt(document_text: str) -> str:
    """Assemble the text-route prompt for one document."""
    return (
        f"{_INSTRUCTIONS}\n"
        "--- BEGIN INVOICE TEXT ---\n"
        f"{document_text}\n"
        "--- END INVOICE TEXT ---\n"
    )
