"""Reading a source file, and deciding how it has to be extracted.

Routing is on *detected content*, never on the file extension. A `.pdf` promises nothing:
a scan saved as PDF carries no text layer, and a text-layer PDF sent to a vision model
pays image rates for characters already in hand.

Every input is opened the same way, including images. PyMuPDF will open a JPEG as a
one-page document whose text layer is empty, which means the same measurement decides the
route for every file and no branch anywhere asks what the extension was.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pymupdf

# Below this many non-whitespace characters, whatever the extractor found is noise —
# a stray watermark, a scanner's embedded label — not a readable invoice. A real invoice
# carries several hundred characters at minimum; a scan carries zero. The gap between
# those two populations is wide, so the exact threshold is not load-bearing.
TEXT_LAYER_MIN_CHARS = 100


class Route(Enum):
    TEXT = "text"
    VISION = "vision"


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    sha256: str
    page_count: int
    route: Route
    text: str
    text_char_count: int

    @property
    def name(self) -> str:
        return self.path.name


def load_document(path: Path) -> SourceDocument:
    """Open a file, measure its text layer, and decide the route from what was found."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    with pymupdf.open(path) as doc:
        pages = [page.get_text() for page in doc]
        page_count = doc.page_count

    # Pages are joined with a separator so a multi-page line table stays legible to the
    # model as an ordered document rather than one run-on block.
    text = "\n".join(pages).strip()
    dense = sum(1 for ch in text if not ch.isspace())
    route = Route.TEXT if dense >= TEXT_LAYER_MIN_CHARS else Route.VISION

    return SourceDocument(
        path=path,
        sha256=digest,
        page_count=page_count,
        route=route,
        text=text,
        text_char_count=dense,
    )
