"""Trust gates from the Zalo post-mortem 2026-10-21 (user Toàn, 19:06–19:29).

The post-mortem's four failures, each pinned by the gate that now prevents it:

- A. 4P Electronics (standing-only) was pitched as seated work → structured
  job attributes + a deterministic hard pre-filter in ``rank_projects`` +
  server-injected tool args (``graph/trust_guards.py`` → ``clients.dispatch_one``).
- B.  the same job/salary blurb re-pasted across turns → repetition detector
  + one bounded regeneration (``_repetition_self_check``).
- C.  no human handoff after an injury disclosure; interrogation continued
  after the phone number arrived → fixed escalation reply + post-phone STOP.
- D.  the bot dodged «bot à?» → honest-identity rules + deterministic
  instruction.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.graph import lanes, trust_guards
from app.graph.clients import _AgentTurn
from app.graph.ports import TurnDecisions
from app.graph.types import BotRunState, GraphDeps
from app.prompts.vfic_persona import (
    DEFAULT_PERSONA_BODY_MD,
    IDENTITY_AND_OPENING_RULES,
    VFIC_HOTLINE,
    vfic_hotline_reply,
)
from app.recruitment.domain.recommendation import (
    ProjectFeatures,
    ProjectScopeItem,
    aggregate_heavy_lifting,
    aggregate_posture,
    rank_projects,
)

pytestmark = pytest.mark.timeout(30)

# ── shared catalog fixtures ─────────────────────────────────────────────────

FOUR_P = ProjectFeatures(
    project_id="4p-id",
    slug="4p-electronics",
    name="4P Electronics",
    company="4P",
    scope=(ProjectScopeItem(title="Công nhân đứng máy SMT", posture="standing_only"),),
    posture="standing_only",
)
SEATED = ProjectFeatures(
    project_id="lgd-id",
    slug="lg-display",
    name="LG Display",
    company="LG",
    scope=(ProjectScopeItem(title="Lắp ráp bo mạch", posture="seated_only"),),
    posture="seated_only",
)
UNKNOWN_PLANT = ProjectFeatures(
    project_id="unk-id",
    slug="unknown-plant",
    name="Nhà máy chưa rõ",
    company="?",
    scope=(ProjectScopeItem(title="Vận hành.line"),),  # posture defaults unknown
    posture="unknown",
)


class _CatalogRetrieval:
    """GraphRetrievalPort double holding a fixed catalog."""

    def __init__(self, *catalog: ProjectFeatures) -> None:
        self.catalog = list(catalog)

    async def list_active_projects(self):
        return list(self.catalog)


# ── A. hard pre-filter ──────────────────────────────────────────────────────


def test_seated_request_excludes_standing_only_project_4p() -> None:
    """The post-mortem's core gate: a seated request NEVER pitches 4P.

    standing_only AND unknown are excluded from the ranked set — an unparsed
    posting is not a promise, so it cannot satisfy a stated constraint either.
    """
    lookup = rank_projects([FOUR_P, SEATED, UNKNOWN_PLANT], work_posture="seated")
    names = [fit.project.name for fit in lookup.fits]
    assert "4P Electronics" not in names
    assert "Nhà máy chưa rõ" not in names
    assert names == ["LG Display"]


def test_seated_request_excludes_4p_from_tool_candidate_set() -> None:
    """The LLM-facing candidate set (tool payload) drops 4P on seated asks."""
    import asyncio

    from app.graph.tools.catalog import list_active_projects

    result = asyncio.run(
        list_active_projects(_CatalogRetrieval(FOUR_P, SEATED, UNKNOWN_PLANT), work_posture="seated")
    )
    payload = json.loads(
        next(line for line in result.splitlines() if line.startswith("ACTIVE_PROJECT_LOOKUP_JSON="))
        .removeprefix("ACTIVE_PROJECT_LOOKUP_JSON=")
        .strip()
    )
    names = [project["project"] for project in payload["projects"]]
    assert names == ["LG Display"]
    assert "4P" not in result


def test_no_heavy_lifting_keeps_only_lifting_free_projects() -> None:
    heavy = ProjectFeatures(
        project_id="h",
        slug="h",
        name="Kho nặng",
        scope=(ProjectScopeItem(title="Bốc vác", heavy_lifting="heavy_over_10kg"),),
        heavy_lifting="heavy_over_10kg",
    )
    free = ProjectFeatures(
        project_id="f",
        slug="f",
        name="Đóng gói nhẹ",
        scope=(ProjectScopeItem(title="Đóng gói", heavy_lifting="no"),),
        heavy_lifting="no",
    )
    lookup = rank_projects([heavy, free, UNKNOWN_PLANT], no_heavy_lifting=True)
    assert [fit.project.name for fit in lookup.fits] == ["Đóng gói nhẹ"]


def test_unfiltered_lookup_keeps_the_whole_catalog() -> None:
    """Without a stated constraint the filter must not narrow the catalog."""
    lookup = rank_projects([FOUR_P, SEATED, UNKNOWN_PLANT])
    assert lookup.total == 3


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (("standing_only",), "standing_only"),
        (("seated_only",), "seated_only"),
        (("seated_only", "standing_only"), "mixed"),
        (("mixed",), "mixed"),
        # unknown rows never upgrade an empty known set
        (("unknown", "unknown"), "unknown"),
        # a known seated row beside unknown rows still offers seated work
        (("seated_only", "unknown"), "seated_only"),
    ],
)
def test_aggregate_posture(items, expected) -> None:
    scope = tuple(ProjectScopeItem(title="việc", posture=value) for value in items)
    assert aggregate_posture(scope) == expected


def test_aggregate_heavy_lifting_reports_the_lightest_known_offer() -> None:
    scope = (
        ProjectScopeItem(title="kho", heavy_lifting="heavy_over_10kg"),
        ProjectScopeItem(title="đóng gói", heavy_lifting="no"),
        ProjectScopeItem(title="khác"),
    )
    assert aggregate_heavy_lifting(scope) == "no"
    assert aggregate_heavy_lifting((ProjectScopeItem(title="x"),)) == "unknown"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("em muốn việc ngồi, đứng lâu không được", {"work_posture": "seated"}),
        ("tay chân em khó vận động, có việc nào hợp không", {"work_posture": "seated"}),
        ("cho em xin việc ngồi làm", {"work_posture": "seated"}),
        ("em không mang vác được, việc nhẹ thôi", {"work_posture": "seated", "no_heavy_lifting": True}),
        ("em khong nhac do nang duoc", {"work_posture": "seated", "no_heavy_lifting": True}),
        # Ordinary job questions state no constraint: nothing injected.
        ("có việc nào lương 10 triệu không", {}),
        ("lịch xe đưa đón thế nào", {}),
    ],
)
def test_physical_constraint_tool_args(text, expected) -> None:
    assert trust_guards.physical_constraint_tool_args(text) == expected


def test_constraint_arg_floor_merges_into_model_supplied_args(monkeypatch) -> None:
    """dispatch_one merges the floor into whatever the model passed.

    The model's own composition (location) survives; the constrained keys are
    pinned server-side, so a model that forgets (or nulls) work_posture cannot
    reopen the standing-only catalog.
    """
    captured: dict = {}

    async def _fake_tool(retrieval, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("app.graph.schemas.list_active_projects", _fake_tool)
    turn = _AgentTurn(
        user_text="việc ngồi",
        system="sys",
        retrieval=SimpleNamespace(),
        embedder=None,
        allowed_tools=("list_active_projects",),
        resolved_tool_registry=None,
        make_retrieval=None,
        metrics={},
        required_tool="list_active_projects",
        required_tool_args=None,
        required_tool_arg_overrides={
            "list_active_projects": {"work_posture": "seated"}
        },
        forced_project_slug=None,
        conversation_scope="",
        on_delta=None,
        on_evidence=None,
        active_llm=None,
        schemas=[],
        messages=[],
        effective_query="việc ngồi",
        max_iters=1,
        retry_empty_generation=False,
    )
    import asyncio

    result = asyncio.run(
        turn.dispatch_one(
            {"name": "list_active_projects", "args": {"location": "Hải Phòng", "work_posture": None}}
        )
    )
    assert result == "ok"
    assert captured["work_posture"] == "seated"
    assert captured["location"] == "Hải Phòng"


# ── B. repetition guard ─────────────────────────────────────────────────────

JOB_BLURB = (
    "Dạ bên 4P Electronics đang tuyển công nhân đứng máy SMT, lương 8-11 triệu, "
    "có trợ cấp đứng máy 800 nghìn, kí túc xá miễn phí và xe đưa đón ạ."
)


def test_reply_repeats_prior_block_detects_re_pasted_blurb() -> None:
    assert trust_guards.reply_repeats_prior_block(
        f"Em gửi lại anh nhé. {JOB_BLURB}", JOB_BLURB
    )
    # ≥80% of the whole reply shared with the prior reply
    assert trust_guards.reply_repeats_prior_block(JOB_BLURB, JOB_BLURB)


def test_reply_repeats_prior_block_ignores_fresh_reply() -> None:
    fresh = "Dạ em đã ghi nhận số điện thoại của anh ạ. Chuyên viên sẽ gọi lại cho anh nhé."
    assert not trust_guards.reply_repeats_prior_block(fresh, JOB_BLURB)
    assert not trust_guards.reply_repeats_prior_block("", JOB_BLURB)
    assert not trust_guards.reply_repeats_prior_block(JOB_BLURB, "")


class _ScriptedAgent:
    """Records every call; pops one reply per call."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict]] = []

    async def agent(self, text: str, **kwargs: dict) -> str:
        self.calls.append((text, kwargs))
        return self.replies.pop(0) if self.replies else ""


