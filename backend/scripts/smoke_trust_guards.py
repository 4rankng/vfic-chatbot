#!/usr/bin/env python3
"""Prompt smoke: the 2026-10-21 trust-postmortem guards over a 3-turn Zalo shape.

Re-runnable evidence generator (``.venv/bin/python -m scripts.smoke_trust_guards``).
Runs the REAL deterministic pipeline — ``lanes._agent_turn`` routing, the
catalog tool with the hard posture filter, the escalation short-circuit, the
post-phone STOP and identity instructions — with only the LLM transport
stubbed: the stub agent composes its reply strictly from the instructions and
tool payload the real pipeline handed it, and the transcript marks those
compositions as simulated. No network, no DB, no provider keys.

Turns (the post-mortem conversation, user Toàn shape):

  1. «cho em xin việc ngồi, đứng lâu không được»
     → physical-constraint gate fires: list_active_projects forced, hard
     filter args pinned server-side, 4P Electronics (standing_only) absent
     from the candidate set the LLM sees.
  2. «Dạ số điện thoại của em là 0912 345 678 ạ»
     → post-phone STOP instruction injected; reply confirms and ends.
  3. «em bị gãy tay chân rồi, việc gì làm được không»
     → escalation short-circuit: the fixed hotline handoff IS the reply; the
     model never runs.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.graph import lanes, trust_guards  # noqa: E402
from app.graph.ports import TurnDecisions  # noqa: E402
from app.graph.types import BotRunState, GraphDeps  # noqa: E402
from app.prompts.vfic_persona import DEFAULT_PERSONA_BODY_MD, IDENTITY_AND_OPENING_RULES  # noqa: E402
from app.recruitment.domain.recommendation import ProjectFeatures, ProjectScopeItem  # noqa: E402

# The post-mortem catalog shape: 4P stands its workers (the posting itself pays
# a đứng-machine allowance); LG Display has seated assembly rows; one plant's
# postings were never parsed (unknown).
FOUR_P = ProjectFeatures(
    project_id="4p", slug="4p-electronics", name="4P Electronics", company="4P",
    scope=(ProjectScopeItem(title="Công nhân đứng máy SMT", posture="standing_only"),),
    posture="standing_only",
)
LG_SEATED = ProjectFeatures(
    project_id="lgd", slug="lg-display", name="LG Display", company="LG",
    province="Hải Phòng",
    scope=(ProjectScopeItem(title="Lắp ráp bo mạch (seated_only)", posture="seated_only"),),
    posture="seated_only",
)
UNPARSED = ProjectFeatures(
    project_id="unk", slug="unparsed-plant", name="Nhà máy chưa trích xuất", company="?",
    scope=(ProjectScopeItem(title="Vận hành dây chuyền", posture="unknown"),),
    posture="unknown",
)


class _Retrieval:
    async def list_active_projects(self):
        return [FOUR_P, LG_SEATED, UNPARSED]


class _SmokeAgent:
    """LLM stand-in: records what the model was handed, replies per contract.

    The replies are hand-authored simulations that honour the injected
    instructions; everything they are based on (forced tool, pinned filter
    args, tool payload, STOP/escalation) is produced by the real pipeline.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def agent(self, text: str, **kwargs: dict) -> str:
        self.calls.append((text, kwargs))
        if kwargs.get("required_tool_arg_overrides"):
            # Turn 1: the filter already removed 4P/unknown; the contract says
            # pitch only what the payload carries.
            return (
                "Dạ với yêu cầu ngồi làm, hiện em có dự án LG Display (Hải Phòng) "
                "vị trí lắp ráp bo mạch được làm ngồi ạ. Anh/chị cho em xin số điện "
                "thoại để chuyên viên gọi tư vấn nhé ạ."
            )
        # Turn 2: the STOP instruction is in the contextual text.
        return (
            "Dạ em đã nhận số điện thoại của anh ạ. Chuyên viên tuyển dụng bên em "
            "sẽ gọi lại hỗ trợ anh trong giờ hành chính nhé ạ."
        )


def _state(text: str) -> BotRunState:
    return BotRunState(
        conversation_id="00000000-0000-0000-0000-00000000000f",
        version_at_start=1,
        user_text=text,
    )


def _deps(agent) -> GraphDeps:
    return GraphDeps(
        db=None,  # type: ignore[arg-type]
        agent=agent,  # type: ignore[arg-type]
        embedder=None,  # type: ignore[arg-type]
        zalo=None,
        conversation=None,  # type: ignore[arg-type]
        retrieval=_Retrieval(),  # type: ignore[arg-type]
        lead=None,
    )


