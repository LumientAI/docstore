"""Tests for CLI helper functions — no LLM calls, no typer integration."""

from __future__ import annotations


from typer.testing import CliRunner

from docstore.cli import _resolve_provider_model, _resolve_store_for_path, app


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


def test_resolve_provider_model_defaults_to_anthropic_haiku():
    assert _resolve_provider_model("anthropic", None) == "claude-haiku-4-5-20251001"


def test_resolve_provider_model_uses_provider_defaults():
    assert _resolve_provider_model("openai", None) == "gpt-5.4-mini"
    assert _resolve_provider_model("groq", None) == "llama-3.3-70b-versatile"
    assert _resolve_provider_model("gemini", None) == "gemini-2.5-flash"


def test_resolve_provider_model_honors_explicit_model():
    assert _resolve_provider_model("openai", "gpt-custom") == "gpt-custom"


def test_invalid_provider_is_rejected():
    result = CliRunner().invoke(app, ["extract", "missing.txt", "--provider", "bogus"])

    assert result.exit_code != 0
