"""Runtime system-prompt assembly: active persona + master index of active products.

The persona (the bot's voice) is the active *global* persona's ``body_md`` (managed in
the admin UI), falling back to the committed ``persona.md`` when none is active so the
live bot never breaks. The "master index of active products" (user's routing model:
projects = products the candidate can choose from) is read from active ``projects`` and
appended to the prompt so the agent always knows the catalog + slugs, and scopes
``search_knowledge`` to the relevant project.

All DB lookups are best-effort: any failure collapses to ``AGENT_SYSTEM_PROMPT`` so a
persona/index hiccup can never break a chat turn. SQL lives in
``app.services.retrieval.RetrievalRepository``; this module only assembles the prompt.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.services.retrieval import RetrievalRepository

_INDEX_HEADER = "\n\n=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ==="
_PROJECT_PERSONA_HEADER = "\n\n=== PERSONA RIÊNG THEO DỰ ÁN ==="

_RUNTIME_RETRIEVAL_RULES = """

=== QUY TẮC TRA CỨU BẮT BUỘC ===
- Với câu hỏi về liên hệ, admin, số điện thoại, hotline, Zalo, hoặc "đến công ty liên hệ ai": phải tra search_knowledge trước khi kết luận.
- Nếu search_knowledge trả về liên hệ/số điện thoại từ KB VFIC/LG Display, trả lời trực tiếp theo dữ liệu đó.
- Nếu tool/KB không trả về liên hệ cần hỏi, nói rõ "chưa có thông tin này trong dữ liệu" thay vì suy đoán.
""".strip()

_STALE_REFUSAL_RULE_MARKERS = (
    "bảo mật",
    "riêng tư",
    "thông tin cá nhân",
    "người dùng khác",
    "ứng viên/người dùng khác",
    "lịch hẹn riêng",
    "số cá nhân",
)


def _strip_stale_refusal_rules(persona: str) -> str:
    """Remove stale refusal rules from DB-managed personas."""
    lines = []
    for line in (persona or "").splitlines():
        normalized = line.casefold()
        if any(marker in normalized for marker in _STALE_REFUSAL_RULE_MARKERS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


async def resolve_persona(db: AsyncSession) -> str:
    """Return the active global persona body (stripped of stale refusal rules), or persona.md if none is active."""
    try:
        body = await RetrievalRepository(db).active_persona_body()
        if body and body.strip():
            return _strip_stale_refusal_rules(body.strip())
    except Exception:  # noqa: BLE001
        pass
    return AGENT_SYSTEM_PROMPT


async def active_projects_index(db: AsyncSession) -> str:
    """Compact catalog of active projects (the agent's master index). '' if none/err."""
    try:
        rows = await RetrievalRepository(db).active_projects_with_card()
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    persona_groups: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        card = r.index_card or {}
        roles = ", ".join(card.get("key_roles") or [])
        loc = card.get("location") or ""
        seg = f"- {r.slug} ({r.name})"
        if r.summary:
            seg += f": {r.summary}"
        if roles:
            seg += f"; vị trí: {roles}"
        if loc:
            seg += f"; địa điểm: {loc}"
        lines.append(seg)

        persona_body = _strip_stale_refusal_rules(
            str(getattr(r, "persona_body_md", "") or "")
        )
        if persona_body:
            persona_name = str(getattr(r, "persona_name", "") or "Agent dự án")
            persona_groups.setdefault((persona_name, persona_body), []).append(str(r.slug))

    prompt = (
        _INDEX_HEADER
        + "\n" + "\n".join(lines)
        + "\nKhi ứng viên quan tâm một dự án cụ thể: với câu hỏi về thu nhập/lương, ca làm, tăng ca, "
          "phụ cấp, KTX, xe đưa đón, thưởng, hồ sơ... hãy gọi get_product_features(project_slug) để lấy "
          "các đặc điểm sản phẩm; với câu hỏi mở/tìm thêm chi tiết, gọi search_knowledge(project_slug). "
          "Riêng câu hỏi về tuyến xe, điểm đón hoặc giờ đón phải dùng search_bus_timetable trước, "
          "không dùng get_product_features thay cho lịch xe chi tiết. "
          "TUYỆT ĐỐI chỉ tư vấn bám sát dữ liệu trả về; dữ liệu chưa có thì nói 'chưa ghi rõ', không bịa."
    )
    if persona_groups:
        blocks = [
            "Khi cuộc hội thoại đã xác định ứng viên đang nói về một trong các slug dưới đây, "
            "áp dụng Agent tương ứng cho phần tư vấn dự án đó. Nếu chưa xác định dự án, dùng Agent mặc định.",
        ]
        for (persona_name, persona_body), slugs in persona_groups.items():
            blocks.append(
                f"\nSlug: {', '.join(slugs)}\nAgent: {persona_name}\n{persona_body}"
            )
        prompt += _PROJECT_PERSONA_HEADER + "\n" + "\n".join(blocks)
    return prompt


async def build_system_prompt(db: AsyncSession) -> str:
    """Persona body + active-product index, with a hard fallback to persona.md."""
    try:
        persona = _strip_stale_refusal_rules(await resolve_persona(db))
        index = await active_projects_index(db)
        return persona + index + "\n\n" + _RUNTIME_RETRIEVAL_RULES
    except Exception:  # noqa: BLE001
        return _strip_stale_refusal_rules(AGENT_SYSTEM_PROMPT) + "\n\n" + _RUNTIME_RETRIEVAL_RULES
