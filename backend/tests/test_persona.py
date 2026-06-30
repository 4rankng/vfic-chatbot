"""Structural guard for the 7-part VFIC agent persona (persona.md).

The persona is intentionally no longer byte-pinned to the legacy n8n workflow —
it is hand-edited and config-driven (loaded from persona.md at import). These
tests guard against accidental deletion/corruption of persona.md and verify the
7-part framework stays intact, plus spot-check that critical operational rules
survived the restructure.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.graph.context import active_projects_index
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.schemas.personas import PersonaUpdate
from app.services.persona_service import PersonaService

EXPECTED_SECTIONS = [
    "### 1. Vai trò của tôi",
    "### 2. Ai sẽ cần sự hỗ trợ của tôi?",
    "### 3. Tôi thực hiện công việc như thế nào?",
    "### 4. Tôi nên tránh điều gì?",
    "### 5. Bạn muốn tôi theo dõi kết quả nào?",
    "### 6. Tôi nên giao tiếp với mọi người như thế nào?",
    "### 7. Lưu ý thêm",
]

# Operational rules that must survive any persona restructure.
CRITICAL_RULES = [
    "MỘT TIN NHẮN - MỘT CÂU HỎI",  # one-question-per-message cadence
    "Tra cứu lịch xe structured",  # bus-timetable structured-tool-first rule
    "SỐ ĐIỆN THOẠI",  # phone-capture conversion goal
    "KHÔNG tự tạo thông tin",  # anti-hallucination / no fabrication beyond data
    "tiếng Việt",  # Vietnamese-only
]


def test_persona_loads_non_empty():
    assert AGENT_SYSTEM_PROMPT, "persona.md loaded empty"
    assert len(AGENT_SYSTEM_PROMPT) > 500


def test_persona_has_exactly_seven_sections():
    assert AGENT_SYSTEM_PROMPT.count("### ") == 7
    for header in EXPECTED_SECTIONS:
        assert header in AGENT_SYSTEM_PROMPT, f"missing section header: {header!r}"


def test_persona_preserves_critical_rules():
    for needle in CRITICAL_RULES:
        assert needle in AGENT_SYSTEM_PROMPT, f"missing critical rule text: {needle!r}"


@pytest.mark.asyncio
async def test_active_projects_index_includes_project_persona_overrides(monkeypatch):
    class _Repo:
        def __init__(self, _db):
            pass

        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="lg-display",
                    name="LG Display",
                    summary="Tuyển công nhân sản xuất",
                    index_card={"key_roles": ["Operator"], "location": "Hai Phong"},
                    persona_name="Persona LGD",
                    persona_body_md="### Vai trò\nTư vấn riêng cho LG Display.",
                )
            ]

    monkeypatch.setattr("app.graph.context.RetrievalRepository", _Repo)

    prompt = await active_projects_index(SimpleNamespace())

    assert "=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ===" in prompt
    assert "lg-display (LG Display)" in prompt
    assert "=== PERSONA RIÊNG THEO DỰ ÁN ===" in prompt
    assert "Slug: lg-display" in prompt
    assert "Agent: Persona LGD" in prompt
    assert "Tư vấn riêng cho LG Display." in prompt


@pytest.mark.asyncio
async def test_persona_service_update_returns_404_for_missing_id():
    """PersonaService.update raises 404 when persona not found."""
    mock_db = AsyncMock()
    mock_db.get.return_value = None

    svc = PersonaService(mock_db)
    admin = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await svc.update(uuid.uuid4(), PersonaUpdate(), admin)
    assert exc_info.value.status_code == 404
