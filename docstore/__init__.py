"""
docstore — dbt for unstructured data.

Extract once, query forever.
"""

from .schema import (
    DiffResult,
    ExtractionResult,
    ExtractionSchema,
    SchemaDescriptor,
)
from .store import DocStore

__all__ = [
    "DocStore",
    "ExtractionSchema",
    "SchemaDescriptor",
    "ExtractionResult",
    "DiffResult",
]

__version__ = "0.1.0"
