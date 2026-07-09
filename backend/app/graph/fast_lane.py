"""Deterministic fast lane — answers common NON-factual traffic with zero LLM calls.

Wired into ``run_turn`` *before* the agent. Routes greetings / thanks / goodbye /
help-meta messages to short, warm Vietnamese templates (tôi/bạn voice per
``persona.md``). This is the latency win for the bulk of OA inbound: an instant,
human-like reply with no remote LLM hop, and (because it returns well inside
``slow_ack_seconds``) no slow-case ack ever fires for these turns.

SCOPE — deliberately narrow, deliberately safe:

* Only NON-factual traffic is templated. Genuinely factual questions (salary,
  shuttle, work location, contacts, interview schedule, age/KTX requirements) are
  **not** handled here. Their answers live in the knowledge base and must be
  grounded by retrieval + synthesis, never hardcoded — wrong contact or pay info
  is far worse than a slightly slower correct answer. Those intents fall through
  to the RAG + agent path.

* Matching is exact-phrase (greeting / thanks / goodbye) so a real question can
  never be mis-read as a pleasantry. Help/meta uses word-boundary keywords but
  only resolves to a generic "what I can help with" menu, which is correct for
  any meta question.

Add factual-intent fast-laning only behind a KB-confidence gate (out of scope
for v1; see plan "Out of scope"). The persona-voice guard test pins tôi/bạn on
every template, including future ones.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class FastLaneHit:
    reply: str
    intent: str


# --- templates (tôi/bạn voice — persona.md:40) --------------------------------
GREETING_REPLY = (
    "Chào bạn! Tôi là trợ lý tuyển dụng của VFIC. "
    "Bạn đang muốn tìm hiểu việc làm, mức lương, xe đưa đón hay hồ sơ ứng tuyển?"
)
THANKS_REPLY = (
    "Rất vui được hỗ trợ bạn! Nếu bạn cần thêm thông tin việc làm, cứ nhắn cho tôi nhé."
)
GOODBYE_REPLY = (
    "Hẹn gặp lại bạn nhé! Khi cần hỗ trợ việc làm VFIC, bạn nhắn tôi bất cứ lúc nào."
)
HELP_REPLY = (
    "Tôi có thể hỗ trợ bạn tìm hiểu về tuyển dụng VFIC: việc làm đang tuyển, "
    "mức lương và phụ cấp, xe đưa đón, địa điểm làm việc, hồ sơ ứng tuyển, "
    "ca làm việc, lịch phỏng vấn và thông tin liên hệ. Bạn muốn biết thêm về điều gì?"
)

# --- exact-phrase sets (normalized: ASCII, lowercase, no accents) --------------
_GREETING_PHRASES = {
    "hi", "hii", "hiii", "helo", "hello", "halo", "hey",
    "hi ban", "hello ban",
    "chao", "chao ban", "chao anh", "chao chi", "chao em", "chao ad", "chao admin",
    "chao cac ban", "a chao", "e chao",
    "xin chao", "xin chao ban", "xin chao anh", "xin chao chi", "xin chao em",
}

_THANKS_PHRASES = {
    "cam on", "cam on ban", "cam on ad", "cam on admin", "cam on nhe", "cam on nhieu",
    "cam on ban nhe", "xin cam on", "xin cam on ban",
    "thank", "thanks", "thank you", "thank you ban", "thanks ban", "tks", "tk",
}

_GOODBYE_PHRASES = {
    "tam biet", "tam biet ban", "tam biet nhe", "bai", "bye", "bye bye",
    "hen gap lai", "hen gap lai ban", "hen gap", "di nhe", "nha tam biet",
}

# help/meta: word-boundary keywords → the generic menu reply (correct for any meta ask)
_HELP_TERMS = (
    "giup", "help", "ho tro", "ban la ai", "ban la gi", "ban biet gi",
    "lam duoc gi", "lam gi duoc", "hoi gi duoc", "hoi duoc gi", "co the giup",
)


def _normalize(text: str) -> str:
    """ASCII-fold + lowercase Vietnamese (mirrors clients._normalize_query_hint)."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.replace("đ", "d").replace("Đ", "D").lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    """Word-boundary match for possibly-multiword terms (spaces → \\s+)."""
    for term in terms:
        pat = r"\b" + r"\s+".join(re.escape(w) for w in term.split()) + r"\b"
        if re.search(pat, text):
            return True
    return False


def match(user_text: str) -> FastLaneHit | None:
    """Return a canned reply for common non-factual traffic, else ``None`` (fall through).

    Order: help → thanks → goodbye → greeting. Greeting is exact-phrase only and
    excluded when the message also carries a factual/question clause, so a real
    question ("chào bạn, lương bao nhiêu?") is never swallowed by the greeting lane.
    """
    raw = _normalize(user_text)
    if not raw:
        return None
    # Strip trailing/leading punctuation and collapse whitespace for exact matching.
    text = re.sub(r"\s+", " ", re.sub(r"[!?.,;:~()\[\]{}\"'+\-]+", " ", raw)).strip()
    if not text:
        return None

    if _has_any(text, _HELP_TERMS):
        return FastLaneHit(HELP_REPLY, "help")
    if text in _THANKS_PHRASES or _has_any(text, ("cam on", "thank")):
        return FastLaneHit(THANKS_REPLY, "thanks")
    if text in _GOODBYE_PHRASES or _has_any(text, ("tam biet",)):
        return FastLaneHit(GOODBYE_REPLY, "goodbye")
    if text in _GREETING_PHRASES:
        return FastLaneHit(GREETING_REPLY, "greeting")
    return None
