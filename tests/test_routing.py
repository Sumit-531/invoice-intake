"""Routing and rendering, checked offline against the real input set.

Two claims are under test, and both are claims `CLAUDE.md` makes in its own voice:

  "Route on detected content, never on file extension, and fall back when detection says
   the layer is empty."

  "Never branch on a filename. If a check only works because you knew which file it was,
   it does not work."

`test_contract.py` enforces the second one statically, by refusing to let a sample filename
appear as a string constant in `src/`. That is necessary and not sufficient: code can
branch on `path.suffix` without ever naming a sample, and a suite that only greps for
literals would call that clean. This file closes the gap behaviourally — it renames files
and asserts the decision does not move.

Nothing here names an invoice either. The documents are discovered and sorted into routes
at runtime, so the tests keep working if the input set changes, and they cannot quietly
start passing because someone special-cased the file they happened to reference.

No network, no API key, no model. Rendering is local arithmetic on pixels.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest

from src.extract.document import TEXT_LAYER_MIN_CHARS, Route, load_document
from src.extract.extractor import prompt_version_for
from src.extract.render import MAX_EDGE_PX, render_pages

INVOICES = Path(__file__).resolve().parent.parent / "invoices"

ALL_DOCUMENTS = sorted(p for p in INVOICES.iterdir() if p.is_file())


def _first_document_routed(route: Route):
    for path in ALL_DOCUMENTS:
        if load_document(path).route is route:
            return path
    pytest.skip(f"no document in the input set routes to {route.value}")


# ---------------------------------------------------------------------------
# Every document is readable, and every one gets a route
# ---------------------------------------------------------------------------


def test_the_input_set_is_not_empty():
    """Guards every test below. A vanished `invoices/` would otherwise turn this whole
    file into a silent no-op that still reports green."""
    assert ALL_DOCUMENTS, "no documents found — the routing tests would all be vacuous"


@pytest.mark.parametrize("path", ALL_DOCUMENTS, ids=lambda p: p.name)
def test_every_document_opens_and_is_routed(path):
    """Including the images. PyMuPDF opens a JPEG as a one-page document, which is what
    lets one measurement decide the route for every input regardless of format."""
    document = load_document(path)

    assert document.page_count >= 1
    assert document.route in (Route.TEXT, Route.VISION)
    assert len(document.sha256) == 64


@pytest.mark.parametrize("path", ALL_DOCUMENTS, ids=lambda p: p.name)
def test_the_route_follows_the_measured_text_layer(path):
    """The rule, stated as an assertion: the route is a function of the character count
    and of nothing else. Not the extension, not the page count, not the file size."""
    document = load_document(path)
    expected = (
        Route.TEXT if document.text_char_count >= TEXT_LAYER_MIN_CHARS else Route.VISION
    )

    assert document.route is expected


# ---------------------------------------------------------------------------
# The extension is not consulted. Renaming proves it.
# ---------------------------------------------------------------------------


def test_a_text_layer_pdf_renamed_to_an_image_extension_still_routes_to_text(tmp_path):
    """The expensive mistake, in the direction that costs money. A text-layer document sent
    down the vision route pays image rates for characters already in hand."""
    source = _first_document_routed(Route.TEXT)
    disguised = tmp_path / "not_really_an_image.jpg"
    shutil.copyfile(source, disguised)

    assert load_document(disguised).route is Route.TEXT


def test_a_scan_saved_as_a_pdf_still_routes_to_vision(tmp_path):
    """The mistake in the direction that costs correctness. A `.pdf` extension promises
    nothing; trusting it sends an empty text layer to the extractor and gets an empty
    invoice back."""
    source = _first_document_routed(Route.VISION)
    disguised = tmp_path / "looks_like_a_document.pdf"
    shutil.copyfile(source, disguised)

    assert load_document(disguised).route is Route.VISION


def test_renaming_a_file_changes_nothing_the_pipeline_depends_on(tmp_path):
    """The identity of a document is its content. That is what makes the raw-response cache
    safe to key on a hash: the same bytes under a new name hit the same entry and cost no
    request, and a *different* document can never collide with one just because it was
    given a familiar filename."""
    source = _first_document_routed(Route.TEXT)
    renamed = tmp_path / "something_else_entirely.dat"
    shutil.copyfile(source, renamed)

    original, copy = load_document(source), load_document(renamed)

    assert original.sha256 == copy.sha256
    assert original.route is copy.route
    assert original.text_char_count == copy.text_char_count
    assert prompt_version_for(original) == prompt_version_for(copy)


def test_the_two_routes_do_not_share_a_prompt_version():
    """A shared version string would mean adding the vision route invalidated every cached
    text response — one request per document, against a 20-per-day ceiling, to recover
    output that was already correct."""
    text = _first_document_routed(Route.TEXT)
    vision = _first_document_routed(Route.VISION)

    assert prompt_version_for(load_document(text)) != prompt_version_for(
        load_document(vision)
    )


# ---------------------------------------------------------------------------
# Rendering — one image per page, and a ceiling on what a page can cost
# ---------------------------------------------------------------------------


def test_every_page_is_rendered_in_order():
    """Order is the contract. A multi-page line table read out of order puts rows under the
    wrong headings, and nothing downstream can tell."""
    path = _first_document_routed(Route.VISION)
    document = load_document(path)

    images = render_pages(path)

    assert len(images) == document.page_count
    assert [image.page_number for image in images] == list(
        range(1, document.page_count + 1)
    )


def test_a_rendered_page_is_jpeg_bytes_and_never_touches_the_disk():
    path = _first_document_routed(Route.VISION)

    image = render_pages(path)[0]

    assert image.data.startswith(b"\xff\xd8\xff"), "not a JPEG"
    assert image.byte_count == len(image.data) > 0
    assert image.width > 0 and image.height > 0


@pytest.mark.parametrize("path", ALL_DOCUMENTS, ids=lambda p: p.name)
def test_no_page_renders_larger_than_the_ceiling(path):
    """An image is billed by area. DPI alone is unbounded — a large-format page renders to
    whatever its dimensions dictate — so the clamp is what puts a price ceiling on a single
    document arriving from a supplier nobody vetted."""
    for image in render_pages(path):
        assert max(image.width, image.height) <= MAX_EDGE_PX


def test_an_oversized_page_is_scaled_down_rather_than_rendered_at_full_dpi(tmp_path):
    """Constructed rather than sampled, because the input set happens not to contain a
    page big enough to trip the clamp. A check that cannot fire on any available input is
    not a check, so the input is fabricated: a 2-metre-wide page, which no supplier will
    ever send and which is exactly why the ceiling must hold without one."""
    oversized = tmp_path / "oversized.pdf"
    document = pymupdf.open()
    document.new_page(width=5600, height=800)  # points, ~197cm across
    document.save(oversized)
    document.close()

    image = render_pages(oversized)[0]

    assert max(image.width, image.height) == pytest.approx(MAX_EDGE_PX, abs=2)
