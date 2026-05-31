"""Tests for the store layer — no LLM calls."""

from __future__ import annotations

from datetime import datetime, timezone

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


def make_result(file_path, fhash, descriptor, data=None, extracted_at=None):
    return ExtractionResult(
        schema_name=descriptor.name,
        schema_version=descriptor.version,
        schema_fields=descriptor.fields,
        file_path=str(file_path),
        file_hash=fhash,
        data=data or {"vendor": "Acme Corp", "amount": 1200, "due_date": "2026-06-01"},
        valid=True,
        validation_issues=[],
        cache_hit=False,
        tokens_used=450,
        tokens_saved=0,
        model="claude-haiku-4-5-20251001",
        extracted_at=extracted_at or datetime.now(timezone.utc).isoformat(),
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


def test_schema_fields_persisted_through_set_get(tmp_store, sample_file, descriptor):
    """schema_fields must survive the set→disk→get round trip so callers can
    rebuild a full SchemaDescriptor from a cached entry."""
    fhash = tmp_store.file_hash(sample_file)
    tmp_store.set(make_result(sample_file, fhash, descriptor))

    retrieved = tmp_store.get(sample_file, descriptor)
    assert retrieved is not None
    assert retrieved.schema_fields == descriptor.fields


def test_find_for_path_locates_entry_after_file_change(tmp_store, sample_file, descriptor):
    """The whole point of find_for_path: locate the previous entry even after
    the file's content (and therefore its hash) has changed. The old
    hash-keyed lookup couldn't do this — diff was broken because of it."""
    original_hash = tmp_store.file_hash(sample_file)
    tmp_store.set(make_result(sample_file, original_hash, descriptor))

    # Mutate the file — hash changes
    sample_file.write_text("Completely different content")
    new_hash = tmp_store.file_hash(sample_file)
    assert new_hash != original_hash

    # find_for_path still locates the previous entry by file path
    found = tmp_store.find_for_path(sample_file, descriptor.name)
    assert found is not None
    assert found.file_hash == original_hash
    assert found.schema_fields == descriptor.fields


def test_find_for_path_returns_most_recent_by_extracted_at(tmp_store, sample_file, descriptor):
    """When multiple entries exist for the same (path, schema), find_for_path
    returns the latest by extracted_at — needed for incremental ingest where
    a file may have been extracted multiple times across content versions."""
    fhash = tmp_store.file_hash(sample_file)

    older = make_result(sample_file, fhash, descriptor,
                        data={"vendor": "Old"}, extracted_at="2025-01-01T00:00:00Z")
    tmp_store.set(older)

    sample_file.write_text("changed content")
    new_hash = tmp_store.file_hash(sample_file)
    newer = make_result(sample_file, new_hash, descriptor,
                        data={"vendor": "New"}, extracted_at="2026-06-01T00:00:00Z")
    tmp_store.set(newer)

    found = tmp_store.find_for_path(sample_file, descriptor.name)
    assert found is not None
    assert found.data == {"vendor": "New"}


def test_find_for_path_returns_none_for_unknown(tmp_store, sample_file, descriptor):
    """No match → None, not an exception. Callers rely on this for the
    'no previous extraction' UX path."""
    assert tmp_store.find_for_path(sample_file, "nonexistent_schema") is None

    # Even with cached entries under a different schema, no match for ours
    tmp_store.set(make_result(sample_file, tmp_store.file_hash(sample_file), descriptor))
    assert tmp_store.find_for_path(sample_file, "different_schema") is None


def test_find_for_path_ignores_other_files(tmp_store, sample_file, descriptor, tmp_path):
    """Entries for a different file_path under the same schema must not leak
    into this file's lookup."""
    other_file = tmp_path / "other.txt"
    other_file.write_text("unrelated content")

    tmp_store.set(make_result(sample_file, tmp_store.file_hash(sample_file),
                              descriptor, data={"vendor": "Mine"}))
    tmp_store.set(make_result(other_file, tmp_store.file_hash(other_file),
                              descriptor, data={"vendor": "Other"}))

    found = tmp_store.find_for_path(sample_file, descriptor.name)
    assert found is not None
    assert found.data == {"vendor": "Mine"}
