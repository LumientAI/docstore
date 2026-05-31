from importlib.metadata import PackageNotFoundError, version as _pkg_version

from docstore.schema import (
    DiffResult,
    ExtractionResult,
    ExtractionSchema,
    SchemaDescriptor,
)
from docstore.store import DocStore

__all__ = [
    "DocStore",
    "ExtractionSchema",
    "SchemaDescriptor",
    "ExtractionResult",
    "DiffResult",
]

try:
    __version__ = _pkg_version("lumient-docstore")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