async def test_repetition_self_check_rewrites_once() -> None:
    agent = _ScriptedAgent(["Trả lời mới ngắn gọn về câu hỏi mới."])
    reply = await lanes._repetition_self_check(
        deps=SimpleNamespace(agent=agent),
        reply=JOB_BLURB,
        agent_kwargs={"system": "sys"},
        timings={},
        user_text="4P lương bao nhiêu",
        chat_id="c1",
        recent_messages=[SimpleNamespace(sender="BOT", body=JOB_BLURB)],
        lead_profile="",
        lead_collection_instruction="",
        route_hint="hãy trả lời",
    )
    assert reply == "Trả lời mới ngắn gọn về câu hỏi mới."
    assert len(agent.calls) == 1  # exactly one retry, never a loop
    assert trust_guards.REPETITION_RETRY_INSTRUCTION in agent.calls[0][0]
    # timings recorded for observability (agent.calls[0][1] carries retry kwargs)


async def test_repetition_self_check_keeps_original_when_retry_fails() -> None:
    class _BrokenAgent:
        async def agent(self, text, **kwargs):
            raise RuntimeError("provider down")

    reply = await lanes._repetition_self_check(
        deps=SimpleNamespace(agent=_BrokenAgent()),
        reply=JOB_BLURB,
        agent_kwargs={"system": "sys"},
        timings={},
        user_text="hỏi lại",
        chat_id="c1",
        recent_messages=[SimpleNamespace(sender="BOT", body=JOB_BLURB)],
        lead_profile="",
        lead_collection_instruction="",
        route_hint="",
    )
    assert reply == JOB_BLURB  # repetitive but grounded beats suppressing


