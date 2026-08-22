"""Document → structured data. The only place in the codebase a model is called."""

from .document import Route, SourceDocument, load_document
from .extractor import ExtractionResult, extract_invoice, is_cached

__all__ = [
    "ExtractionResult",
    "Route",
    "SourceDocument",
    "extract_invoice",
    "is_cached",
    "load_document",
]
