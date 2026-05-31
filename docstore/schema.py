"""
Schema primitives for docstore.

Users define what they want to extract by subclassing ExtractionSchema
or letting the orchestrator build one from natural language.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


# Supported field types the orchestrator normalises to
FIELD_TYPES = {"string", "number", "boolean", "date", "list[string]", "list[object]"}


class SchemaDescriptor(BaseModel):
    """
    Canonical, hashable representation of an extraction schema.

    Created either from a user-defined ExtractionSchema subclass
    or from a natural-language description via the orchestrator.

    The version field is a sha256 of the fields dict — it changes
    automatically when any field is added, removed, or renamed.
    """

    name: str
    fields: dict[str, str]  # field_name -> type hint
    version: str = ""       # auto-computed from fields

    model_config = {"frozen": True}

    def model_post_init(self, __context: Any) -> None:
        # Compute version from fields if not provided
        if not self.version:
            object.__setattr__(self, "version", self._hash_fields())

    def _hash_fields(self) -> str:
        canonical = json.dumps(self.fields, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def cache_token(self) -> str:
        return f"{self.name}:{self.version}"

    def to_prompt_fragment(self) -> str:
        """Render schema as a JSON template for the extractor prompt."""
        template = {k: f"<{v}>" for k, v in self.fields.items()}
        return json.dumps(template, indent=2)

    @classmethod
    def from_dict(cls, name: str, fields: dict[str, str]) -> "SchemaDescriptor":
        return cls(name=name, fields=fields)


class ExtractionSchema:
    """
    Base class for user-defined schemas.

    Usage:
        class InvoiceSchema(ExtractionSchema):
            vendor: str
            amount: float
            currency: str
            due_date: str
            paid: bool

    The class annotations are introspected to build a SchemaDescriptor.
    Type hints are mapped to docstore field types automatically.
    """

    _TYPE_MAP: dict[Any, str] = {
        str:       "string",
        int:       "number",
        float:     "number",
        bool:      "boolean",
        list:      "list[string]",
    }

    @classmethod
    def to_descriptor(cls) -> SchemaDescriptor:
        hints = {}
        for name, annotation in cls.__annotations__.items():
            if name.startswith("_"):
                continue
            mapped = cls._TYPE_MAP.get(annotation, "string")
            hints[name] = mapped
        return SchemaDescriptor(name=cls.__name__, fields=hints)


class ExtractionResult(BaseModel):
    """The output of a successful extraction pipeline run."""

    schema_name: str
    schema_version: str
    schema_fields: dict[str, str] = {}
    file_path: str
    file_hash: str
    data: dict[str, Any]
    valid: bool
    validation_issues: list[str] = []
    cache_hit: bool = False
    tokens_used: int = 0
    tokens_saved: int = 0
    model: str = ""
    extracted_at: str = ""

    def cache_key(self) -> str:
        return f"{self.file_hash}:{self.schema_name}:{self.schema_version}"


class DiffResult(BaseModel):
    """Output of the diff subagent comparing two versions of a document."""

    schema_name: str
    file_path: str
    changed_fields: list[str]
    previous: dict[str, Any]
    current: dict[str, Any]
    summary: str
    previous_hash: str
    current_hash: str
