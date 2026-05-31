"""
docstore — dbt for unstructured data.

Extract once, query forever.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .llm import (
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    LLMResponse,
    ProviderName,
    create_llm_client,
)
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
    "ProviderName",
    "LLMResponse",
    "DEFAULT_PROVIDER",
    "DEFAULT_MODELS",
    "create_llm_client",
]

try:
    __version__ = _pkg_version("docstore")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