# ── C.1 escalation ──────────────────────────────────────────────────────────

ESCALATION_TRIGGERS = [
    "em bị gãy tay rồi có làm được không",
    "gãy chân rồi việc gì nhẹ cho em",
    "GAY CHAN roi lam gi duoc nua",  # no diacritics
    "em là người khuyết tật, có việc nào không",
    "khuyet tat chan tay co xin viec duoc khong",
    "tôi vừa tai nạn giao thông giờ tìm việc nhẹ",
    "em mới phẫu thuật xong cần việc ngồi",
    "thương tật 40% có nhà máy nào nhận không",
    "bất lực hai tay không nhấc được đồ nặng",
    "chồng em liệt nửa người, tìm việc giúp",
    "bà em bị đột co, xin việc nhẹ gần nhà",
    "không đi lại được, có việc làm tại nhà không",
]


@pytest.mark.parametrize("text", ESCALATION_TRIGGERS)
def test_escalation_keywords_trigger(text) -> None:
    """≥8 keyword families × diacritic variants all fire the gate."""
    assert trust_guards.is_escalation_message(text)


@pytest.mark.parametrize(
    "text",
    [
        "liệt kê các việc đang tuyển cho em",  # «liệt kê» is not «liệt»
        "lương bao nhiêu",
        "có việc nhẹ không anh",
        "cho em xin hotline",
    ],
)
def test_escalation_non_triggers(text) -> None:
    assert not trust_guards.is_escalation_message(text)


