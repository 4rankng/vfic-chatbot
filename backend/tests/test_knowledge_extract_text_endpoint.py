"""POST /knowledge/documents/extract-text: stateless editor pre-fill extraction.

The endpoint exists so a text editor can surface .docx content in place — the
browser cannot decode the OOXML container — without creating a knowledge
document or enqueueing the training pipeline. These tests drive the route over
HTTP on a bare app and pin the full format contract: markdown, text, DOCX and
XLSX extract; unsupported/binary formats and YAML answer 422 with the service's
own Vietnamese reason; the shared 20 MiB ceiling still applies upstream.
"""

from __future__ import annotations

import uuid
import zipfile
from io import BytesIO
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge as knowledge_api
from app.api.auth_dependencies import require_admin
from app.core.errors import register_domain_exception_handlers
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_bytes(paragraph: str) -> bytes:
    """A minimal OOXML container: one part, one paragraph of Word text."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{_WORD_NS}"><w:body>'
            f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    return buffer.getvalue()


def _xlsx_bytes(sheet_xml: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def _client() -> TestClient:
    app = FastAPI()
    # The production edge maps DomainError → its status code; the bare app
    # needs the same registration for the 422 rejections to serialize.
    register_domain_exception_handlers(app)
    app.include_router(knowledge_api.router, prefix="/api/v1")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_project_knowledge_db] = lambda: SimpleNamespace()
    return TestClient(app)


def test_markdown_extracts_to_text_without_storing_anything() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={"file": ("quy-trinh.md", b"# Quy trinh\n\nNoi dung.", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "# Quy trinh\n\nNoi dung."}


def test_docx_extracts_paragraph_text() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={
            "file": (
                "tuyen-dung.docx",
                _docx_bytes("Tuyen dung lao dong pho thong"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Tuyen dung lao dong pho thong"}


def test_xlsx_extracts_tab_separated_rows() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={
            "file": (
                "lich-lam.xlsx",
                _xlsx_bytes(
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Ca</t></is></c>'
                    '<c r="B1" t="inlineStr"><is><t>Gio</t></is></c></row></sheetData></worksheet>'
                ),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Ca\tGio"}


def test_an_unsupported_binary_format_answers_422() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={"file": ("brief.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )

    assert response.status_code == 422
    assert "errors" in response.json()["detail"]


def test_yaml_is_refused_by_name() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={"file": ("categories.yaml", b"jobs: []", "application/yaml")},
    )

    assert response.status_code == 422
    assert "YAML" in response.json()["detail"]["errors"][0]


def test_an_empty_document_answers_422() -> None:
    response = _client().post(
        "/api/v1/knowledge/documents/extract-text",
        files={"file": ("trong.md", b"   \n\t", "text/markdown")},
    )

    assert response.status_code == 422
