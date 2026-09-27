"""Runtime system-prompt assembly: provider-scoped persona + active project index.

The persona (the bot's voice + follow-up policy) is resolved from the current
conversation provider, falling back to the active global persona and then the
committed ``persona.md``. The active project index is appended so the agent
always knows the catalog + slugs and scopes ``search_knowledge`` to the
relevant project.

All DB lookups are best-effort: any failure collapses to ``AGENT_SYSTEM_PROMPT`` so a
persona/index hiccup can never break a chat turn. SQL lives in
``app.services.retrieval.RetrievalRepository``; this module only assembles the prompt.
"""

from __future__ import annotations

from app.core.preamble_cache import cached_system_prompt
from app.graph.ports import GraphRetrievalPort
from app.graph.prompts import AGENT_SYSTEM_PROMPT

_INDEX_HEADER = "\n\n=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ==="
_RUNTIME_RETRIEVAL_RULES = """

=== QUY TẮC TRA CỨU BẮT BUỘC ===
- Với câu hỏi về liên hệ, admin, số điện thoại, hotline, Zalo, hoặc "đến công ty liên hệ ai": phải tra search_knowledge trước khi kết luận.
- Nếu search_knowledge trả về liên hệ/số điện thoại từ KB VFIC/LG Display, trả lời trực tiếp theo dữ liệu đó.
- Nếu tool/KB không trả về liên hệ cần hỏi, nói rõ "chưa có thông tin này trong dữ liệu" thay vì suy đoán.
- Kết quả Job ACTIVE có cấu trúc là nguồn ưu tiên cho tình trạng tuyển dụng. Nếu graph thông báo danh mục Job có cấu trúc đang trống/chưa cấu hình, phải gọi search_knowledge: chỉ được xác nhận "đang tuyển" khi nội dung KB đang hoạt động, đã xuất bản nói rõ điều đó.
- Không được suy ra tình trạng tuyển dụng từ danh mục dự án, tên dự án hoặc kiến thức chung. Nếu KB không có bằng chứng tuyển dụng rõ ràng, nói "chưa thể xác minh từ dữ liệu hiện có"; không được biến thiếu dữ liệu thành "chưa tuyển".
- Câu hỏi về CHÍNH VFIC (công ty ở tỉnh nào, địa chỉ, trụ sở, "VFIC là gì", "chúng tôi là ai", đơn vị nào hỗ trợ ứng viên): được trả lời trực tiếp từ phần giới thiệu trong persona, KHÔNG cần gọi search_knowledge. Chỉ áp dụng cho thông tin tổng quan về công ty — vẫn phải dùng tool cho tình trạng tuyển dụng, việc làm cụ thể, lương, lịch xe.
- KHÔNG ĐƯỢC BỊA KÊNH LIÊN HỆ: không nêu hotline, tổng đài, số máy lẻ, email, địa chỉ hoặc tên người liên hệ mà kết quả tool (hoặc mục API TINGTING) không trả về. Không có dữ liệu thì nói rõ "chưa có thông tin đã xác minh" và xin SĐT để liên hệ lại — tuyệt đối không tự nghĩ ra số điện thoại, email hay phòng ban nào. Mẫu "chưa có thông tin đã xác minh"/xin SĐT KHÔNG áp dụng cho việc tài khoản TingTing: khi có mục API TINGTING và người dùng quên/đặt lại/quá hạn mật khẩu hoặc không nhận được OTP, phải chạy quy trình call_tingting_api trước, không được trả lời bằng mẫu đó.
- NHÂN VIÊN CẦN HỖ TRỢ TÀI KHOẢN/HỆ THỐNG: khi có mục API TINGTING (quên mật khẩu, không nhận được mã OTP, đặt lại mật khẩu), PHẢI gọi call_tingting_api theo đúng từng bước trong hướng dẫn và hỏi từng bước một; không được trả lời rằng việc này ngoài phạm vi rồi hướng dẫn liên hệ nơi khác. BẮT BUỘC xác minh danh tính trước mọi bước thay đổi tài khoản: tra cứu nhân viên theo số điện thoại, đối chiếu họ tên đầy đủ, CCCD và số điện thoại nhân viên cung cấp với kết quả tra cứu, chỉ khi khớp hoàn toàn mới gửi OTP hoặc đặt lại mật khẩu. Chỉ hỏi các trường còn thiếu (họ tên đầy đủ, CCCD) — không hỏi lại số điện thoại đã có, và không hỏi lại thông tin vừa tra cứu được.
- GỌI TOOL SONG SONG: Khi cần nhiều tool không phụ thuộc nhau (ví dụ recommend_jobs + get_product_features, hoặc search_knowledge + list_active_projects), hãy gọi TẤT CẢ trong cùng một lượt trả lời thay vì gọi từng cái một. Điều này giúp trả lời nhanh hơn rất nhiều. Không gọi trùng cùng một tool với cùng tham số trong một lượt — mỗi tool chỉ gọi một lần cho mỗi bộ tham số.
""".strip()

