"""Normalising Japanese text before comparing it.

A supplier name is one string on the page and another in the master, and the difference is
usually presentation rather than identity: full-width Latin letters from a form field,
half-width katakana from a legacy system, a company form printed `㈱` where the master
spells out `株式会社`. Comparing the raw strings reports a known supplier as unknown.

**Exact matching on a normalised form — deliberately not fuzzy matching.** A similarity
score can produce a *wrong* match, and a wrong partner code is a payment to the wrong
company. That is the failure this system exists to prevent, so no amount of convenience
buys it. Normalisation only removes differences that carry no meaning; whatever survives it
must still be equal, character for character.

NFKC is the Unicode compatibility normalisation. It maps `Ｔ` to `T`, `１` to `1`,
half-width katakana to full-width, and `㈱` to `(株)` — the whole class of width and form
variation in one table lookup, rather than a list of characters someone remembered.

`unicodedata` is stdlib and a pure table lookup: no I/O, no network. It does not breach
this package's purity.
"""

from __future__ import annotations

import unicodedata

# NFKC turns `㈱` into `(株)`, which is closer but still not the master's `株式会社`.
# Expanding the abbreviation to the long form is right; *stripping* the company form
# would be wrong — `株式会社山田` and `有限会社山田` are different legal entities.
_COMPANY_FORMS = {
    "(株)": "株式会社",
    "(有)": "有限会社",
    "(合)": "合同会社",
    "(資)": "合資会社",
    "(名)": "合名会社",
}


def normalise_for_match(value: str) -> str:
    """For company names. Width, spacing, case, and company-form abbreviations collapse."""
    folded = unicodedata.normalize("NFKC", value)
    folded = "".join(folded.split())  # whitespace is layout, not identity
    for abbreviation, full_form in _COMPANY_FORMS.items():
        folded = folded.replace(abbreviation, full_form)
    return folded.casefold()


def normalise_identifier(value: str) -> str:
    """For invoice numbers. Width, case, and every separator collapse.

    Punctuation goes entirely, and that is a deliberate choice made by looking at the
    output rather than at the intention. Keeping hyphens was the first instinct — they
    separate meaningful segments of a supplier's numbering scheme — but it means
    `YM 2026-0107` and `YM-2026-0107` compare as different invoices, and OCR reads a
    separator as a space, a hyphen, or nothing at all depending on the scan.

    The two possible errors are not symmetric. Over-normalising can only merge two
    documents that are not the same invoice, which stops and goes to a person. Under-
    normalising lets a real duplicate through, and that is a second payment. Where the
    costs are that lopsided, the aggressive form is the safe one.
    """
    folded = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in folded if ch.isalnum()).casefold()


def normalise_registration(value: str) -> str:
    """For the national registration number — the strongest key available.

    Everything that is not a letter or a digit goes: the same T-number is printed with
    hyphens, with spaces, and with neither. Note that `str.isalnum()` is true for
    full-width digits, so the NFKC pass is what actually makes `Ｔ１２３` and `T123` equal.
    """
    folded = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in folded if ch.isalnum()).upper()
