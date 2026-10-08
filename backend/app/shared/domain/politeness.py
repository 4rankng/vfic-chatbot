"""Known pleasantry forms for the politeness-ack gate.

The ack lane (``app.graph.lanes``) answers a message that is ONLY a greeting/
thanks/acknowledgment with a smile and runs no model. Jev's probabilistic
pleasantry judgment gates it, but a short content answer ("Đồng triều ạ" — a
district, replying to the bot's "which town do you live in?") can score above
the gate and ship a bare smile to a candidate waiting for a real answer. This
closed lexicon is the deterministic backstop: only a recognized pleasantry
form may be acked; anything else falls through to the agent, which is always
the safe direction (a real pleasantry the lexicon misses simply gets a
polite agent reply, as it did before the ack lane existed).
"""

from __future__ import annotations

import re

from app.shared.domain.text import normalize_vietnamese_text

# Tokens that carry the pleasantry meaning themselves.
_PLEASANTRY_TOKENS = frozenset(
    {
        # thanks
        "cam",
        "on",
        "camon",
        "thank",
        "thanks",
        "tks",
        "tkss",
        # greeting
        "hi",
        "hey",
        "hello",
        "halo",
        "chao",
        "xin",
        "alo",
        # bye
        "tam",
        "biet",
        "bye",
        # acknowledgment / agreement
        "ok",
        "oke",
        "oki",
        "okie",
        "okay",
        "da",
        "vang",
        "uh",
        "uhm",
        "um",
        "roi",
        "biet",
        "hieu",
        "dc",
        "duoc",
        # presence ("Dạ đây ạ")
        "day",
    }
)

# Polite particles and address words that may ride along but never carry
# meaning on their own ("cảm ơn anh nhiu", "Dạ đây ạ", "chào ad").
_PARTICLE_TOKENS = frozenset(
    {
        "a",
        "ah",
        "nha",
        "nhe",
        "nhiu",
        "nhieu",
        "anh",
        "chi",
        "em",
        "ban",
        "ad",
        "admin",
        "mod",
    }
)

_EMOJI_CHARS = frozenset("👍👌😊🙂😄😀😅🎉❤🙌👏💪😉🤗✨")
_EMOJI_COMPANION_CHARS = frozenset("️‍ \t")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def is_known_pleasantry(value: str | None) -> bool:
    """Whether the message is a recognized greeting/thanks/ack form only.

    Judged on the accent-insensitive normalized text: every token must be a
    known pleasantry or a polite particle, with at least one pleasantry token;
    or the message must be emoji-only. An empty or unmatched message is False —
    the caller then runs the agent, which is the safe direction.
    """
    text = (value or "").strip()
    if not text:
        return False
    if all(
        character in _EMOJI_CHARS or character in _EMOJI_COMPANION_CHARS for character in text
    ):
        return True
    tokens = _TOKEN_PATTERN.findall(normalize_vietnamese_text(text))
    if not tokens:
        return False
    pleasantry = False
    for token in tokens:
        if token in _PLEASANTRY_TOKENS:
            pleasantry = True
        elif token not in _PARTICLE_TOKENS:
            return False
    return pleasantry
