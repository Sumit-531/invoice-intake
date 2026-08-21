"""Deterministic local verification. Pure functions: no I/O, no model, no network.

That purity is the whole value. Every check here runs against fabricated inputs,
instantly, for free, with no API key — which is what makes it possible to watch a check
fail on a corrupted invoice before trusting it on a real one.

The checks are ranked, strongest first, and this is the order they run in:

  1. Arithmetic  — recompute from the lines. Deterministic, free, offline.
  2. Master data — the partner list and the tax codes. External ground truth.
  3. The accounting API — genuinely independent, but it costs a round trip and arrives
     last. Checks 1 and 2 must pass here before a POST is attempted at all.

A model's own confidence is not on that list. It is a routing signal, never a gate: the
extractor and any checker built from it share one understanding of the document, so a
defect living in that understanding survives both.

NOT YET HERE: duplicate detection on (partner_code, invoice_number). It is a pure check
and belongs in this package, but it needs more than one invoice to mean anything.
"""

from __future__ import annotations

from ..models import ExtractedInvoice, Partner, TaxCode
from .arithmetic import Amounts, check_amounts, recompute
from .dates import check_dates
from .masters import check_lines_are_registrable, resolve_partner, resolve_tax_codes
from .result import Finding, Verification

__all__ = [
    "Amounts",
    "Finding",
    "Verification",
    "check_amounts",
    "check_dates",
    "recompute",
    "resolve_partner",
    "resolve_tax_codes",
    "verify_extraction",
]


def verify_extraction(
    invoice: ExtractedInvoice,
    partners: list[Partner],
    tax_codes: list[TaxCode],
) -> Verification:
    """Run every local check. Collects all findings rather than stopping at the first.

    A person looking at a rejected invoice should see everything wrong with it in one
    pass. Reporting one problem, being corrected, then reporting the next wastes the
    reviewer's time and hides how badly an extraction went.
    """
    findings: list[Finding] = []

    findings.extend(check_dates(invoice))
    findings.extend(check_lines_are_registrable(invoice))

    partner_code, _matched_by, partner_findings = resolve_partner(invoice, partners)
    findings.extend(partner_findings)

    tax_code_by_line, tax_findings = resolve_tax_codes(invoice, tax_codes)
    findings.extend(tax_findings)

    if tax_findings:
        # Without a tax code for every line there is no rate to apply, so the
        # recalculation cannot run. Reporting a fabricated total alongside the real
        # failure would only make the real failure harder to see.
        return Verification(findings=tuple(findings), partner_code=partner_code)

    rate_by_code = {entry.tax_code: entry.rate for entry in tax_codes}
    computed = recompute(invoice, tax_code_by_line, rate_by_code)
    findings.extend(check_amounts(invoice, computed))

    return Verification(
        findings=tuple(findings),
        partner_code=partner_code,
        tax_code_by_line=tax_code_by_line,
        subtotal=computed.subtotal,
        tax_amount=computed.tax_amount,
        total_amount=computed.total_amount,
        tax_by_code=computed.tax_by_code,
    )
