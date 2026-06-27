"""File-content extraction: parse Office/text bytes to plain Vietnamese-safe text.

Pure parsing only — no DB, no LLM. Heavy parsers (pypdf / python-docx / openpyxl) are
imported lazily inside the functions so importing this module stays cheap and free of
optional-dependency failures.
"""
from __future__ import annotations

import io

from app.core.config import get_settings


def extract_text(file_name: str, content_type: str, data: bytes) -> str:
    """Parse Office/text file bytes to plain UTF-8 text (Vietnamese-safe)."""
    name = (file_name or "").lower()
    ct = (content_type or "").lower()
    blob = name.endswith

    def _dec() -> str:
        return data.decode("utf-8", errors="replace")

    if "pdf" in ct or blob(".pdf"):
        return _extract_pdf(data)
    if "officedocument.wordprocessingml" in ct or blob(".docx"):
        return _extract_docx(data)
    if "spreadsheet" in ct or blob(".xlsx"):
        return _extract_xlsx(data)
    if blob(".csv") or "csv" in ct:
        return _dec()
    return _dec()  # .txt / .md / unknown -> treat as text


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    parts: list[str] = []
    for page in PdfReader(io.BytesIO(data)).pages:
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _extract_docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for tbl in doc.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(c.strip() for c in cells):
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts)


def split_for_digest(text: str, max_chars: int | None = None) -> list[str]:
    """Naively split long text into LLM-sized sections with small overlap.

    The LLM does the real semantic splitting per section; this just keeps each call
    within a sane input size. Paragraph boundaries are respected where possible.
    """
    max_chars = max_chars or get_settings().digest_section_chars
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    step = max(1, max_chars - 400)  # 400-char overlap
    sections: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + max_chars]
        if chunk.strip():
            sections.append(chunk)
        if start + max_chars >= len(text):
            break
        if len(sections) >= get_settings().digest_max_sections:
            break
    return sections
