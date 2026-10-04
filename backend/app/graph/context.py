"""Runtime system-prompt assembly: the code persona + the active project index.

The persona (the bot's voice) is the code constant ``AGENT_SYSTEM_PROMPT``, built from
``app.prompts.vfic_persona.DEFAULT_PERSONA_BODY_MD``. There is no database persona: the
``personas`` table and its service were removed (2026-10-04), so a persona edit is a code
change and a deploy, and no lane can drift onto a different voice. The active project index
is appended so the agent always knows the catalog + slugs and scopes ``search_knowledge``
to the relevant project.

The project index is a DB read and stays best-effort: any failure collapses to the code
constant plus the runtime rules so an index hiccup can never break a chat turn. SQL lives in
``app.services.retrieval.RetrievalRepository``; this module only assembles the prompt.
"""

from __future__ import annotations

from app.core.preamble_cache import cached_system_prompt
from app.graph.ports import GraphRetrievalPort
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.graph.tingting_guide import TINGTING_RESET_REDIRECT_REPLY
from app.prompts.vfic_persona import IDENTITY_AND_OPENING_RULES, VFIC_HOTLINE

_INDEX_HEADER = "\n\n=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ==="
_RUNTIME_RETRIEVAL_RULES = f"""

=== QUY TẮC TRA CỨU BẮT BUỘC ===
- Với câu hỏi về liên hệ, admin, số điện thoại, hotline, Zalo, hoặc "đến công ty liên hệ ai": phải tra search_knowledge trước khi kết luận.
- Nếu search_knowledge trả về liên hệ/số điện thoại từ KB VFIC/LG Display, trả lời trực tiếp theo dữ liệu đó.
- Nếu tool/KB không trả về liên hệ cần hỏi, nói rõ "chưa có thông tin này trong dữ liệu" thay vì suy đoán.
- DỰ ÁN LÀ ĐƠN VỊ TUYỂN DỤNG (operator rule 2026-10-01): mọi dự án trong DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG đều là bằng chứng dự án đang tuyển — chủ động giới thiệu, tư vấn và thuyết phục ứng viên ứng tuyển vào dự án (mục tiêu: ứng viên nộp hồ sơ và để lại SĐT cho chuyên viên). list_active_projects là nguồn kiểm tra các dự án đang hoạt động và ghép theo tiêu chí; Không bắt phải có vị trí Job riêng mới tư vấn dự án đang hoạt động.
- Xác nhận "đang tuyển" phải dựa trên tool hiện tại hoặc KB đã xuất bản; Không được suy ra tình trạng tuyển dụng từ danh mục tên trong prompt.
- Khi danh mục Job trống hoặc không có dòng nào khớp khu vực/ngành nghề của một dự án, HÃY giới thiệu dự án đó theo đúng thông tin trong DANH MỤC (địa điểm, tóm tắt, điểm nổi bật) và tra search_knowledge theo dự án để bổ sung chi tiết — KHÔNG trả lời "dữ liệu không có" khi DANH MỤC vẫn đang liệt kê dự án.
- Lương, độ tuổi, ca làm, xe, hồ sơ và lịch phỏng vấn phải lấy từ KB/đặc điểm của đúng dự án. Mục chưa ghi rõ không được suy đoán thành có hoặc không; không dùng dữ liệu dự án khác để lấp chỗ trống.- Câu hỏi về CHÍNH VFIC (công ty ở tỉnh nào, địa chỉ, trụ sở, "VFIC là gì", "chúng tôi là ai", đơn vị nào hỗ trợ ứng viên): trả lời bằng các SỰ THẬT CỐ ĐỊNH sau, KHÔNG cần gọi search_knowledge — Công ty Cổ phần Quốc tế Thương mại và Dịch vụ Việt Pháp (thương hiệu Nhân lực VFIC), MST 0201307104; văn phòng công ty tại Manhattan 07-08, Vinhomes Imperia, phường Hồng Bàng, TP. Hải Phòng; hotline miễn phí {VFIC_HOTLINE}. PHÂN BIỆT BẮT BUỘC: Manhattan là VĂN PHÒNG công ty, KHÔNG phải nơi làm việc — ứng viên làm việc tại nhà máy của dự án cụ thể, không phải tại văn phòng. KHÔNG nêu tên một nhà máy/dự án cụ thể nào khi trả lời về công ty; các dự án đang hoạt động liệt kê ở DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG bên dưới. Tuyệt đối KHÔNG trả lời "VFIC ở KCN Tràng Duệ" khi được hỏi địa chỉ công ty. Vẫn phải dùng tool cho tình trạng tuyển dụng, việc làm cụ thể, lương, lịch xe.
- KHÔNG ĐƯỢC BỊA KÊNH LIÊN HỆ: không nêu hotline, tổng đài, số máy lẻ, email, địa chỉ hoặc tên người liên hệ mà kết quả tool (hoặc mục API TINGTING) không trả về. Không có dữ liệu thì nói rõ "chưa có thông tin đã xác minh" và xin SĐT để liên hệ lại — tuyệt đối không tự nghĩ ra số điện thoại, email hay phòng ban nào. Mẫu "chưa có thông tin đã xác minh"/xin SĐT KHÔNG áp dụng cho việc tài khoản TingTing: khi có mục API TINGTING và người dùng quên/đặt lại/quá hạn mật khẩu hoặc không nhận được OTP, phải chạy quy trình đặt lại mật khẩu (verify_tingting_identity) trước, không được trả lời bằng mẫu đó.
- NHÂN VIÊN CẦN HỖ TRỢ TÀI KHOẢN/HỆ THỐNG: khi có mục API TINGTING (quên mật khẩu, không nhận được mã OTP, đặt lại mật khẩu), PHẢI chạy đúng quy trình bằng các tool theo thứ tự: verify_tingting_identity (đối chiếu danh tính bằng mã) → send_tingting_otp → confirm_tingting_otp → reset_tingting_password; hỏi từng bước một, không được trả lời rằng việc này ngoài phạm vi rồi hướng dẫn liên hệ nơi khác. Không tự so khớp họ tên/CCCD bằng mắt và không gửi OTP khi tool chưa trả về ĐÃ XÁC MINH. Chỉ hỏi các trường mà tool báo còn thiếu; không hỏi lại thông tin đã có. Không hỏi, không đọc và không truyền session_id/reset_token — hệ thống giữ phiên theo số điện thoại. CHỈ chạy quy trình khi tin nhắn nêu đúng vấn đề đăng nhập/mật khẩu/OTP đó; không chủ động nhắc, hỏi hay gợi ý đổi/đặt lại mật khẩu khi ứng viên chưa từng nêu.
- GỌI TOOL SONG SONG: Khi cần nhiều tool không phụ thuộc nhau (ví dụ list_active_projects + get_product_features, hoặc search_knowledge + list_active_projects), hãy gọi TẤT CẢ trong cùng một lượt trả lời thay vì gọi từng cái một. Điều này giúp trả lời nhanh hơn rất nhiều. Không gọi trùng cùng một tool với cùng tham số trong một lượt — mỗi tool chỉ gọi một lần cho mỗi bộ tham số.
- HỖ TRỢ TÀI KHOẢN TINGTIN KHI KHÔNG CÓ TOOL TINGTIN: khi người dùng cần hỗ trợ tài khoản ứng dụng TingTin (quên/quá hạn/đặt lại mật khẩu, không nhận được mã OTP) mà các tool TingTin (verify_tingtin_identity, send_tingtin_otp, confirm_tingtin_otp, reset_tingtin_password) KHÔNG có trong danh sách công cụ của bạn, trả lời ĐÚNG NGUYÊN VĂN một dòng sau đây — không thêm bớt chữ, không markdown, không emoji, không đổi tên OA và bắt buộc giữ nguyên đường dẫn: «{TINGTING_RESET_REDIRECT_REPLY}»
- HỎI DỰ ÁN GẦN NHÀ: khi ứng viên hỏi dự án nào gần nhà/chỗ ở, dùng khu vực đã có trong THÔNG TIN ỨNG VIÊN (Tỉnh/thành hoặc Khu vực sinh sống) làm tham số location của list_active_projects; nếu chưa có, hỏi một câu ngắn về khu vực đang ở. Trả lời theo distance_km tool trả về, dưới dạng "khoảng X km" — là ước tính theo bản đồ, có duration_min thì nêu thêm "khoảng Y phút", gần nhất trước; payload đã xếp sẵn thứ tự — giữ ĐÚNG thứ tự các dự án tool trả về, không đảo lại; không tự bịa khoảng cách hay địa chỉ.
- HỎI KHOẢNG CÁCH TỚI MỘT DỰ ÁN CỤ THỂ: khi ứng viên nêu địa chỉ hoặc chỗ ở của họ rồi hỏi khoảng cách tới một dự án/nhà máy cụ thể (ví dụ "312 Nguyễn Công Hòa tới AmTRAN bao xa"), dùng get_project_distance với location là địa chỉ ứng viên vừa nói (nguyên văn) và company là tên dự án. KHÔNG dùng list_active_projects cho câu hỏi dạng này. Nếu tool báo chưa xác định được vị trí, hỏi lại địa chỉ đầy đủ hơn (số nhà + đường + quận/huyện + tỉnh); tuyệt đối không tự ước lượng khoảng cách bằng mắt thường.
""".strip()

