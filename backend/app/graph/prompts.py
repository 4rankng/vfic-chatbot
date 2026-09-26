"""VFIC chatbot prompts.

The agent persona lives in ``persona.md`` (next to this file) and is loaded at
import time — edit that Markdown file to tune the bot's 7-part role definition;
no Python changes are required.
"""

from pathlib import Path

_PERSONA_PATH = Path(__file__).resolve().parent / "persona.md"
# Source of truth for the bot's behaviour. Loaded once at import so a missing or
# corrupt file fails fast at worker startup rather than mid-conversation.
AGENT_SYSTEM_PROMPT = _PERSONA_PATH.read_text(encoding="utf-8").strip()
