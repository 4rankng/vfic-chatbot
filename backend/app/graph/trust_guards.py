"""Trust guards from the 2026-10-21 Zalo post-mortem (user Toàn, 19:06–19:29).

Four behaviors the post-mortem demanded, all deterministic so no prompt
discretion is load-bearing:

- **Escalation** — an injury/disability disclosure («gãy tay», «khuyết tật»,
  «tai nạn», …) is answered ONCE with a fixed handoff that asks the candidate
  to call the hotline directly, and never with another advisory question. The
  bot kept consulting on jobs after the user wrote he had broken limbs — that
  turn is what lost the follow.
- **Post-phone STOP** — the turn a candidate hands over a phone number
  confirms receipt and ends the interrogation; no new screening questions, no
  new pitches.
- **Physical-constraint pre-filter trigger** — «việc ngồi», «không mang vắc»,
  «tay chân khó vận động» force the project-catalog tool with hard filter
  args server-injected, so standing-only/unparsed projects can never be
  pitched (the filter itself lives in
  :func:`app.recruitment.domain.recommendation.rank_projects`).
- **Repetition detection** — a reply whose text block is ≥80% a repeat of the
  bot's previous reply triggers one regeneration under a no-repeat
  instruction.
- **Identity honesty** — «bot à / người thật à / AI à» gets a deterministic
  honesty instruction reinforcing the persona rule: never claim to be human.

Framework-free like every graph policy module: only shared/domain text
helpers and core settings — no service/model imports (import guard).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.shared.domain.text import has_phone, normalize_vietnamese_text

# ── C.1 Escalation ──────────────────────────────────────────────────────────
# Matched on diacritic-folded text, so every pattern inherently covers its
# no-diacritic variant («gãy tay» and «gay tay» normalize identically). The
# eight core triggers from the post-mortem plus safe high-precision variants.
# «liệt» alone would match «liệt kê» (list), so it is anchored to limb words.
_ESCALATION_RE = re.compile(
    r"\bgay tay\b|\bgay chan\b|\bgay ca hai (?:tay|chan)\b|"
    r"\bkhuyet tat\b|\btai nan\b|\bphau thuat\b|\bthuong tat\b|"
    r"\bbat luc\b|\bliet tay\b|\bliet chan\b|\bliet nua nguoi\b|"
    r"\bkhong di lai duoc\b|\bxe lan\b|\bdot co\b"
)


def is_escalation_message(text: str) -> bool:
    """Whether the message discloses an injury/disability needing a human."""
    return _ESCALATION_RE.search(normalize_vietnamese_text(text or "")) is not None


def escalation_reply() -> str:
    """The one fixed handoff for injury/disability disclosures (owner rule).

    Owner-approved verbatim template — :func:`vfic_hotline_reply`, the same
    sentence the persona (§7) and the existing not-job-seeker/off-scope gates
    quote, built around the single ``VFIC_HOTLINE`` code constant (1800 7228,
    tổng đài miễn cước). Exactly one reply, zero follow-up questions: the
    interrogate ends here by construction. No parallel hotline constant and
    no new config — the recruitment channel's one handoff mechanism already
    existed.
    """
    from app.prompts.vfic_persona import vfic_hotline_reply

    return vfic_hotline_reply()


# ── C.2 Post-lead-capture STOP ──────────────────────────────────────────────
POST_PHONE_STOP_INSTRUCTION = (
    "DỪNG KHAI THÁC THÔNG TIN SAU KHI CÓ SỐ ĐIỆN THOẠI: tin nhắn này của ứng viên "
    "chứa SỐ ĐIỆN THOẠI. Trả lời NGẮN (2-4 câu): xác nhận đã nhận số, nói chuyên "
    "viên tuyển dụng sẽ liên hệ với anh/chị. TUYỆT ĐỐI KHÔNG hỏi thêm câu hỏi "
    "tuyển chọn mới (khu vực, lương mong muốn, độ tuổi, kinh nghiệm, chọn dự án), "
    "KHÔNG pitch dự án mới, KHÔNG kết thúc bằng một câu hỏi. Đây là tin kết thúc "
    "buổi tư vấn, không phải bước giữa của bảng hỏi."
)


def is_phone_handover(text: str) -> bool:
    """Whether the message's own text hands over a phone number.

    ``has_phone`` scans the digits themselves, so asking ABOUT a number
    («cho em xin hotline») — which carries no digits — never fires. The STOP
    rule targets exactly the turn the candidate gives their own number.
    """
    return has_phone(text or "")


# ── A.3 Physical-constraint pre-filter trigger ──────────────────────────────
# Seated work / no lifting / limited mobility: each maps to hard tool filters
# the lane injects server-side (model cannot drop or spoof them).
_SEATED_CONSTRAINT_RE = re.compile(
    r"\bngoi lam\b|\bviec ngoi\b|\bngoi lam viec\b|\blam viec ngoi\b|"
    r"\bkhong dung (?:lau|duoc|may )|\bdung kho khan\b|"
    r"\btay chan kho van dong\b|\bkho van dong\b|\bvan dong kho khan\b|"
    r"\bkhong nhac (?:nang|do )\b|\bkhong nhac nang duoc\b|"
    r"\bkhong (?:the )?mang vac\b|\bkhong phai mang vac\b|\bkhong boc vac\b|"
    r"\bkhong vac (?:nang )?duoc\b"
)


def has_physical_constraint(text: str) -> bool:
    """Whether the message states a seated/no-lifting/mobility constraint."""
    return _SEATED_CONSTRAINT_RE.search(normalize_vietnamese_text(text or "")) is not None


def physical_constraint_tool_args(text: str) -> dict[str, object]:
    """The hard-filter tool args the stated constraint maps to.

    Seated and mobility constraints both imply ``work_posture="seated"`` (a
    candidate who cannot stand or move freely needs seated work); explicit
    no-lifting statements add ``no_heavy_lifting``. Empty dict = no
    constraint stated, nothing injected.
    """
    normalized = normalize_vietnamese_text(text or "")
    args: dict[str, object] = {}
    if _SEATED_CONSTRAINT_RE.search(normalized):
        args["work_posture"] = "seated"
        if re.search(
            r"mang vac|nhac nang|nhac do |boc vac|vac nang", normalized
        ):
            args["no_heavy_lifting"] = True
    return args


SEATED_CONSTRAINT_HINT = (
    "Ý định: ứng viên nêu RÀNG BUỘC THỂ CHẤT (ngồi làm / không đứng lâu / không "
    "mang vác / tay chân khó vận động). Tool list_active_projects ở lượt này ĐÃ "
    "được hệ thống truyền sẵn bộ lọc cứng (work_posture=seated và/hoặc "
    "no_heavy_lifting): mọi dự án đứng máy hoặc chưa rõ tư thế ĐÃ BỊ LOẠI khỏi "
    "kết quả. Chỉ tư vấn các dự án trong payload tool trả về; tuyệt đối KHÔNG "
    "tự thêm dự án ngoài payload, KHÔNG mô tả công việc đứng máy là \"ngồi "
    "được\"; nếu danh sách rỗng, nói thật hiện chưa có dự án ngồi khớp và mời "
    "gọi hotline — không bịa dự án, không lách ràng buộc."
)

# ── B.2 Repetition guard ────────────────────────────────────────────────────
# A reply block ≥80% identical to the previous bot reply is a repeat the
# candidate already read (the post-mortem transcript re-pasted the same job
# blurb three turns straight). Detected on normalized text so emoji/formatting
# cannot hide it.
_REPEAT_BLOCK_SIMILARITY = 0.8
_REPEAT_MIN_CHARS = 60

REPETITION_RETRY_INSTRUCTION = (
    "BẢN NHÁP BỊ LOẠI VÌ LẶP NỘI DUNG: bản vừa soạn lặp lại phần lớn nội dung "
    "tin nhắn trước của bạn (mô tả dự án/lương/chính sách anh/chị đã đọc rồi). "
    "Soạn lại CHỈ dựa trên thông tin MỚI trong tin nhắn hiện tại của ứng viên: "
    "2-4 câu, trả lời trực tiếp câu hỏi (nếu có), KHÔNG lặp lại mô tả dự án, "
    "mức lương hay chính sách đã nêu ở tin trước trừ khi anh/chị hỏi lại, "
    "KHÔNG dán lại danh sách dự án."
)


def _last_bot_body(recent_messages: list) -> str:
    """The most recent BOT message body before this turn, "" when none."""
    from app.graph.message_values import sender_is

    for message in reversed(recent_messages or []):
        body = str(getattr(message, "body", "") or "").strip()
        if body and sender_is(message, "BOT"):
            return body
    return ""


def reply_repeats_prior_block(reply: str, prior_bot_reply: str) -> bool:
    """Whether ``reply`` re-sends a block of ``prior_bot_reply`` nearly verbatim.

    Fires when the whole normalized reply is ≥80% shared with the prior reply,
    OR one contiguous shared block alone is long enough to be a re-pasted job
    blurb. Fresh replies that merely share a project name never reach either
    threshold.
    """
    new = normalize_vietnamese_text(reply or "")
    prior = normalize_vietnamese_text(prior_bot_reply or "")
    if not new or not prior:
        return False
    matcher = SequenceMatcher(None, new, prior, autojunk=False)
    blocks = matcher.get_matching_blocks()
    shared = sum(block.size for block in blocks)
    if shared / len(new) >= _REPEAT_BLOCK_SIMILARITY:
        return True
    return any(block.size >= max(_REPEAT_MIN_CHARS, 1) for block in blocks)


# ── D. Identity honesty ─────────────────────────────────────────────────────
# Matched on normalize_vietnamese_text (lowercase, diacritic-folded), so the
# patterns are written diacritic-free. Covers «AI à», «bot à», «người thật
# à/không», «mày là bot», «trợ lý tự động à» shapes.
_IDENTITY_QUESTION_RE = re.compile(
    r"\bai a\b|\bbot a\b|\bbot khong\b|\bbot that\b|"
    r"\bnguoi that a\b|\bnguoi that khong\b|\bla bot\b|\bphai bot\b|"
    r"\btro ly tu dong\b|\brobot\b|\bmay a\b|\bchatbot\b"
)


def is_identity_question(text: str) -> bool:
    """Whether the candidate asks if they are talking to a bot/AI/human."""
    return _IDENTITY_QUESTION_RE.search(normalize_vietnamese_text(text or "")) is not None


IDENTITY_HONESTY_INSTRUCTION = (
    "CÂU HỎI DANH TÍNH: ứng viên hỏi bạn có phải bot/AI/người thật không. "
    "Trả lời TRUNG THỰC: em là trợ lý TỰ ĐỘNG hỗ trợ thông tin việc làm của "
    "Nhân lực VFIC, khi cần anh/chị nhân sự thật sẽ gọi lại hỗ trợ trực tiếp. "
    "TUYỆT ĐỐI KHÔNG khẳng định hay ngầm khẳng định mình là người; không cần "
    "xin lỗi dài dòng, trả lời ngắn 1-2 câu rồi hỗ trợ tiếp việc anh/chị đang "
    "cần theo câu hỏi chính trong tin nhắn."
)


def identity_honesty_instruction(text: str) -> str | None:
    """The honesty instruction when this message is an identity question."""
    return IDENTITY_HONESTY_INSTRUCTION if is_identity_question(text) else None