async def run() -> str:
    lines: list[str] = []
    agent = _SmokeAgent()

    async def _fake_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    import app.graph.context as context_mod

    original = context_mod.build_system_prompt
    context_mod.build_system_prompt = _fake_system_prompt
    try:
        # Turn 1 — seated constraint.
        timings1: dict = {}
        reply1 = await lanes._agent_turn(
            _state(T1_TEXT), _deps(agent), T1_TEXT,
            provider="zalo_bot", chat_id="smoke-zalo",
            recent_messages=[], timings=timings1,
            decisions=TurnDecisions(intent="recommend", intent_confidence=0.9),
        )
        kwargs1 = agent.calls[-1][1]
        from app.graph.tools.catalog import list_active_projects as tool

        payload1 = await tool(_Retrieval(), work_posture="seated")
        body1 = json.loads(
            next(
                line
                for line in payload1.splitlines()
                if line.startswith("ACTIVE_PROJECT_LOOKUP_JSON=")
            ).removeprefix("ACTIVE_PROJECT_LOOKUP_JSON=")
        )

        # Turn 2 — phone handover.
        timings2: dict = {}
        reply2 = await lanes._agent_turn(
            _state(T2_TEXT), _deps(agent), T2_TEXT,
            provider="zalo_bot", chat_id="smoke-zalo",
            recent_messages=[], timings=timings2,
            decisions=TurnDecisions(intent="profile_update", intent_confidence=0.9),
        )
        contextual2 = agent.calls[-1][0]

        # Turn 3 — injury disclosure.
        timings3: dict = {}
        reply3 = await lanes._agent_turn(
            _state(T3_TEXT), _deps(agent), T3_TEXT,
            provider="zalo_bot", chat_id="smoke-zalo",
            recent_messages=[], timings=timings3,
        )
    finally:
        context_mod.build_system_prompt = original

    candidate_names = [p.get("project") for p in body1["projects"]]
    lines += [
        "# Trust post-mortem prompt smoke — 3 turns (Zalo, user Toàn shape)",
        "",
        "Pipeline parts exercised for real: constraint gate → forced catalog tool →",
        "server-pinned filter args → hard posture filter → tool payload; post-phone",
        "STOP instruction; escalation short-circuit. LLM transport stubbed — the",
        "candidate-facing prose on turns 1-2 is hand-authored to the injected",
        "contract and marked SIMULATED; turn 3 is the code-authored fixed reply.",
        "",
        "## Turn 1 — «%s»" % T1_TEXT,
        "",
        "- gate: `physical_constraint_filter` = `%s`" % timings1.get(
            "physical_constraint_filter"
        ),
        "- forced tool: `%s`" % kwargs1.get("required_tool"),
        "- pinned args (server-side, model cannot drop): `%s`" % kwargs1.get(
            "required_tool_arg_overrides"
        ),
        "- candidate set the LLM sees (post-filter): %s" % candidate_names,
        "- 4P Electronics present? %s" % ("4P Electronics" in str(candidate_names)),
        "- unknown-posture project present? %s" % ("chưa trích xuất" in str(candidate_names)),
        "- route hint starts with the seated contract: %s" % (
            "ĐÃ BỊ LOẠI" in agent.calls[0][0]
        ),
        "",
        "BOT (SIMULATED per contract):",
        "",
        "> " + reply1.replace("\n", "\n> "),
        "",
        "## Turn 2 — «%s»" % T2_TEXT,
        "",
        "- STOP instruction injected: %s" % (
            trust_guards.POST_PHONE_STOP_INSTRUCTION in contextual2
        ),
        "- STOP flag in timings: %s" % timings2.get("post_phone_stop"),
        "",
        "BOT (SIMULATED per STOP contract):",
        "",
        "> " + reply2.replace("\n", "\n> "),
        "",
        "## Turn 3 — «%s»" % T3_TEXT,
        "",
        "- escalation fired (route_reason=%s), model never ran (agent calls: %d)"
        % (timings3.get("route_reason"), len(agent.calls) - 2),
        "",
        "BOT (CODE-AUTHORED, owner template):",
        "",
        "> " + reply3.replace("\n", "\n> "),
        "",
        "## Persona rules now in force (excerpt)",
        "",
        "- identity honesty: %s" % (
            "TỰ ĐỘNG" in IDENTITY_AND_OPENING_RULES
            and "KHÔNG khẳng định cũng không phủ nhận" not in IDENTITY_AND_OPENING_RULES
        ),
        "- anti-repetition block in system prompt rules: %s" % (
            "QUY TẮC NGẮN GỌN VÀ KHÔNG LẶP"
            in open(context_mod.__file__, encoding="utf-8").read()
        ),
        "- persona body carries no «không tự giới thiệu là bất kỳ thứ gì khác»: %s"
        % ("không tự giới thiệu là bất kỳ thứ gì khác" not in DEFAULT_PERSONA_BODY_MD),
        "",
    ]
    verdict = (
        candidate_names == ["LG Display"]
        and trust_guards.POST_PHONE_STOP_INSTRUCTION in contextual2
        and reply3 == trust_guards.escalation_reply()
    )
    lines += ["## Verdict: %s" % ("PASS" if verdict else "FAIL"), ""]
    return "\n".join(lines)


T1_TEXT = "cho em xin việc ngồi, đứng lâu không được"
T2_TEXT = "Dạ số điện thoại của em là 0912 345 678 ạ"
T3_TEXT = "em bị gãy tay chân rồi, việc gì làm được không"


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text = asyncio.run(run())
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
