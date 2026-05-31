"""
Parser subagent — converts any supported file to clean plain text.
No LLM calls. Pure extraction.

Supported: PDF, DOCX, TXT, MD, CSV, HTML
"""

from __future__ import annotations

from pathlib import Path


def parse(file_path: Path) -> str:
    """Return the plain text content of a file."""
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(file_path)
    elif suffix in (".docx", ".doc"):
        return _parse_docx(file_path)
    elif suffix in (".txt", ".md", ".csv", ".html", ".htm", ".json"):
        return file_path.read_text(encoding="utf-8", errors="replace")
    else:
        # Best-effort: try reading as text
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            raise ValueError(
                f"Unsupported file type: {suffix}. "
                "Supported: pdf, docx, txt, md, csv, html, json"
            ) from e


def _parse_pdf(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ImportError("pypdf is required for PDF parsing: pip install pypdf") from e

    reader = PdfReader(str(file_path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Page {i + 1}]\n{text.strip()}")
    if not pages:
        raise ValueError(
            f"No extractable text found in PDF: {file_path}. "
            "Scanned or image-only PDFs require OCR; OCR is not supported yet."
        )
    return "\n\n".join(pages)


def _parse_docx(file_path: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise ImportError(
            "python-docx is required for DOCX parsing: pip install python-docx"
        ) from e

    doc = Document(str(file_path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return len(text) // 4