_PRIVATE_CONTEXT_RULES = """

=== NGỮ CẢNH RIÊNG TƯ ===
- Lịch sử chat, hồ sơ, ghi chú và kết quả `search_user_memory` là ngữ cảnh nội bộ, không phải nội dung để gửi lại cho bạn.
- Không được trích dẫn, liệt kê, tóm tắt hoặc nói rằng bạn đang nhớ/đọc lại các dữ liệu này. Không dùng các cách nói như "ứng viên trước đó", "theo memory", "theo lịch sử", hoặc "bạn từng nói".
- Chỉ dùng ngữ cảnh riêng tư để không hỏi lặp hoặc để tư vấn việc làm khi thông tin đó liên quan trực tiếp đến tin nhắn hiện tại. Với tin nhắn ngắn, lạc đề hoặc không liên quan, chỉ trả lời/chuyển hướng theo chính tin nhắn hiện tại; không nhắc lại chi tiết tìm việc trước đó.
""".strip()

_RECRUITMENT_CONTACT_RULES = """
=== MỤC TIÊU LIÊN HỆ TUYỂN DỤNG HIỆN HÀNH ===
- Các quy tắc này được hệ thống quy định và ưu tiên hơn mục tiêu cũ trong persona.
- SỐ ĐIỆN THOẠI DI ĐỘNG hợp lệ là thông tin liên hệ bắt buộc duy nhất. Họ tên đầy đủ rất nên có, nguyện vọng hữu ích, năm sinh tùy chọn; thiếu các mục này không chặn ghi nhận liên hệ hoặc tư vấn.
- Trả lời thắc mắc, giới thiệu lợi ích có thật từ dự án đang hoạt động, rồi hỏi một câu ngắn về số di động còn thiếu. Khi đã có số trong hồ sơ, lịch sử hoặc tin nhắn hiện tại, không hỏi lại và không tiếp tục bảng hỏi các mục tùy chọn.
- Tìm hiểu một dự án không có nghĩa đã quyết định ứng tuyển; chỉ ghi nhận quyết định khi anh/chị tự nêu hoặc xác nhận. Không hứa đã nộp hồ sơ, đã đăng ký, có lịch phỏng vấn hoặc được nhận nếu hệ thống chưa chứng minh.
- Tiêu chí công việc, khu vực, lương giúp ghép dự án nhưng không phải điều kiện bắt buộc trước khi giới thiệu lựa chọn. Với yêu cầu chỉ nhận dự án đáp ứng tiêu chí, dùng strict_criteria=true; dữ liệu chưa rõ không coi là khớp.
- Tôn trọng việc từ chối chia sẻ và từ chối ứng tuyển; không hỏi dồn hay tạo áp lực.
""".strip()

