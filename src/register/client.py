"""HTTP client for the mock accounting system.

Its specification cannot change; it is treated as a system owned by another team. Every
response is the same envelope — `{"success", "data", "error"}` — and every error carries a
structured `code`. Branching is on that code, never on the message string: messages are
written for people and are free to change, codes are the interface.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from ..config import ACCOUNTING_API_KEY, ACCOUNTING_API_URL, HTTP_TIMEOUT_SECONDS
from ..models import Partner, RegisteredInvoice, TaxCode


class AccountingUnreachable(RuntimeError):
    """The accounting system did not answer. Distinct from it answering with a refusal."""


@dataclass(frozen=True)
class Registration:
    """The outcome of one POST. A refusal is an outcome, not an exception."""

    status: int
    accepted: bool
    accounting_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict | None = None


class AccountingClient:
    def __init__(
        self,
        base_url: str = ACCOUNTING_API_URL,
        api_key: str = ACCOUNTING_API_KEY,
        timeout: int = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-API-Key": api_key})

    def _request(self, method: str, path: str, json_body: dict | None = None):
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                method, url, json=json_body, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise AccountingUnreachable(
                f"{method} {url} failed: {type(exc).__name__}: {exc}\n"
                "Start it with `python accounting_api.py`, or set ACCOUNTING_API_URL if "
                "it is listening somewhere else."
            ) from exc

        try:
            return response.status_code, response.json()
        except ValueError as exc:
            raise AccountingUnreachable(
                f"{method} {url} returned {response.status_code} with a body that is not "
                f"JSON. Something other than the accounting system may be bound to this "
                f"address.\n{response.text[:200]}"
            ) from exc

    def _get_data(self, path: str) -> dict:
        status, body = self._request("GET", path)
        if status != 200 or not body.get("success"):
            error = body.get("error") or {}
            raise AccountingUnreachable(
                f"GET {path} returned {status}: "
                f"{error.get('code')} {error.get('message')}"
            )
        return body["data"]

    def health(self) -> dict:
        return self._get_data("/health")

    def partners(self) -> list[Partner]:
        return [Partner(**item) for item in self._get_data("/partners")["partners"]]

    def tax_codes(self) -> list[TaxCode]:
        return [TaxCode(**item) for item in self._get_data("/tax-codes")["tax_codes"]]

    def invoices(self) -> list[RegisteredInvoice]:
        """What the accounting system already holds — the input to duplicate detection.

        Fetched at the start of every run rather than remembered between runs. This system
        is in-memory and resets on restart; a ledger of ours would not, and would start
        blocking invoices that are no longer registered.
        """
        records = self._get_data("/invoices")["invoices"]
        return [RegisteredInvoice.model_validate(record) for record in records]

    def create_invoice(self, payload: dict) -> Registration:
        status, body = self._request("POST", "/invoices", payload)

        if status == 201 and body.get("success"):
            return Registration(
                status=status,
                accepted=True,
                accounting_id=body["data"]["accounting_id"],
            )

        error = body.get("error") or {}
        return Registration(
            status=status,
            accepted=False,
            error_code=error.get("code"),
            error_message=error.get("message"),
            error_details=error.get("details"),
        )
