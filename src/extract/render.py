"""Rasterising a document into page images for the vision route.

Every input is rendered by the same rule. A scan saved as a PDF and a photograph saved as
a JPEG arrive here as the same thing — a page with no readable text layer — and asking
what the extension was would reintroduce exactly the branch `document.py` exists to avoid.
PyMuPDF opens a JPEG as a one-page document, so one code path covers both.

THE THREE NUMBERS BELOW ARE A COST DECISION
An image is billed by area, not by how much is written on it. Rendering at 600 DPI would
be sharper, cost several times more per page, and add nothing: the characters on these
documents are already resolved at 200 DPI, and a model that cannot read a glyph at that
size will not be rescued by more pixels — it will produce a confident misreading either
way, which is what verification is for.

`MAX_EDGE_PX` is the part that actually protects the budget. DPI alone is unbounded: a
large-format page renders to whatever its dimensions dictate, and one oversized document
could quietly cost more than the rest of a batch. Clamping the longest edge puts a ceiling
on the price of a single page regardless of what arrives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

RENDER_DPI = 200
MAX_EDGE_PX = 2000
JPEG_QUALITY = 85

# JPEG rather than PNG: these are photographs and scans of paper, where PNG's lossless
# encoding preserves scanner noise at several times the byte count and no legibility gain.
IMAGE_MIME_TYPE = "image/jpeg"

_POINTS_PER_INCH = 72.0


@dataclass(frozen=True)
class PageImage:
    """One rendered page, ready to send. Bytes, not a file — nothing is written to disk."""

    page_number: int
    width: int
    height: int
    data: bytes

    @property
    def byte_count(self) -> int:
        return len(self.data)


def render_pages(path: Path) -> list[PageImage]:
    """Render every page, in order.

    Order is the contract. A multi-page line table is read as a sequence, and pages
    arriving shuffled would put rows under the wrong headings with nothing downstream able
    to tell.
    """
    images: list[PageImage] = []

    with pymupdf.open(path) as document:
        for index, page in enumerate(document):
            zoom = _zoom_for(page.rect.width, page.rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            images.append(
                PageImage(
                    page_number=index + 1,
                    width=pixmap.width,
                    height=pixmap.height,
                    data=pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY),
                )
            )

    return images


def _zoom_for(width_points: float, height_points: float) -> float:
    """The scale factor that hits RENDER_DPI, unless that would breach the pixel ceiling."""
    zoom = RENDER_DPI / _POINTS_PER_INCH
    longest_edge_points = max(width_points, height_points)

    if longest_edge_points <= 0:
        return zoom

    if longest_edge_points * zoom > MAX_EDGE_PX:
        return MAX_EDGE_PX / longest_edge_points

    return zoom
