"""Enforces the structural claims CLAUDE.md makes about this codebase.

CLAUDE.md is a document, and a document nothing enforces is a document that drifts.
These tests convert its checkable claims into failures. They are static, offline, run in
well under a second, and need no API key.

WHAT THIS DOES NOT CHECK — stated so a green run is not mistaken for a full one:

  - "Raw model output is persisted before parsing" — behavioural, needs the extractor to
    exist. Becomes a real test once `src/extract/` has a callable seam to stub.
  - "No silent defaults" and "every rejection carries evidence" — judgement, not structure.
  - Whether the *verification logic itself* is correct. That is `test_verify.py`'s job.
    This file only proves the code is shaped the way the contract says it is.

"COULDN'T CHECK" MUST NEVER LOOK LIKE "CHECKED AND CLEAN". Before `src/` contains any
Python, every check here skips loudly rather than passing. The moment it does, they arm
themselves — and `test_expected_packages_exist` fails if the layout drifted away from the
one CLAUDE.md describes, so the skips can never quietly become permanent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

# The packages CLAUDE.md's Architecture section names.
EXPECTED_PACKAGES = ("extract", "verify", "register", "review")

# `verify/` is pure: no I/O, no model, no network. Anything here is a violation.
IMPURE_MODULES = {
    "anthropic", "openai", "google", "boto3",           # model SDKs
    "requests", "httpx", "urllib", "http", "socket",    # network
    "os", "pathlib", "shutil", "tempfile", "io",        # filesystem
    "subprocess", "sqlite3", "pickle", "random", "time",
}

# Sibling packages `verify/` must not reach into — purity is a dependency claim too.
IMPURE_SIBLINGS = {"extract", "register", "review"}

# Amount-bearing field names. None of these may ever be typed `float` or `Decimal`.
MONEY_NAMES = (
    "amount", "price", "total", "subtotal", "tax_amount",
    "unit_price", "sum", "balance", "yen", "jpy",
)

# Literals that would mean the code recognises the sample set instead of the problem.
SAMPLE_FILE_STEMS = tuple(f"invoice_{n:02d}" for n in range(1, 13))
SAMPLE_INVOICE_NUMBERS = (
    "YM-2026-0107", "YM-2026-0122",
    "SATO-260118", "SATO-260205",
    "OSK-26-0112", "OSK-26-0128",
    "TF-2026-0115", "TF-2026-0125",
    "MIT-2026-011", "MIT-2026-014",
    "SSL-2026-0203",
)


def python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


SRC_FILES = python_files(SRC)
SCAFFOLDED = bool(SRC_FILES)

needs_source = pytest.mark.skipif(
    not SCAFFOLDED,
    reason="src/ contains no Python yet — nothing to check. This skip disappears the "
           "moment the first module lands, and must not be allowed to become permanent.",
)


@needs_source
def test_expected_packages_exist():
    """The layout has not drifted away from the one CLAUDE.md describes.

    Without this, deleting or renaming `verify/` would silently disarm the purity check
    below rather than failing anything. If the layout genuinely changes, edit CLAUDE.md
    and this constant together — that is the reconciliation working, not a nuisance.
    """
    missing = [name for name in EXPECTED_PACKAGES if not (SRC / name).is_dir()]
    assert not missing, (
        f"CLAUDE.md's Architecture section names packages that do not exist: {missing}. "
        "Either create them or update CLAUDE.md — the contract and the tree must agree."
    )


@needs_source
def test_verify_package_is_pure():
    """CLAUDE.md: 'verify/ is pure. No I/O, no model, no network.'

    Its whole value is being testable against fabricated inputs, instantly, for free,
    with no key. One import of an HTTP client destroys that property permanently.
    """
    violations: list[str] = []

    for path in python_files(SRC / "verify"):
        for node in ast.walk(parsed(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in IMPURE_MODULES:
                        violations.append(f"{rel(path)}:{node.lineno} imports '{alias.name}'")

            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:  # relative: `from ..register import ...`
                    reached = (node.module or "").split(".")[0]
                    if reached in IMPURE_SIBLINGS:
                        violations.append(
                            f"{rel(path)}:{node.lineno} reaches into sibling package '{reached}'"
                        )
                    continue
                top = (node.module or "").split(".")[0]
                if top in IMPURE_MODULES:
                    violations.append(f"{rel(path)}:{node.lineno} imports from '{node.module}'")

    assert not violations, "verify/ is not pure:\n  " + "\n  ".join(violations)


@needs_source
def test_nothing_branches_on_the_sample_set():
    """CLAUDE.md: 'Never branch on a filename or a hardcoded invoice number.'

    A check that only works because you knew which file it was does not work. Matching on
    string *constants* rather than raw text is deliberate: naming `invoice_09` in a comment
    to explain a hazard is fine and useful. Putting it in a literal the code compares
    against is the defect.

    Docstrings are exempt for the same reason, and that exemption was earned: the first
    clean-code run of this check failed on a docstring reading "see invoice_09 in the
    notes" — flagging the explanatory prose the rule above explicitly permits.

    tests/ is exempt by construction — this file itself is full of these strings, and a
    fixture naturally names the document it was built from.
    """
    needles = SAMPLE_FILE_STEMS + SAMPLE_INVOICE_NUMBERS
    violations: list[str] = []

    for path in SRC_FILES:
        tree = parsed(path)

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            hit = next((n for n in needles if n in node.value), None)
            if hit:
                violations.append(f"{rel(path)}:{node.lineno} contains sample literal '{hit}'")

    assert not violations, (
        "Source recognises the sample set instead of the problem:\n  "
        + "\n  ".join(violations)
    )


@needs_source
def test_money_is_never_a_float():
    """CLAUDE.md: 'Money is an integer in JPY. No amount is ever typed float or Decimal.'

    Deliberately NOT a blanket ban on `float`. The tax formula must mirror the accounting
    system's own `floor(subtotal_for_code * rate)`, floating-point included, because that
    system is the authority — reimplementing it in integer arithmetic is arguably more
    correct and is therefore wrong here. So this bans floats *on amounts*, which is the
    actual claim, rather than banning the type outright.
    """
    def is_money(name: str) -> bool:
        low = name.lower()
        return any(m in low for m in MONEY_NAMES)

    def annotation_name(node: ast.expr | None) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):  # Optional[float], list[float]
            return " ".join(
                annotation_name(n)
                for n in ast.walk(node.slice)
                if isinstance(n, (ast.Name, ast.Attribute))
            )
        return ""

    violations: list[str] = []

    for path in SRC_FILES:
        for node in ast.walk(parsed(path)):
            target, annotation = None, None

            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, annotation = node.target.id, node.annotation
            elif isinstance(node, ast.arg) and node.annotation is not None:
                target, annotation = node.arg, node.annotation

            if target is None or not is_money(target):
                continue

            found = annotation_name(annotation)
            if "float" in found or "Decimal" in found:
                violations.append(
                    f"{rel(path)}:{node.lineno} money field '{target}' is typed '{found}'"
                )

    assert not violations, "Amounts must be integer JPY:\n  " + "\n  ".join(violations)
