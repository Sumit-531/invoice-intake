"""What a check produces when it is unhappy.

Every rejection carries a structured reason and the evidence for it — enough for a person
to act without reopening the source document. `code` is what routing branches on; the
message is for a human and nothing may parse it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Verification:
    """The outcome of every local check, plus what those checks resolved.

    `partner_code` and `tax_code_by_line` are outputs rather than inputs: they are what
    the master data resolved to, and they exist only when nothing blocked. Registration
    reads them from here, so an invoice that failed a check has nothing to submit with.
    """

    findings: tuple[Finding, ...] = ()
    partner_code: str | None = None
    tax_code_by_line: tuple[str, ...] = ()
    subtotal: int = 0
    tax_amount: int = 0
    total_amount: int = 0
    tax_by_code: tuple[tuple[str, int], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(finding.code for finding in self.findings)
