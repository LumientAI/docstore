"""Tests for the store layer — no LLM calls."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from docstore.schema import ExtractionResult, SchemaDescriptor
from docstore.store import DocStore


@pytest.fixture
def tmp_store(tmp_path):
    return DocStore(root=tmp_path / ".docstore")


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "invoice.txt"
    f.write_text("Vendor: Acme Corp\nAmount: $1,200\nDue: 2026-06-01")
    return f


@pytest.fixture
def descriptor():
    return SchemaDescriptor(
        name="invoice_schema",
        fields={"vendor": "string", "amount": "number", "due_date": "date"},
    )


def make_result(file_path, fhash, descriptor, data=None):
    return ExtractionResult(
        schema_name=descriptor.name,
        schema_version=descriptor.version,
        file_path=str(file_path),
        file_hash=fhash,
        data=data or {"vendor": "Acme Corp", "amount": 1200, "due_date": "2026-06-01"},
        valid=True,
        validation_issues=[],
        cache_hit=False,
        tokens_used=450,
        tokens_saved=0,
        model="claude-haiku-4-5-20251001",
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )


def test_set_and_get(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    retrieved = tmp_store.get(sample_file, descriptor)
    assert retrieved is not None
    assert retrieved.cache_hit is True
    assert retrieved.data["vendor"] == "Acme Corp"


def test_cache_miss_returns_none(tmp_store, sample_file, descriptor):
    result = tmp_store.get(sample_file, descriptor)
    assert result is None


def test_different_schemas_same_file(tmp_store, sample_file):
    fhash = tmp_store.file_hash(sample_file)

    d1 = SchemaDescriptor(name="schema_a", fields={"vendor": "string"})
    d2 = SchemaDescriptor(name="schema_b", fields={"amount": "number"})

    r1 = make_result(sample_file, fhash, d1, data={"vendor": "Acme"})
    r2 = make_result(sample_file, fhash, d2, data={"amount": 1200})

    tmp_store.set(r1)
    tmp_store.set(r2)

    retrieved_1 = tmp_store.get(sample_file, d1)
    retrieved_2 = tmp_store.get(sample_file, d2)

    assert retrieved_1 is not None
    assert retrieved_2 is not None
    assert retrieved_1.data == {"vendor": "Acme"}
    assert retrieved_2.data == {"amount": 1200}


def test_file_change_invalidates_cache(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    # Modify the file
    sample_file.write_text("Vendor: Beta Corp\nAmount: $2,000")

    # Cache should miss because file hash changed
    retrieved = tmp_store.get(sample_file, descriptor)
    assert retrieved is None


def test_schema_version_changes_on_field_change():
    d1 = SchemaDescriptor(name="s", fields={"vendor": "string"})
    d2 = SchemaDescriptor(name="s", fields={"vendor": "string", "amount": "number"})
    assert d1.version != d2.version


def test_query_returns_matching_schema(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    results = tmp_store.query("invoice_schema")
    assert len(results) == 1
    assert results[0].data["vendor"] == "Acme Corp"


def test_query_with_filter(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor, data={"vendor": "Acme", "paid": False})
    tmp_store.set(result)

    # Filter matching
    results = tmp_store.query("invoice_schema", lambda r: r.data.get("paid") is False)
    assert len(results) == 1

    # Filter not matching
    results = tmp_store.query("invoice_schema", lambda r: r.data.get("paid") is True)
    assert len(results) == 0


def test_stats(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    s = tmp_store.stats()
    assert s["total_entries"] == 1
    assert s["total_tokens_cached"] == 450
    assert s["estimated_cost_to_recompute_usd"] == round(450 / 1_000_000 * 1.00, 4)
    assert "invoice_schema" in s["schema_counts"]


def test_list_schemas(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    schemas = tmp_store.list_schemas()
    assert "invoice_schema" in schemas


def test_delete(tmp_store, sample_file, descriptor):
    fhash = tmp_store.file_hash(sample_file)
    result = make_result(sample_file, fhash, descriptor)
    tmp_store.set(result)

    deleted = tmp_store.delete(sample_file, descriptor)
    assert deleted is True

    retrieved = tmp_store.get(sample_file, descriptor)
    assert retrieved is None