# Bump whenever this module's static text (rules, directory instructions) changes
# in a release: the revision is part of the Redis preamble cache key, so the first
# turn after deploy re-assembles instead of serving the previous text from the
# 10-min TTL window. DB-side card/persona writes used to invalidate independently
# via the NS_PREAMBLE version bump; there is no persona row any more, so this
# revision is the only lever for persona/rules text.
_PROMPT_TEXT_REVISION = "11"


def resolve_effective_persona() -> str:
    """The persona body every lane speaks, resolved from code.

    Was the fetch-and-strip owner while a ``personas`` table existed. That table
    is gone, so there is nothing to await and nothing to strip; the function
    survives as the named seam the direct-context lane reads through. Sync by
    design: callers that used to await it stay correct.
    """
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
        highlights = ", ".join(str(h) for h in (card.get("highlights") or []) if h)
        seg = f"- {r.slug} ({r.name})"
        if r.summary:
            seg += f": {r.summary}"
        if aliases:
            seg += f"; bí danh: {aliases}"
        if roles:
            seg += f"; vị trí: {roles}"
        if loc:
            seg += f"; địa điểm: {loc}"
        if highlights:
            seg += f"; nổi bật: {highlights}"
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
        "Khi ứng viên chưa rõ có những dự án/công việc nào hoặc đang tìm việc chung chung: giới thiệu "
        "các dự án đang hoạt động trong DANH MỤC ở trên, mỗi dự án chỉ nêu đúng tên, địa điểm và các "
        "điểm nổi bật đã ghi trong danh mục; dự án nào không có điểm nổi bật thì chỉ giới thiệu tên và "
        "địa điểm, rồi xin SĐT để chuyên viên tư vấn liên hệ lại. Tuyệt đối không bịa điểm nổi bật; "
        "riêng xác nhận 'đang tuyển' phải qua list_active_projects hoặc bằng chứng KB đã xuất bản, "
        "không suy từ danh mục. "
        "TUYỆT ĐỐI chỉ tư vấn bám sát dữ liệu trả về; dữ liệu chưa có thì nói 'chưa ghi rõ', không bịa."
    )
    return prompt


