"""Provider reasoning-field compatibility for the LangChain OpenAI adapter.

MiniMax and OpenRouter return interleaved reasoning out of band —
``reasoning_content`` / ``reasoning_details`` on the message, or ``<think>``
blocks inside the content. LangChain's generic OpenAI adapter intentionally
drops those fields, which breaks the tool loop that must forward them unchanged
on the next request. This module owns that wire compatibility and nothing else;
the chat factories that consume :func:`_reasoning_chat_class` live in
``graph/clients.py``.
"""

from __future__ import annotations

import re
from functools import lru_cache

_REASONING_RESPONSE_FIELDS = ("reasoning_details", "reasoning_content", "reasoning")
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>(.*?)</think\s*>", re.IGNORECASE | re.DOTALL)


def _reasoning_text_from_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(
            part for item in value if (part := _reasoning_text_from_value(item))
        ).strip()
    if isinstance(value, dict):
        for key in ("text", "reasoning", "summary"):
            if key in value and (text := _reasoning_text_from_value(value[key])):
                return text
    return ""


def _extract_returned_reasoning(ai: object) -> str | None:
    """Extract provider-returned reasoning without including the final answer."""
    additional_kwargs = getattr(ai, "additional_kwargs", {})
    if isinstance(additional_kwargs, dict):
        for key in _REASONING_RESPONSE_FIELDS:
            if key in additional_kwargs and (
                text := _reasoning_text_from_value(additional_kwargs[key])
            ):
                return text

    try:
        content_blocks = getattr(ai, "content_blocks", [])
    except Exception:  # noqa: BLE001 - provider message compatibility is best-effort
        content_blocks = []
    if isinstance(content_blocks, list):
        reasoning_blocks = [
            block
            for block in content_blocks
            if isinstance(block, dict)
            and (block["type"] if "type" in block else None) in {"reasoning", "thinking"}
        ]
        if text := _reasoning_text_from_value(reasoning_blocks):
            return text

    content = getattr(ai, "content", "")
    if isinstance(content, str):
        blocks = [match.strip() for match in _THINK_BLOCK_RE.findall(content) if match.strip()]
        if blocks:
            return "\n\n".join(blocks)
        opening = re.search(r"<think\b[^>]*>", content, re.IGNORECASE)
        if opening and (unfinished := content[opening.end() :].strip()):
            return unfinished
    return None


@lru_cache(maxsize=1)
def _reasoning_chat_class():
    """ChatOpenAI variant that preserves third-party reasoning fields.

    LangChain's generic OpenAI adapter intentionally drops fields such as
    ``reasoning_content`` and ``reasoning_details``. The subclass keeps those
    fields on AIMessage.additional_kwargs and forwards them unchanged on later
    tool-loop requests, as required by MiniMax/OpenRouter interleaved thinking.
    """
    from langchain_core.messages import AIMessage
    from langchain_openai import ChatOpenAI

    class ReasoningPreservingChatOpenAI(ChatOpenAI):
        trace_provider: str = "unknown"
        # Wire-level cache marker attached to the leading system message. Set
        # only where the provider documents an explicit marker for this
        # endpoint: OpenRouter's prompt caching takes an Anthropic-style
        # ``cache_control`` on a content block (openrouter.ai/docs/features/
        # prompt-caching). MiniMax's OpenAI-compatible API caches the prefix
        # automatically and documents no marker for it, and the operator-
        # configured custom provider is an unknown vendor — sending it an
        # undocumented marker could reject every request on that lane.
        system_prefix_cache_control: dict = {}

        def _create_chat_result(self, response, generation_info=None):
            response_dict = (
                response
                if isinstance(response, dict)
                else response.model_dump(warnings=False)
            )
            result = super()._create_chat_result(response, generation_info)
            choices = response_dict["choices"] if "choices" in response_dict else []
            for generation, choice in zip(
                result.generations,
                choices or [],
                strict=False,
            ):
                raw_message = choice["message"] if "message" in choice else {}
                if not isinstance(generation.message, AIMessage):
                    continue
                for key in _REASONING_RESPONSE_FIELDS:
                    if key in raw_message and raw_message[key] is not None:
                        generation.message.additional_kwargs[key] = raw_message[key]
            return result

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            source_messages = self._convert_input(input_).to_messages()
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            wire_messages = payload["messages"] if "messages" in payload else None
            if not isinstance(wire_messages, list):
                return payload
            if self.system_prefix_cache_control and wire_messages:
                # Cache breakpoint on the stable prefix boundary: everything
                # before and including the first system message. The text is
                # rewrapped as a single content block — identical bytes, plus
                # the marker — so the prompt itself is untouched.
                first = wire_messages[0]
                if (
                    isinstance(first, dict)
                    and "role" in first
                    and first["role"] == "system"
                    and "content" in first
                    and isinstance(first["content"], str)
                    and first["content"]
                ):
                    first["content"] = [
                        {
                            "type": "text",
                            "text": first["content"],
                            "cache_control": self.system_prefix_cache_control,
                        }
                    ]
            for source, wire in zip(source_messages, wire_messages, strict=False):
                if not isinstance(source, AIMessage) or not isinstance(wire, dict):
                    continue
                for key in _REASONING_RESPONSE_FIELDS:
                    if key in source.additional_kwargs and source.additional_kwargs[key] is not None:
                        wire[key] = source.additional_kwargs[key]
            return payload

    return ReasoningPreservingChatOpenAI
