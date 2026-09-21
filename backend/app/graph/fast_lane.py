"""Deterministic pleasantries templates for the bot brain.

Template selection comes from the Jev decision fan-out
(``pleasantry_kind``) via :func:`template_for` — there is no lexical
matching left in this module. Scope is unchanged and deliberately narrow:
only NON-factual traffic gets a template. Genuinely factual questions
(salary, shuttle, contacts, requirements) must never be templated — they
are grounded by retrieval + synthesis, and a wrong contact or pay info is
far worse than a slightly slower correct answer.

The persona-voice guard test pins tôi/bạn voice on every template.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FastLaneHit:
    reply: str
    intent: str


# --- templates (em / anh-chị voice — persona.md) ------------------------------
# These fire before any lead lookup, so the candidate's gender is never known
# here. They therefore always use the neutral "anh/chị" — never "anh" or "chị"
# alone, which would be a coin-flip guess on a first greeting.
GREETING_REPLY = (
    "Em chào anh/chị! Em là trợ lý tuyển dụng của VFIC. "
    "Anh/chị đang muốn tìm hiểu việc làm, mức lương, xe đưa đón hay hồ sơ ứng tuyển ạ?"
)
THANKS_REPLY = (
    "Em rất vui được hỗ trợ anh/chị ạ! Nếu anh/chị cần thêm thông tin việc làm, "
    "cứ nhắn cho em nhé."
)
GOODBYE_REPLY = (
    "Hẹn gặp lại anh/chị nhé ạ! Khi cần hỗ trợ việc làm VFIC, anh/chị nhắn em "
    "bất cứ lúc nào."
)
HELP_REPLY = (
    "Em có thể hỗ trợ anh/chị tìm hiểu về tuyển dụng VFIC: việc làm đang tuyển, "
    "mức lương và phụ cấp, xe đưa đón, địa điểm làm việc, hồ sơ ứng tuyển, "
    "ca làm việc, lịch phỏng vấn và thông tin liên hệ. Anh/chị muốn biết thêm về điều gì ạ?"
)

# kind (from Jev pleasantry_kind) -> template reply.
_PLEASANTRY_TEMPLATES = {
    "greeting": GREETING_REPLY,
    "thanks": THANKS_REPLY,
    "goodbye": GOODBYE_REPLY,
    "help": HELP_REPLY,
}


def template_for(kind: str) -> FastLaneHit | None:
    """Template reply for a Jev pleasantry kind, else ``None`` (fall through)."""
    reply = _PLEASANTRY_TEMPLATES.get((kind or "").strip())
    if reply is None:
        return None
    return FastLaneHit(reply, kind)
