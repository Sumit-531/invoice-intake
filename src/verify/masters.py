"""Checks against the accounting system's master data — external ground truth.

The masters arrive as arguments. Fetching them is `register/`'s job; this module cannot
reach the network and that is the point. The model cannot argue with a master list, which
is what makes this the second-strongest check available.

A supplier absent from the master is not a bug and not a retry. That invoice can never be
registered, and saying so is the correct output.
"""

from __future__ import annotations

from ..models import ExtractedInvoice, Partner, TaxCode
from .result import Finding


def _normalise(value: str) -> str:
    """Whitespace and case are presentation, not identity."""
    return "".join(value.split()).casefold()


def _normalise_registration(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum()).upper()


def resolve_partner(
    invoice: ExtractedInvoice, partners: list[Partner]
) -> tuple[str | None, str | None, list[Finding]]:
    """Return (partner_code, how_it_matched, findings).

    Match order is strongest key first. The registration number is a national identifier
    and is worth more than any name comparison: a supplier may print an abbreviation, a
    trading name, or a division, but the T-number is the same number every time.
    """
    printed_registration = invoice.supplier_registration_no
    if printed_registration:
        target = _normalise_registration(printed_registration)
        for partner in partners:
            if partner.registration_no and _normalise_registration(
                partner.registration_no
            ) == target:
                return partner.partner_code, "registration_no", []

    printed_name = _normalise(invoice.supplier_name)
    for partner in partners:
        if _normalise(partner.name) == printed_name:
            return partner.partner_code, "name", []

    for partner in partners:
        for alias in partner.aliases:
            if _normalise(alias) == printed_name:
                return partner.partner_code, "alias", []

    return (
        None,
        None,
        [
            Finding(
                "PARTNER_NOT_FOUND",
                "The supplier on this invoice is not in the accounting system's partner "
                "master, under its name, any registered alias, or its registration "
                "number. It cannot be registered until a person adds it.",
                {
                    "supplier_as_printed": invoice.supplier_name,
                    "registration_no_as_printed": printed_registration,
                    "known_partners": [p.name for p in partners],
                },
            )
        ],
    )


def resolve_tax_codes(
    invoice: ExtractedInvoice, tax_codes: list[TaxCode]
) -> tuple[tuple[str, ...], list[Finding]]:
    """Map each line's printed rate onto a tax code from the master.

    A rate is what the document prints; a code is what crosses the API boundary. The
    mapping is built from the master rather than hardcoded, so a rate the accounting
    system does not recognise fails here — loudly, locally, and for free — instead of
    arriving back as an UNKNOWN_TAX_CODE after a round trip.
    """
    by_percent: dict[int, list[str]] = {}
    for entry in tax_codes:
        by_percent.setdefault(round(entry.rate * 100), []).append(entry.tax_code)

    findings: list[Finding] = []
    resolved: list[str] = []

    for index, line in enumerate(invoice.lines):
        candidates = by_percent.get(line.tax_rate_percent, [])
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue
        resolved.append("")
        if not candidates:
            findings.append(
                Finding(
                    "UNKNOWN_TAX_RATE",
                    f"Line {index + 1} was read as {line.tax_rate_percent}% consumption "
                    "tax, which the accounting system does not recognise.",
                    {
                        "line": index + 1,
                        "description": line.description,
                        "rate_percent_read": line.tax_rate_percent,
                        "known_rates_percent": sorted(by_percent),
                    },
                )
            )
        else:
            findings.append(
                Finding(
                    "AMBIGUOUS_TAX_RATE",
                    f"Line {index + 1} was read as {line.tax_rate_percent}%, which maps "
                    "to more than one tax code in the master. A person must choose.",
                    {
                        "line": index + 1,
                        "rate_percent_read": line.tax_rate_percent,
                        "candidate_tax_codes": candidates,
                    },
                )
            )

    return tuple(resolved), findings


def check_lines_are_registrable(invoice: ExtractedInvoice) -> list[Finding]:
    """Fields the accounting system requires, which the document may not have printed.

    `unit` is required and non-empty on every line there. When a row prints no unit, the
    correct answer is not to invent one — it is to stop and let a person decide.
    """
    findings: list[Finding] = []
    for index, line in enumerate(invoice.lines):
        if not line.unit or not line.unit.strip():
            findings.append(
                Finding(
                    "LINE_UNIT_MISSING",
                    f"Line {index + 1} prints no unit, and the accounting system requires "
                    "one on every line. Nothing is assumed on the invoice's behalf.",
                    {
                        "line": index + 1,
                        "description": line.description,
                        "amount": line.amount,
                    },
                )
            )
    return findings
