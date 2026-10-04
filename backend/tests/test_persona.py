"""Structural guard for the VFIC agent persona.

The persona is a code constant (``app.prompts.vfic_persona.DEFAULT_PERSONA_BODY_MD``)
and this file is the only copy: persona storage was removed on 2026-10-04, so an
accidental edit here changes the bot's voice on the next deploy with nothing else
to compare it against. These tests guard against deletion/corruption of the body
and verify the core operational rules survive any restructure. The persona is
authored in the Studio's 7-part format — the seven section headers below are the
authoring contract, and every operational rule must remain present.
"""

from types import SimpleNamespace

import pytest

from app.graph.context import active_projects_index
from app.graph.prompts import AGENT_SYSTEM_PROMPT

# Operational rules that must survive any persona restructure. Each is a
# behavior the agent must follow — losing any of these changes the bot's
# product behavior in a way the dashboard/conversion metrics depend on.
CRITICAL_RULES = [
    "Thu thập SỐ ĐIỆN THOẠI DI ĐỘNG",  # §5 — contact-capture mission
    "Số di động là thông tin liên hệ bắt buộc duy nhất",
    "HỌ TÊN ĐẦY ĐỦ rất nên có",
    "NGUYỆN VỌNG hữu ích",
    "NĂM SINH tùy chọn",
    "Mỗi tin nhắn chỉ hỏi một lần ở câu chốt cuối cùng",  # §5 — one ask per message
    "TUYỆT ĐỐI KHÔNG BỊA ĐẶT",  # §4 — anti-fabrication
    "MỌI dự án đang hoạt động đều có thể xuất hiện — không bỏ sót, không xếp việc lẻ",  # §3 — introduce by project, never a job dump
    'CẤM dùng từ "bạn", "quý khách", "ứng viên", "người lao động"',  # §6 — address form
    "không in đậm",  # §6 — plain-text output
    "Tuyệt đối không hỏi lại những điều ứng viên đã cung cấp",  # §3 — never re-ask
    "Luôn dùng tiếng Việt chuẩn mực",  # §6 — Vietnamese-only
]


def test_persona_loads_non_empty():
    assert AGENT_SYSTEM_PROMPT, "persona.md loaded empty"
    # The persona is ~5.3KB. This floor catches corruption
    # (empty/truncated file) without forcing a specific verbosity.
    assert len(AGENT_SYSTEM_PROMPT) > 1500


def test_persona_has_core_sections():
    """The persona must cover role, communication rules, tools, and limits.

    The seven `### N. ...` headers are the authoring contract Persona Studio
    parses; they must match PERSONA_SECTIONS exactly (numbering included).
    """
    topics = [
        "### 1. Vai trò của tôi",
        "### 2. Ai sẽ cần sự hỗ trợ của tôi?",
        "### 3. Tôi thực hiện công việc như thế nào?",
        "### 4. Tôi nên tránh điều gì?",
        "### 5. Bạn muốn tôi theo dõi kết quả nào?",
        "### 6. Tôi nên giao tiếp với mọi người như thế nào?",
        "### 7. Lưu ý thêm",
    ]
    for topic in topics:
        assert topic in AGENT_SYSTEM_PROMPT, f"persona missing topic: {topic!r}"


def test_persona_preserves_critical_rules():
    for needle in CRITICAL_RULES:
        assert needle in AGENT_SYSTEM_PROMPT, f"missing critical rule text: {needle!r}"


@pytest.mark.asyncio
async def test_active_projects_index_excludes_project_persona_overrides():
    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="lg-display",
                    name="LG Display",
                    aliases=["LG", "LGD"],
                    summary="Tuyển công nhân sản xuất",
                    index_card={"key_roles": ["Operator"], "location": "Hai Phong"},
                    persona_name="Persona LGD",
                    persona_body_md="### Vai trò\nTư vấn riêng cho LG Display.",
                )
            ]

    prompt = await active_projects_index(_Repo())

    assert "=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ===" in prompt
    assert "lg-display (LG Display)" in prompt
    assert "bí danh: LG, LGD" in prompt
    assert "=== PERSONA RIÊNG THEO DỰ ÁN ===" not in prompt
    assert "Tư vấn riêng cho LG Display." not in prompt


@pytest.mark.asyncio
async def test_active_projects_index_renders_highlights_from_index_card():
    """Directory lines carry the card's highlights so the bot can advertise them.

    Highlights come only from ``index_card.highlights`` — the key both the
    ingestion card schema and ``sync_highlights`` write — never from anywhere else.
    """

    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="samsung-bac-ninh",
                    name="Samsung Bắc Ninh",
                    aliases=[],
                    summary="Tuyển dụng quy mô lớn liên tục",
                    index_card={
                        "roles": ["Công nhân SMT"],
                        "location": "Bắc Ninh",
                        "highlights": ["Xe đưa đón", "Bao ăn ở", ""],
                    },
                )
            ]

    prompt = await active_projects_index(_Repo())

    assert "samsung-bac-ninh (Samsung Bắc Ninh)" in prompt
    assert "địa điểm: Bắc Ninh" in prompt
    assert "nổi bật: Xe đưa đón, Bao ăn ở" in prompt


