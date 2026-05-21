"""
File-based cache layer.

All extraction results are stored as JSON files in a .docstore/ directory.
Cache keys encode the file hash, schema name, and schema version so that:
  - The same document with a different schema gets a separate cache entry
  - A changed document invalidates its cache entry
  - A changed schema invalidates all entries for that schema
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import ExtractionResult, SchemaDescriptor


DEFAULT_STORE_DIR = ".docstore"


class StoreStats(dict):
    """Simple stats bag returned by DocStore.stats()."""
    pass


class DocStore:
    def __init__(self, root: Path | str = DEFAULT_STORE_DIR) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Key helpers ────────────────────────────────────────────────────────

    @staticmethod
    def file_hash(file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    @staticmethod
    def make_key(file_hash: str, descriptor: SchemaDescriptor) -> str:
        return f"{file_hash}__{descriptor.name}__{descriptor.version}"

    def _path_for_key(self, key: str) -> Path:
        return self.root / f"{key}.json"

    # ── Read / write ───────────────────────────────────────────────────────

    def get(self, file_path: Path, descriptor: SchemaDescriptor) -> ExtractionResult | None:
        fhash = self.file_hash(file_path)
        key = self.make_key(fhash, descriptor)
        path = self._path_for_key(key)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        result = ExtractionResult(**data)
        result = result.model_copy(update={"cache_hit": True})
        return result

    def set(self, result: ExtractionResult) -> None:
        key = self.make_key(result.file_hash, SchemaDescriptor(
            name=result.schema_name,
            fields={},
            version=result.schema_version,
        ))
        path = self._path_for_key(key)
        with open(path, "w") as f:
            json.dump(result.model_dump(), f, indent=2)

    def delete(self, file_path: Path, descriptor: SchemaDescriptor) -> bool:
        fhash = self.file_hash(file_path)
        key = self.make_key(fhash, descriptor)
        path = self._path_for_key(key)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Query ──────────────────────────────────────────────────────────────

    def query(
        self,
        schema_name: str,
        filter_fn: Any = None,
    ) -> list[ExtractionResult]:
        """
        Return all stored results for a given schema name.
        No LLM calls — pure JSON scan.

        filter_fn: optional callable (ExtractionResult) -> bool
        """
        results = []
        for path in self.root.glob(f"*__{schema_name}__*.json"):
            with open(path) as f:
                data = json.load(f)
            result = ExtractionResult(**data)
            if filter_fn is None or filter_fn(result):
                results.append(result)
        return results

    def list_schemas(self) -> dict[str, list[str]]:
        """
        Return all schema names and their versions present in the store.
        {schema_name: [version1, version2, ...]}
        """
        schemas: dict[str, set[str]] = {}
        for path in self.root.glob("*.json"):
            parts = path.stem.split("__")
            if len(parts) == 3:
                _, schema_name, version = parts
                schemas.setdefault(schema_name, set()).add(version)
        return {k: sorted(v) for k, v in schemas.items()}

    def list_entries_for_file(
        self, file_path: Path
    ) -> list[tuple[str, str]]:
        """
        Return all (schema_name, version) pairs cached for a given file.
        """
        fhash = self.file_hash(file_path)
        results = []
        for path in self.root.glob(f"{fhash}__*.json"):
            parts = path.stem.split("__")
            if len(parts) == 3:
                _, schema_name, version = parts
                results.append((schema_name, version))
        return results

    # ── Stats ──────────────────────────────────────────────────────────────

    def stats(self) -> StoreStats:
        entries = list(self.root.glob("*.json"))
        total_tokens_used = 0
        total_tokens_saved = 0
        schema_counts: dict[str, int] = {}

        for path in entries:
            with open(path) as f:
                data = json.load(f)
            total_tokens_used  += data.get("tokens_used", 0)
            total_tokens_saved += data.get("tokens_saved", 0)
            sname = data.get("schema_name", "unknown")
            schema_counts[sname] = schema_counts.get(sname, 0) + 1

        return StoreStats(
            total_entries=len(entries),
            schema_counts=schema_counts,
            total_tokens_used=total_tokens_used,
            total_tokens_saved=total_tokens_saved,
            estimated_cost_saved_usd=round(total_tokens_saved / 1_000_000 * 0.25, 4),
        )
