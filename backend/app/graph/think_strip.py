"""Provider-artefact stripping for user-visible bot replies.

The pre-send answer review layer that used to live here — ``fast_safety_filter``,
``DeterministicReplyPolicy``, ``truncate_for_chat`` — was removed on explicit
operator instruction: it re-judged and rewrote the agent's answer after
generation (empty-retry, truncation, verdicts) while adding no LLM call worth
its cost. The agent's answer now ships as generated — with one exception that
belongs to generation, not review: a provider that stops at its output cap is
continued (and, failing that, has its dangling tail dropped) inside
``clients.MiniMaxAgent``, so a half-written answer is never delivered. See the
answer-completion guard in ``clients.py``.

One invariant remains: no provider artefact may reach a candidate. Two of them
arrive inline inside the content, so every reply passes through
:func:`strip_provider_artifacts` exactly once at the converged boundary in
``runner._finalize_user_visible_reply``:

- MiniMax M2 deliberation, in think blocks (:func:`strip_think_reasoning`);
- a tool call the provider serialized as *content* instead of the ``tool_calls``
  field (:func:`extract_text_tool_calls` / :func:`strip_tool_call_markup`). One
  such turn was delivered verbatim to a candidate — ``Dạ, để em kiểm tra …``
  followed by ``<invoke name="search_knowledge">…`` — so the markup is parsed at
  the agent loop (where the call can still be executed) and stripped at the
  boundary (so it can never leak even when it cannot be parsed).
"""

from __future__ import annotations

import json
import re

# MiniMax M2 reasoning models wrap deliberation in think tags; the user-facing
# reply is what follows the last closing tag. These three patterns are the single
# source of truth for think-block semantics: ``strip_think_reasoning`` removes
# them from the final text, and ``visible_offset`` locates where candidate-visible
# text begins in the raw stream.
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<\s*think\b", re.IGNORECASE)
_THINK_TRUNCATED_RE = re.compile(r"<\s*think\b[\s\S]*$", re.IGNORECASE)


def visible_offset(raw: str) -> int | None:
    """Index in ``raw`` where candidate-visible text starts.

    ``0`` when there is no think block, the end of the last closing tag when the
    deliberation is complete, and ``None`` while a think block is still open (the
    stream so far is pure deliberation and nothing is visible yet).
    """
    raw = raw or ""
    matches = list(_THINK_CLOSE_RE.finditer(raw))
    if matches:
        return matches[-1].end()
    if _THINK_OPEN_RE.search(raw):
        return None
    return 0


def strip_think_reasoning(raw: str) -> str:
    """Remove complete or truncated provider reasoning from user-visible text."""
    raw = raw or ""
    if _THINK_CLOSE_RE.search(raw):
        raw = _THINK_CLOSE_RE.split(raw)[-1]
    # A provider timeout can truncate output before the closing tag. In that case
    # everything after the unmatched opener is still deliberation, not a reply.
    # Discard the incomplete block instead of removing only its tag and exposing
    # the reasoning text as user-visible content.
    raw = _THINK_TRUNCATED_RE.sub("", raw)
    return raw


