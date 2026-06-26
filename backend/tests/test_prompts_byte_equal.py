"""CI guard: the 3 VFIC prompt strings in app/graph/prompts.py must be byte-equal
to n8n-workflows/VFIC Chatbot.json. Catches prompt drift (the core behavior IP)."""
import json
import os
import pytest
import re
from pathlib import Path

from app.graph.prompts import ERROR_REPLY, SAFETY_PROMPT


def _workflow_path() -> Path:
    candidates = [
        Path(os.environ.get("N8N_WORKFLOWS_DIR", "")) / "VFIC Chatbot.json",
        Path(__file__).resolve().parents[2] / "n8n-workflows" / "VFIC Chatbot.json",
        Path("/repo/n8n-workflows/VFIC Chatbot.json"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("VFIC Chatbot.json not found; set N8N_WORKFLOWS_DIR")


# The n8n-workflows/ tree is DR-only and may be absent from a checkout. Skip the
# whole module (rather than erroring at collection) when the ground-truth file
# is missing — these tests guard prompt drift, not core runtime behavior.
try:
    WORKFLOW = _workflow_path()
except FileNotFoundError:
    pytest.skip(
        "VFIC Chatbot.json not found; set N8N_WORKFLOWS_DIR",
        allow_module_level=True,
    )


def _workflow(name: str) -> Path:
    p = WORKFLOW.parent / name
    if not p.exists():
        raise FileNotFoundError(f"{name} not found next to {WORKFLOW}")
    return p


def _nodes(path: Path) -> dict:
    return {n["name"]: n for n in json.loads(path.read_text(encoding="utf-8"))["nodes"]}


def test_safety_prompt_byte_equal():
    nodes = _nodes(WORKFLOW)
    expected = nodes["Check Response"]["parameters"]["messages"]["messageValues"][0]["message"]
    assert SAFETY_PROMPT == expected


def test_error_reply_byte_equal():
    nodes = _nodes(WORKFLOW)
    js = nodes["Build Error Reply"]["parameters"]["jsCode"]
    expected = re.search(r"const fallback = '([^']*)'", js).group(1)
    assert ERROR_REPLY == expected


def test_retry_fallbacks_match_try_again_node():
    """The hand-ported retry fallbacks must match the 'Try Again' JS branches."""
    from app.graph.safety import GENERIC_FALLBACK, TECHNICAL_FALLBACK

    nodes = _nodes(WORKFLOW)
    js = nodes["Try Again"]["parameters"]["jsCode"]
    assert TECHNICAL_FALLBACK in js
    assert GENERIC_FALLBACK in js


def test_lead_extract_prompt_byte_equal():
    from app.graph.lead_memory_prompts import LEAD_EXTRACT_SYSTEM_PROMPT

    nodes = _nodes(_workflow("VFIC Persist Lead.json"))
    expected = nodes["Extract Lead"]["parameters"]["messages"]["messageValues"][0]["message"]
    assert LEAD_EXTRACT_SYSTEM_PROMPT == expected


def test_memory_extract_prompt_byte_equal():
    from app.graph.lead_memory_prompts import MEMORY_EXTRACT_PROMPT

    nodes = _nodes(_workflow("VFIC Persist Memories.json"))
    expected = nodes["Extract Memories"]["parameters"]["messages"]["messageValues"][0]["message"]
    assert MEMORY_EXTRACT_PROMPT == expected