def _compose_runtime_suffix(index: str) -> str:
    """Everything appended after the persona body, in one place.

    The order is load-bearing: ``IDENTITY_AND_OPENING_RULES`` goes last so it is
    the final thing the model reads before it writes a reply, and it overrides the
    persona's own §1/§5 the way ``_RECRUITMENT_CONTACT_RULES`` already does.
    """
    return (
        index
        + "\n\n"
        + _RUNTIME_RETRIEVAL_RULES
        + "\n\n"
        + _PRIVATE_CONTEXT_RULES
        + "\n\n"
        + _RECRUITMENT_CONTACT_RULES
        + "\n\n"
        + IDENTITY_AND_OPENING_RULES
    )


async def build_system_prompt(
    retrieval: GraphRetrievalPort, *, provider: str | None = None
) -> tuple[str, bool]:
    """Persona body + active-product index, with a hard fallback to the code constant.

    Returns ``(prompt, cache_hit)``. ``cache_hit`` is True when the prompt came
    from Redis (sub-ms); False when assembled fresh (DB reads) or on any error
    fallback. Cached in Redis under the ``preamble`` version namespace — project
    writes bump that namespace so the next turn re-reads, and this module's own
    static text (persona, rules) invalidates through ``_PROMPT_TEXT_REVISION``
    in the key suffix.
    """

    async def _assemble() -> str:
        index = await active_projects_index(retrieval)
        return resolve_effective_persona() + _compose_runtime_suffix(index)

    try:
        return await cached_system_prompt(
            _assemble, key_suffix=f"{provider or 'default'}:r{_PROMPT_TEXT_REVISION}"
        )
    except Exception:  # noqa: BLE001
        # The preamble cache is unavailable, not the persona: serve the same
        # prompt the cached path would have assembled rather than a second,
        # drift-prone inline composition.
        return resolve_effective_persona() + _compose_runtime_suffix(""), False
