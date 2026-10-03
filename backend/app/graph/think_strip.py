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
# structured ``tool_calls`` field. Two syntaxes are in production:
#
# * the Anthropic-style block (an optional namespace prefix, which is why every
#   tag pattern tolerates ``antml:``-style names), and
# * the DSML block, which closes the namespace with U+FF5C FULLWIDTH VERTICAL
#   LINE rather than ``>``: ``<｜DSML｜ invoke name="x">``.
#
# Matching only the ASCII form was not a cosmetic gap. On 2026-10-03 a DSML call
# was neither dispatched nor stripped, so the raw protocol — tags, tool name and
# arguments — was delivered verbatim to a candidate in chat.
#
# ``DSML`` closes the optional namespace in both the ASCII and the fullwidth-bar
# spelling, so it belongs where ``antml:`` does: inside the prefix group.
_DSML_NS = r"(?:｜\s*DSML\s*｜\s*|\w+:)?"
_INVOKE_OPEN_RE = re.compile(rf"<\s*{_DSML_NS}invoke\b", re.IGNORECASE)
_INVOKE_BLOCK_RE = re.compile(
    rf"<\s*{_DSML_NS}invoke\b[^>]*>(?P<body>.*?)<\s*/\s*{_DSML_NS}invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_RE = re.compile(
    rf"<\s*{_DSML_NS}parameter\b[^>]*?name\s*=\s*[\"'](?P<name>[^\"']+)[\"'][^>]*>"
    rf"(?P<value>.*?)<\s*/\s*{_DSML_NS}parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_NAME_RE = re.compile(r"\bname\s*=\s*[\"'](?P<name>[^\"']+)[\"']", re.IGNORECASE)
_MARKUP_TAG_RE = re.compile(
    rf"<\s*/?\s*{_DSML_NS}(?:invoke|parameter|function_calls|tool_call|tool_calls|calls)\b[^>]*>",
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


# The last-resort detector, and deliberately independent of the parsers above.
#
# ``extract_text_tool_calls`` and ``strip_tool_call_markup`` are two separate
# best-effort regexes over formats we have seen. When a provider invents a NEW
# serialization, BOTH miss it and the raw protocol is treated as a perfectly
# good assistant answer — which is how ``<｜DSML｜ invoke name="...">`` reached a
# candidate on 2026-10-03. A parser that misses is recoverable (the call simply
# does not run); a stripper that misses is not (the candidate reads our
# internals). So the boundary also *detects* protocol residue and the caller
# falls back to a safe reply instead of sending it.
#
# Matched on the shape, not on a known tag list: an opening delimiter followed
# by a protocol-ish name, or any of the namespace/attribute tells.
_PROTOCOL_RESIDUE_RE = re.compile(
    # Any angle-bracket tag, in either delimiter family. The operator persona
    # forbids markdown and Zalo renders plain text, so a candidate's reply has
    # no legitimate reason to contain "<tag>"; anchoring on the delimiter (not
    # on a list of known tag names) is what makes this catch a format we have
    # never seen. `1-3` leading slashes also covers a closed "</think>"-style
    # tail. A false positive fails safe — the round is retried, not delivered.
    r"<\s*/{0,3}\s*[\w:｜|]"
    # The explicit tells, kept because they are unambiguous on their own.
    r"|｜\s*DSML\s*｜"
    r"|\bname\s*=\s*[\"'][A-Za-z_][\w.]*[\"']\s*>",
    re.IGNORECASE,
)


def contains_tool_protocol(text: str) -> bool:
    """Whether ``text`` still carries tool-call protocol the stripper missed.

    A caller that sees ``True`` must NOT deliver the text. It should fall back
    to a grounded or safe reply. Written to be format-agnostic on purpose: the
    2026-10-03 leak happened because the detectors only knew formats already in
    the wild.
    """
    return bool(_PROTOCOL_RESIDUE_RE.search(text or ""))


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
# Provider hiccups emit U+FFFD mid-Vietnamese words (observed 2026-10-01 in two
# delivered replies: "Thu\uFFFDuyên", "để \uFFFDn điện thoại"). The character is
# never meaningful in the operator's content — drop the runs.
_REPLACEMENT_RE = re.compile("\ufffd+")


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
    text = _REPLACEMENT_RE.sub("", text)
    return _ITALIC_RE.sub(lambda m: m.group("text"), text)
