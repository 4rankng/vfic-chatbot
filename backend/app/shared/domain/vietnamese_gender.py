"""Vietnamese given-name gender inference — deterministic, conservative.

The bot addresses people "anh"/"chị"; a wrong guess reads worse than the
neutral "anh/chị", so this module only answers when the name carries an
unambiguous marker:

- a middle token ``Văn`` → male, ``Thị`` → female (the classic CCCD middle
  names, recognised with or without their tone marks);
- otherwise the given (last) token is matched against small, curated sets of
  tone-marked common given names. The comparison keeps tone marks because they
  carry the answer: bare ``Dung`` is the female name, ``Dũng`` the male one —
  strip the tones and the two collide into one useless token.

Anything else — unlisted names, foreign names (``Frank Ng``), tone-stripped
ambiguous spellings — returns ``""`` and the caller stays neutral.

Only ever fed the name the person typed about THEMSELVES (the tool contract in
:mod:`app.graph.tools.tingting_identity`); a record lookup result is the
verification answer key and must never reach this classifier, or the verdict
would disclose the record's gender to whoever is being verified.
"""

from __future__ import annotations

import re
import unicodedata

_MALE = frozenset(
    {
        "bách", "binh", "bình", "chiến", "công", "cường", "cương", "đại", "đạt",
        "đông", "đức", "dũng", "dương", "duy", "hải", "hiếu", "hòa", "hoàng",
        "hùng", "hưng", "hữu", "khoa", "khang", "khôi", "long", "luân", "lực",
        "mạnh", "nam", "nghĩa", "phát", "phong", "phúc", "phước", "quang",
        "quân", "quốc", "quyết", "sang", "sơn", "sỹ", "thắng", "thành",
        "thiện", "thông", "tiến", "toàn", "trung", "trường", "tú", "tùng",
        "tường", "tuấn", "việt", "vinh", "vũ", "vượng",
    }
)
_FEMALE = frozenset(
    {
        "bích", "cầm", "chi", "dung", "hà", "hằng", "hạnh", "hiền", "hoa",
        "huệ", "hương", "lan", "liên", "mai", "my", "mỹ", "nga", "ngân",
        "nguyệt", "nhung", "nhi", "oanh", "quyên", "quỳnh", "sương", "thảo",
        "thu", "thuần", "thủy", "thúy", "trang", "trinh", "tuyền", "tuyết",
        "uyên", "vân", "yến",
    }
)
# Middle-name markers: recognised regardless of tone marks, so the tone-stripped
# spellings people type without a Vietnamese keyboard still classify.
_MALE_MARKERS = frozenset({"văn", "van"})
_FEMALE_MARKERS = frozenset({"thị", "thi"})

_NON_WORD_RE = re.compile(r"[^a-zà-ỹđ\s]")


def _tokens(full_name: str) -> list[str]:
    """Lowercase NFC word tokens of the name, punctuation dropped."""
    text = unicodedata.normalize("NFC", str(full_name or "")).casefold()
    text = _NON_WORD_RE.sub(" ", text)
    return text.split()


def infer_gender_from_name(full_name: str) -> str:
    """Return ``"male"``/``"female"`` for an unambiguous Vietnamese name, else ``""``."""
    tokens = _tokens(full_name)
    if not tokens:
        return ""
    middle = tokens[:-1] if len(tokens) > 1 else []
    for token in middle:
        if token in _MALE_MARKERS:
            return "male"
        if token in _FEMALE_MARKERS:
            return "female"
    given = tokens[-1]
    if given in _MALE:
        return "male"
    if given in _FEMALE:
        return "female"
    return ""


__all__ = ["infer_gender_from_name"]
