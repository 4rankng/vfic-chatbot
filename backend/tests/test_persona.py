"""Structural guard for the 7-part VFIC agent persona (persona.md).

The persona is intentionally no longer byte-pinned to the legacy n8n workflow —
it is hand-edited and config-driven (loaded from persona.md at import). These
tests guard against accidental deletion/corruption of persona.md and verify the
7-part framework stays intact, plus spot-check that critical operational rules
survived the restructure.
"""

from app.graph.prompts import AGENT_SYSTEM_PROMPT

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
