"""Tests for CLI helper functions — no LLM calls, no typer integration."""

from __future__ import annotations

from pathlib import Path

from docstore.cli import _resolve_store_for_path


def test_resolve_store_derives_from_directory(tmp_path):
    """Default --store on a directory path → <dir>/.docstore (matches benchmark)."""
    assert _resolve_store_for_path(tmp_path, ".docstore") == str(tmp_path / ".docstore")


def test_resolve_store_derives_from_file_path(tmp_path):
    """Default --store on a file path → <file's parent>/.docstore."""
    f = tmp_path / "invoice.txt"
    f.write_text("placeholder")
    assert _resolve_store_for_path(f, ".docstore") == str(tmp_path / ".docstore")


def test_resolve_store_honors_explicit_override(tmp_path):
    """When the user passes --store explicitly, that value wins regardless of path."""
    explicit = "/some/other/cache"
    assert _resolve_store_for_path(tmp_path, explicit) == explicit