def test_escalation_reply_is_the_owner_template_with_hotline_and_no_questions() -> None:
    """Exactly one reply: the owner-approved verbatim handoff, zero questions."""
    reply = trust_guards.escalation_reply()
    assert reply == vfic_hotline_reply()
    assert VFIC_HOTLINE in reply  # "1800 7228"
    assert "1800 7228" in reply
    assert "?" not in reply and "？" not in reply and "không" not in reply
    # no advisory content: no project pitch, no salary, no screening question
    for banned in ("dự án", "lương", "khu vực", "độ tuổi", "kinh nghiệm"):
        assert banned not in reply.lower().replace("phụ trách", "")


# ── C.2 post-phone STOP ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dạ số điện thoại của em là 0912345678 ạ", True),
        ("0987654321", True),
        ("số em 0345.678.912 nhé", True),
        ("cho em xin số hotline", False),  # asking about a number ≠ giving one
        ("lương 8000000 được không", False),
        ("em ở Hải Phòng", False),
    ],
)
def test_phone_handover_detection(text, expected) -> None:
    assert trust_guards.is_phone_handover(text) is expected


def test_post_phone_stop_instruction_is_static_and_terminal() -> None:
    """The STOP instruction forbids new screening questions and pitches."""
    instruction = trust_guards.POST_PHONE_STOP_INSTRUCTION
    assert "KHÔNG hỏi thêm" in instruction
    assert "KHÔNG pitch" in instruction
    assert "KHÔNG kết thúc bằng một câu hỏi" in instruction


# ── D. identity honesty ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["bạn là bot à", "AI à bạn", "người thật không vậy", "la bot chu gi", "chatbot chu"],
)
def test_identity_question_detection(text) -> None:
    assert trust_guards.is_identity_question(text)
    assert trust_guards.identity_honesty_instruction(text) is not None


def test_identity_non_questions_get_no_instruction() -> None:
    for text in ["việc gì đang tuyển", "bot ơi cho em xin việc", "lương bao nhiêu"]:
        assert not trust_guards.is_identity_question(text)
        assert trust_guards.identity_honesty_instruction(text) is None


def test_persona_answers_identity_honestly() -> None:
    """The dodge rule is gone; the persona admits to being automated."""
    combined = IDENTITY_AND_OPENING_RULES + DEFAULT_PERSONA_BODY_MD
    assert "KHÔNG khẳng định cũng không phủ nhận" not in combined
    assert "TỰ ĐỘNG" in IDENTITY_AND_OPENING_RULES
    assert "không tự giới thiệu là bất kỳ thứ gì khác" not in DEFAULT_PERSONA_BODY_MD


# ── lane wiring through _agent_turn ─────────────────────────────────────────


