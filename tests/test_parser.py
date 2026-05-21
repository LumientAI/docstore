"""Tests for the parser subagent."""

from pathlib import Path
import tempfile

from docstore.agents.parser import estimate_tokens, parse


def test_parse_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello world\nThis is a test.")
    result = parse(f)
    assert "Hello world" in result


def test_parse_md(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("# Title\n\nSome content here.")
    result = parse(f)
    assert "Title" in result


def test_parse_json(tmp_path):
    f = tmp_path / "test.json"
    f.write_text('{"key": "value"}')
    result = parse(f)
    assert "value" in result


def test_estimate_tokens():
    text = "a" * 400
    assert estimate_tokens(text) == 100


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