_PRIVATE_CONTEXT_RULES = """

=== NGỮ CẢNH RIÊNG TƯ ===
- Lịch sử chat, hồ sơ, ghi chú và kết quả `search_user_memory` là ngữ cảnh nội bộ, không phải nội dung để gửi lại cho bạn.
- Không được trích dẫn, liệt kê, tóm tắt hoặc nói rằng bạn đang nhớ/đọc lại các dữ liệu này. Không dùng các cách nói như "ứng viên trước đó", "theo memory", "theo lịch sử", hoặc "bạn từng nói".
- Chỉ dùng ngữ cảnh riêng tư để không hỏi lặp hoặc để tư vấn việc làm khi thông tin đó liên quan trực tiếp đến tin nhắn hiện tại. Với tin nhắn ngắn, lạc đề hoặc không liên quan, chỉ trả lời/chuyển hướng theo chính tin nhắn hiện tại; không nhắc lại chi tiết tìm việc trước đó.
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


async def resolve_persona(
    retrieval: GraphRetrievalPort, *, provider: str | None = None
) -> str:
    """Return the effective provider persona body, or persona.md if none is active."""
    try:
        body = await retrieval.active_persona_body(provider=provider)
        if body and body.strip():
            return _strip_stale_refusal_rules(body.strip())
    except Exception:  # noqa: BLE001
        pass
    return AGENT_SYSTEM_PROMPT


async def active_projects_index(retrieval: GraphRetrievalPort) -> str:
    """Compact catalog of active projects (the agent's master index). '' if none/err."""
    try:
        rows = await retrieval.active_projects_with_card()
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    for r in rows:
        card = r.index_card or {}
        aliases = ", ".join(str(alias) for alias in (getattr(r, "aliases", None) or []) if alias)
        roles = ", ".join(card.get("roles") or card.get("key_roles") or [])
        loc = card.get("location") or ""
        seg = f"- {r.slug} ({r.name})"
        if r.summary:
            seg += f": {r.summary}"
        if aliases:
            seg += f"; bí danh: {aliases}"
        if roles:
            seg += f"; vị trí: {roles}"
        if loc:
            seg += f"; địa điểm: {loc}"
        lines.append(seg)

    prompt = (
        _INDEX_HEADER
        + "\n"
        + "\n".join(lines)
        + "\nKhi ứng viên quan tâm một dự án cụ thể: với câu hỏi về thu nhập/lương, ca làm, tăng ca, "
        "phụ cấp, KTX, xe đưa đón, thưởng, hồ sơ... hãy gọi get_product_features(project_slug) để lấy "
        "các đặc điểm sản phẩm; nếu ứng viên chưa nêu rõ dự án mà hỏi mốc thu nhập/lương chung, hãy gọi "
        "compare_income(target_monthly_vnd) để so sánh dữ liệu thu nhập giữa các dự án đang hoạt động; "
        "với câu hỏi mở/tìm thêm chi tiết, gọi search_knowledge(project_slug). "
        "Riêng câu hỏi về tuyến xe, điểm đón hoặc giờ đón phải dùng search_bus_timetable trước, "
        "không dùng get_product_features thay cho lịch xe chi tiết. "
        "TUYỆT ĐỐI chỉ tư vấn bám sát dữ liệu trả về; dữ liệu chưa có thì nói 'chưa ghi rõ', không bịa."
    )
    return prompt


async def build_system_prompt(
    retrieval: GraphRetrievalPort, *, provider: str | None = None
) -> tuple[str, bool]:
    """Persona body + active-product index, with a hard fallback to persona.md.

    Returns ``(prompt, cache_hit)``. ``cache_hit`` is True when the prompt came
    from Redis (sub-ms); False when assembled fresh (DB reads) or on any error
    fallback. Cached in Redis under the ``preamble`` version namespace —
    persona/project writes bump that namespace so the next turn re-reads.
    """

    async def _assemble() -> str:
        persona = _strip_stale_refusal_rules(await resolve_persona(retrieval, provider=provider))
        index = await active_projects_index(retrieval)
        return (
            persona
            + index
            + "\n\n"
            + _RUNTIME_RETRIEVAL_RULES
            + "\n\n"
            + _PRIVATE_CONTEXT_RULES
        )

    try:
        return await cached_system_prompt(_assemble, key_suffix=provider or "default")
    except Exception:  # noqa: BLE001
        return _strip_stale_refusal_rules(
            AGENT_SYSTEM_PROMPT
        ) + "\n\n" + _RUNTIME_RETRIEVAL_RULES + "\n\n" + _PRIVATE_CONTEXT_RULES, False
