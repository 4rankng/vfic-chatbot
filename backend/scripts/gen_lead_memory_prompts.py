#!/usr/bin/env python3
"""Regenerate app/graph/lead_memory_prompts.py VERBATIM from the Persist workflows.

    python -m scripts.gen_lead_memory_prompts

Emits LEAD_EXTRACT_SYSTEM_PROMPT (from VFIC Persist Lead.json) and MEMORY_EXTRACT_PROMPT
(from VFIC Persist Memories.json) as triple-quoted constants. CI asserts byte-equality.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "app" / "graph" / "lead_memory_prompts.py"


def _triple(name: str, text: str) -> str:
    assert "\\" not in text, f"{name} contains a backslash"
    assert '"""' not in text, f"{name} contains a triple-quote"
    return f'{name} = """{text}"""\n'


def main() -> None:
    lead = json.loads((ROOT / "n8n-workflows" / "VFIC Persist Lead.json").read_text(encoding="utf-8"))
    mem = json.loads((ROOT / "n8n-workflows" / "VFIC Persist Memories.json").read_text(encoding="utf-8"))
    ln = {n["name"]: n for n in lead["nodes"]}
    mn = {n["name"]: n for n in mem["nodes"]}

    lead_prompt = ln["Extract Lead"]["parameters"]["messages"]["messageValues"][0]["message"]
    mem_prompt = mn["Extract Memories"]["parameters"]["messages"]["messageValues"][0]["message"]

    parts = [
        '"""Lead-extraction + memory-extraction prompts — VERBATIM from the Persist\n'
        "workflows. DO NOT EDIT BY HAND; regenerate via `python -m scripts.gen_lead_memory_prompts`.\n"
        'CI asserts byte-equality (tests/test_prompts_byte_equal.py).\n"""\n',
        _triple("LEAD_EXTRACT_SYSTEM_PROMPT", lead_prompt),
        _triple("MEMORY_EXTRACT_PROMPT", mem_prompt),
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} (lead={len(lead_prompt)} memory={len(mem_prompt)} chars)")


if __name__ == "__main__":
    main()
