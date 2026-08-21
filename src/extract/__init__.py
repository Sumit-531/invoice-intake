"""Document → structured data. The only place in the codebase a model is called."""

from .document import Route, SourceDocument, load_document
from .extractor import ExtractionResult, extract_invoice

__all__ = [
    "ExtractionResult",
    "Route",
    "SourceDocument",
    "extract_invoice",
    "load_document",
]