class _FakeRetrieval:
    async def list_active_projects(self):
        return [FOUR_P, SEATED, UNKNOWN_PLANT]


def _state(text: str) -> BotRunState:
    return BotRunState(
        conversation_id="11111111-1111-1111-1111-111111111111",
        version_at_start=1,
        user_text=text,
    )


def _deps(agent) -> GraphDeps:
    return GraphDeps(
        db=None,  # type: ignore[arg-type] — the agent lane never touches it here
        agent=agent,  # type: ignore[arg-type]
        embedder=None,  # type: ignore[arg-type]
        zalo=None,
        conversation=None,  # type: ignore[arg-type]
        retrieval=_FakeRetrieval(),  # type: ignore[arg-type]
        lead=None,
    )


@pytest.fixture
def agent_lane(monkeypatch):
    """System prompt + answer cache stubbed so _agent_turn runs prompt-only."""

    async def _fake_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system", True

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_system_prompt)
    monkeypatch.setattr(lanes, "is_answer_cacheable", lambda **kwargs: False)
    return monkeypatch


async def test_agent_turn_escalation_short_circuits_before_any_model(agent_lane) -> None:
    """The injury disclosure is answered by the fixed reply, model never runs."""

    class _MustNotRun:
        async def agent(self, text, **kwargs):  # pragma: no cover - guard
            raise AssertionError("the escalation turn must not reach the model")

    reply = await lanes._agent_turn(
        _state("em bị gãy chân rồi, còn việc nào làm được không"),
        _deps(_MustNotRun()),
        "em bị gãy chân rồi, còn việc nào làm được không",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
    )
    assert reply == trust_guards.escalation_reply()
    assert "1800 7228" in reply


async def test_agent_turn_pins_seated_filter_args(agent_lane) -> None:
    agent = _ScriptedAgent(["Dạ có dự án ngồi lắp ráp phù hợp ạ."])
    text = "cho em xin việc ngồi, đứng lâu không được"
    await lanes._agent_turn(
        _state(text),
        _deps(agent),
        text,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
        decisions=TurnDecisions(intent="recommend", intent_confidence=0.9),
    )
    kwargs = agent.calls[0][1]
    assert kwargs["required_tool"] == "list_active_projects"
    assert kwargs["required_tool_arg_overrides"] == {
        "list_active_projects": {"work_posture": "seated"}
    }


async def test_agent_turn_appends_post_phone_stop(agent_lane) -> None:
    agent = _ScriptedAgent(["Dạ em đã nhận số của anh ạ."])
    text = "Dạ số điện thoại của em là 0912345678 ạ"
    await lanes._agent_turn(
        _state(text),
        _deps(agent),
        text,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
        decisions=TurnDecisions(intent="profile_update", intent_confidence=0.9),
    )
    contextual_text = agent.calls[0][0]
    assert trust_guards.POST_PHONE_STOP_INSTRUCTION in contextual_text


async def test_agent_turn_appends_identity_honesty(agent_lane) -> None:
    agent = _ScriptedAgent(["Dạ em là trợ lý tự động ạ."])
    text = "bạn là bot à hay người thật vậy"
    await lanes._agent_turn(
        _state(text),
        _deps(agent),
        text,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
        decisions=TurnDecisions(intent="general", intent_confidence=0.9),
    )
    contextual_text = agent.calls[0][0]
    assert trust_guards.IDENTITY_HONESTY_INSTRUCTION in contextual_text


async def test_agent_turn_no_stop_or_identity_on_ordinary_turn(agent_lane) -> None:
    agent = _ScriptedAgent(["Dạ bên em có dự án LG Display ạ."])
    text = "có dự án nào đang tuyển không"
    await lanes._agent_turn(
        _state(text),
        _deps(agent),
        text,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9),
    )
    contextual_text = agent.calls[0][0]
    assert trust_guards.POST_PHONE_STOP_INSTRUCTION not in contextual_text
    assert trust_guards.IDENTITY_HONESTY_INSTRUCTION not in contextual_text
