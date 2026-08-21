"""Domain types shared across the pipeline.

These live outside `extract/` deliberately. `verify/` is pure and may not reach into a
sibling package, so a schema owned by `extract/` could not be typed through the checker
without breaking that rule. Putting the vocabulary in the middle keeps every layer
honest: `extract/` produces these, `verify/` inspects them, `register/` serialises them.

WHAT THE MODEL IS ASKED FOR, AND WHAT IT IS NOT
-----------------------------------------------
`ExtractedInvoice` holds what was *read off the page* — nothing derived. In particular
`printed_subtotal` / `printed_tax_amount` / `printed_total` are transcriptions of the
figures the supplier printed, and the extraction prompt forbids computing them.

That distinction is the whole arithmetic check. If the model were allowed to add the
lines up itself, its total would agree with its lines by construction and comparing them
would prove nothing. Two independent readings — the lines, and the printed summary — is
what makes a dropped line or a digit slip visible.

The partner code and the per-line tax code are absent on purpose. Both are resolved
against the accounting system's masters, deterministically, downstream. A model does not
get to invent an identifier that a real ledger will act on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

# Money is an integer number of yen. `StrictInt` rather than `int` so that a model
# returning 150000.0 or "150,000" is a validation failure at the boundary rather than a
# silent coercion two layers later.
JPY = StrictInt


class ExtractedLine(BaseModel):
    """One row of the invoice's line table, exactly as printed."""

    # No `extra="forbid"` here or on ExtractedInvoice, though strictness would be the
    # instinct. Pydantic renders it as `additionalProperties: false`, and Gemini's schema
    # dialect rejects that field outright — the request fails before generation. The
    # protection is not lost, only moved: this schema is enforced by the provider on the
    # wire, so unrequested fields cannot come back in the first place.
    description: StrictStr
    quantity: StrictInt | None = Field(
        default=None, description="Null when the row prints no quantity."
    )
    unit: StrictStr | None = Field(
        default=None, description="Null when the row prints no unit. Never invented."
    )
    unit_price: JPY | None = Field(
        default=None, description="Null when the row prints no unit price."
    )
    amount: JPY = Field(description="The row's line total. Negative for a discount.")
    tax_rate_percent: StrictInt = Field(
        description="The consumption tax rate applying to this row, as a whole number."
    )


class ExtractedInvoice(BaseModel):
    """A supplier invoice as read. Unverified by construction."""

    invoice_number: StrictStr
    supplier_name: StrictStr = Field(
        description="The issuer of the invoice, not the addressee."
    )
    supplier_registration_no: StrictStr | None = None

    issue_date: StrictStr = Field(description="Normalised to YYYY-MM-DD.")
    issue_date_raw: StrictStr = Field(
        description="The date exactly as printed. Evidence for a human, and the only way "
        "to audit a calendar conversion without reopening the document."
    )
    due_date: StrictStr | None = None
    due_date_raw: StrictStr | None = None

    printed_subtotal: JPY | None = None
    printed_tax_amount: JPY | None = None
    printed_total: JPY | None = None

    lines: list[ExtractedLine] = Field(min_length=1)

    handwriting_note: StrictStr | None = Field(
        default=None,
        description="Set when handwriting appears to change the invoice's meaning. "
        "Transcribed, never acted on.",
    )


class Partner(BaseModel):
    """An entry in the accounting system's supplier master. Ground truth."""

    model_config = ConfigDict(extra="ignore")

    partner_code: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    registration_no: str | None = None


class TaxCode(BaseModel):
    """An entry in the accounting system's tax-code master. Ground truth."""

    model_config = ConfigDict(extra="ignore")

    tax_code: str
    rate: float  # not an amount: the multiplier the accounting system applies
    label: str = ""