# ── Tool-call markup written as content ─────────────────────────────────────
# A provider may serialize an invocation into the message content instead of the
# structured ``tool_calls`` field. The syntax seen in production is the
# Anthropic-style block below (with an optional namespace prefix, which is why
# every tag pattern tolerates ``antml:``-style names).
_INVOKE_OPEN_RE = re.compile(r"<\s*(?:\w+:)?invoke\b", re.IGNORECASE)
_INVOKE_BLOCK_RE = re.compile(
    r"<\s*(?:\w+:)?invoke\b[^>]*>(?P<body>.*?)<\s*/\s*(?:\w+:)?invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_RE = re.compile(
    r"<\s*(?:\w+:)?parameter\b[^>]*?name\s*=\s*[\"'](?P<name>[^\"']+)[\"'][^>]*>"
    r"(?P<value>.*?)<\s*/\s*(?:\w+:)?parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_NAME_RE = re.compile(r"\bname\s*=\s*[\"'](?P<name>[^\"']+)[\"']", re.IGNORECASE)
_MARKUP_TAG_RE = re.compile(
    r"<\s*/?\s*(?:\w+:)?(?:invoke|parameter|function_calls|tool_call|tool_calls)\b[^>]*>",
    re.IGNORECASE,
)


def _coerce_argument(raw: str) -> object:
    """A parameter value as JSON when it parses, else the stripped string."""
    text = (raw or "").strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text
    return text if isinstance(parsed, str) else parsed


def extract_text_tool_calls(raw: str) -> list[dict]:
    """Tool calls the provider wrote as content, in call order.

    Each entry mirrors the shape of a provider ``tool_calls`` item
    (``{"name", "args", "id"}``) so the agent loop can dispatch it exactly like a
    structured call. An ``<invoke>`` block without a name is skipped — the reply
    is still stripped at the boundary, so nothing leaks either way.
    """
    text = raw or ""
    calls: list[dict] = []
    for match in _INVOKE_BLOCK_RE.finditer(text):
        header = text[match.start() : match.start("body")]
        name_match = _ATTR_NAME_RE.search(header)
        name = name_match.group("name").strip() if name_match else ""
        if not name:
            continue
        args: dict[str, object] = {}
        for parameter in _PARAMETER_RE.finditer(match.group("body")):
            args[parameter.group("name").strip()] = _coerce_argument(parameter.group("value"))
        calls.append({"name": name, "args": args, "id": f"text-call-{len(calls) + 1}"})
    return calls


def strip_tool_call_markup(raw: str) -> str:
    """Remove tool-call markup from user-visible text.

    Complete invoke blocks go first; an unclosed one (a stream or generation cut
    mid-call) takes the rest of the text with it, exactly as a truncated think
    block does — a half-written call is not a reply. Stray markup tags are
    dropped last so no fragment can survive on its own.
    """
    text = raw or ""
    text = _INVOKE_BLOCK_RE.sub("", text)
    open_match = _INVOKE_OPEN_RE.search(text)
    if open_match:
        text = text[: open_match.start()]
    return _MARKUP_TAG_RE.sub("", text)


def strip_provider_artifacts(raw: str) -> str:
    """The converged boundary: provider thinking and tool-call markup removed."""
    return strip_tool_call_markup(strip_think_reasoning(raw))


# Zalo renders plain text: markdown decorations the model wraps around its
# answer reach the candidate as literal asterisks/ticks (observed 2026-10-01:
# "- **4P Electronics**: ..."). The operator persona already forbids markdown;
# this is the deterministic backstop that strips the decorations while keeping
# the words and list structure.
_BOLD_RE = re.compile(r"\*\*(?P<text>[^*\n]+)\*\*|__(?P<under>[^_\n]+)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?P<text>[^*\n]+)\*(?![\w*])")
_STRIKE_RE = re.compile(r"~~(?P<text>[^~\n]+)~~")
_FENCE_RE = re.compile(r"```+(?P<lang>[\w+-]*\n?)?(?P<text>[^`]+?)```+", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`(?P<text>[^`\n]+)`")
_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\n]+)\)")


def strip_markdown_decorations(raw: str) -> str:
    """Remove markdown emphasis/code/link decorations from plain-text output.

    Pure decoration removal: whitespace is preserved exactly (progressive-send
    bubble offsets and pinned reply text are whitespace-sensitive), list
    markers and paragraph structure stay — they read naturally as plain text.
    Markdown links degrade to ``text (url)`` so the address survives.
    """
    text = _BOLD_RE.sub(lambda m: m.group("text") or m.group("under") or "", raw)
    text = _STRIKE_RE.sub(lambda m: m.group("text"), text)
    text = _FENCE_RE.sub(lambda m: f"{m.group('lang') or ''}{m.group('text')}", text)
    text = _INLINE_CODE_RE.sub(lambda m: m.group("text"), text)
    text = _MD_LINK_RE.sub(lambda m: f"{m.group('text')} ({m.group('url')})", text)
    text = _HEADING_RE.sub("", text)
    return _ITALIC_RE.sub(lambda m: m.group("text"), text)
