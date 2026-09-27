"""Framework-free Vietnamese text normalization and markdown flattening."""

from __future__ import annotations

import re
import unicodedata


_LINK = re.compile(r"!?\[([^\]]+)\]\(([^)\s]+)\)")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*\*([^*\n]+)\*\*\*|___([^_\n]+)___")
_STRONG = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])|(?<!\w)_([^_\n]+)_(?!\w)")
_STRIKE = re.compile(r"~~([^~\n]+)~~")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_BULLET = re.compile(r"^[ \t]{0,3}[*+][ \t]+", re.MULTILINE)
_HRULE = re.compile(r"^[ \t]{0,3}(?:-\s*){3,}$|^[ \t]{0,3}(?:\*\s*){3,}$|^[ \t]{0,3}(?:_\s*){3,}$", re.MULTILINE)
_BLANKS = re.compile(r"\n{3,}")


def plain_text(markdown: str) -> str:
    """Flatten markdown to the plain text a non-rendering channel can show.

    The agent reply is written once for every channel, but Zalo renders message
    text verbatim: ``**bold**`` and ``[text](url)`` would reach users as literal
    asterisks and brackets. Emphasis markup is dropped and links keep their
    target as bare text — Zalo clients auto-link bare URLs.
    """
    if not markdown:
        return markdown
    text = _LINK.sub(_link_target, markdown)
    text = _CODE_SPAN.sub(r"\1", text)
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _STRONG.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _STRIKE.sub(r"\1", text)
    text = _HEADING.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _BULLET.sub("- ", text)
    text = _HRULE.sub("", text)
    return _BLANKS.sub("\n\n", text).strip()


def _link_target(match: re.Match[str]) -> str:
    label, target = match.group(1).strip(), match.group(2)
    if not label or label == target:
        return target
    return f"{label}: {target}"


def normalize_vietnamese_text(value: str) -> str:
    """Return accent-insensitive, lowercased, whitespace-collapsed text."""

    no_marks = "".join(
        character
        for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(no_marks.replace("đ", "d").split())


__all__ = ["normalize_vietnamese_text", "plain_text"]
