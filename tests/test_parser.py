"""Tests for the parser subagent."""


import pytest

from docstore.agents.parser import estimate_tokens, parse


def _write_text_pdf(path, pages: list[str]) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import (
        DictionaryObject,
        NameObject,
        NumberObject,
        StreamObject,
        TextStringObject,
    )

    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=144)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = StreamObject()
        stream._data = (
            f"BT /F1 12 Tf 36 96 Td ({TextStringObject(text)}) Tj ET"
        ).encode("utf-8")
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Rotate")] = NumberObject(0)

    with open(path, "wb") as f:
        writer.write(f)


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


def test_parse_pdf_with_embedded_text(tmp_path):
    f = tmp_path / "invoice.pdf"
    _write_text_pdf(f, ["Invoice ACME-001 Total EUR 42.00"])

    result = parse(f)

    assert result.startswith("[Page 1]")
    assert "Invoice ACME-001" in result
    assert "Total EUR 42.00" in result


def test_parse_pdf_preserves_page_markers(tmp_path):
    f = tmp_path / "multipage.pdf"
    _write_text_pdf(f, ["First page vendor", "Second page total"])

    result = parse(f)

    assert "[Page 1]" in result
    assert "[Page 2]" in result
    assert "First page vendor" in result
    assert "Second page total" in result


def test_parse_pdf_without_extractable_text_raises_clear_error(tmp_path):
    from pypdf import PdfWriter

    f = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=144)
    with open(f, "wb") as out:
        writer.write(out)

    with pytest.raises(ValueError, match="No extractable text.*OCR is not supported"):
        parse(f)


def test_estimate_tokens():
    text = "a" * 400
    assert estimate_tokens(text) == 100


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