@pytest.mark.asyncio
async def test_active_projects_index_omits_the_highlights_segment_when_the_card_has_none():
    """No highlights → no 'nổi bật' segment, so nothing invites invented benefits."""

    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="foxconn-nghe-an",
                    name="Foxconn Nghệ An",
                    aliases=[],
                    summary="Sản xuất linh kiện điện tử",
                    index_card={"location": "Nghệ An"},
                ),
                SimpleNamespace(
                    slug="lg-display",
                    name="LG Display Hải Phòng",
                    aliases=[],
                    summary="Tuyển công nhân sản xuất",
                    index_card={"location": "Hải Phòng", "highlights": []},
                ),
            ]

    prompt = await active_projects_index(_Repo())

    assert "nổi bật:" not in prompt
    assert "địa điểm: Nghệ An" in prompt


@pytest.mark.asyncio
async def test_active_projects_index_carries_the_vague_seeker_rule():
    """Vague seekers get the whole directory, grounded to card fields only.

    The rule lives inside the directory block (not the static rules) so it is
    present exactly when the DANH MỤC it points at exists, and hiring claims
    stay anchored to ``list_active_projects`` evidence.
    """

    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="lg-display",
                    name="LG Display Hải Phòng",
                    aliases=[],
                    summary="Tuyển công nhân sản xuất",
                    index_card={"location": "Hải Phòng"},
                )
            ]

    prompt = await active_projects_index(_Repo())

    assert "tìm việc chung chung" in prompt
    assert "DANH MỤC" in prompt
    assert "list_active_projects" in prompt
    assert "không bịa điểm nổi bật" in prompt


def test_runtime_rules_fixed_facts_do_not_advertise_a_single_project():
    """The always-on fixed facts name no factory; enumeration belongs to DANH MỤC.

    A hardcoded example here is what made the bot advertise exactly one
    workplace on company-identity turns. The office-vs-plant discriminator and
    the office facts must survive the strip.
    """
    from app.graph.context import _RUNTIME_RETRIEVAL_RULES

    # The exact advertisement regression: the parenthetical example and the
    # single-factory workplace claim. (A bare "LG Display" mention survives in
    # the KB-name contact rule — that one cannot be echoed as a workplace.)
    assert "ví dụ LG Display" not in _RUNTIME_RETRIEVAL_RULES
    assert "làm việc tại nhà máy LG Display" not in _RUNTIME_RETRIEVAL_RULES
    assert "Trảng Duệ" not in _RUNTIME_RETRIEVAL_RULES
    # Office facts + the PHÂN BIỆT BẮT BUỘC discriminator survive.
    assert "PHÂN BIỆT BẮT BUỘC" in _RUNTIME_RETRIEVAL_RULES
    assert "Manhattan là VĂN PHÒNG công ty" in _RUNTIME_RETRIEVAL_RULES
    assert "MST 0201307104" in _RUNTIME_RETRIEVAL_RULES
    assert "DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG" in _RUNTIME_RETRIEVAL_RULES


def test_runtime_rules_answer_near_home_from_tool_distance():
    """``gần nhà`` must be answered from the tool's ``distance_km``, never invented."""
    from app.graph.context import _RUNTIME_RETRIEVAL_RULES

    assert "HỎI DỰ ÁN GẦN NHÀ" in _RUNTIME_RETRIEVAL_RULES
    assert "distance_km" in _RUNTIME_RETRIEVAL_RULES
    assert "không tự bịa khoảng cách" in _RUNTIME_RETRIEVAL_RULES


def test_tingting_support_prompt_excludes_the_recruitment_directory():
    """The support OA's prompt never carries the directory or the vague-seeker rule.

    The lane never builds ``build_system_prompt`` for that account (see the
    runner-turn tests), so the directory can only leak if someone embeds it
    into the support persona itself — this pins that boundary.
    """
    from app.graph.tingting_guide import tingting_support_system_prompt

    for prompt in (
        tingting_support_system_prompt(include_guide=False, hotline="+84 914 827 988"),
        tingting_support_system_prompt(include_guide=True, hotline="+84 914 827 988"),
    ):
        assert "DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG" not in prompt
        assert "tìm việc chung chung" not in prompt
        assert "list_active_projects" not in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_cache_key_carries_the_prompt_text_revision(monkeypatch):
    """The cache suffix embeds the revision, so a rule-text release re-assembles.

    Without it a deploy changing the static rules would keep serving the old
    prompt from Redis until the 10-min TTL lapsed. The provider separation in
    the key must survive.
    """
    from app.graph import context

    captured: dict[str, str] = {}

    async def _caching(factory, *, key_suffix="default"):
        captured["suffix"] = key_suffix
        return await factory(), False

    monkeypatch.setattr(context, "cached_system_prompt", _caching)

    class _Repo:
        async def active_projects_with_card(self):
            return []

    prompt, cache_hit = await context.build_system_prompt(_Repo(), provider="zalo_oa")

    assert cache_hit is False
    assert captured["suffix"] == f"zalo_oa:r{context._PROMPT_TEXT_REVISION}"
    # The persona is the code constant now, so a repository that cannot serve
    # a project index still yields the real persona rather than a placeholder.
    assert AGENT_SYSTEM_PROMPT in prompt
    assert "SỐ ĐIỆN THOẠI DI ĐỘNG hợp lệ là thông tin liên hệ bắt buộc duy nhất" in prompt
    assert "ưu tiên hơn mục tiêu cũ trong persona" in prompt
    assert "không bắt phải có vị trí job riêng" in prompt.casefold()

    await context.build_system_prompt(_Repo())
    assert captured["suffix"] == f"default:r{context._PROMPT_TEXT_REVISION}"
