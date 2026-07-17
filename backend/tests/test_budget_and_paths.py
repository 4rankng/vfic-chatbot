"""Tests for the TurnBudget guard + four bounded paths (Tech-Lead Directive §2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.chatbot.budget import BudgetExhausted, CallKind, TurnBudget
from app.services.chatbot.paths import (
    path_a_structured,
    path_b_faq,
    path_c_retrieval,
    path_d_clarify,
)


# ─── TurnBudget ──────────────────────────────────────────────────────────────


def test_budget_allows_one_call_per_kind():
    b = TurnBudget()
    b.record_call(CallKind.GENERATION)
    assert b.remaining(CallKind.GENERATION) == 0


def test_budget_raises_on_second_call_same_kind():
    b = TurnBudget()
    b.record_call(CallKind.EMBEDDING)
    with pytest.raises(BudgetExhausted, match="embedding"):
        b.record_call(CallKind.EMBEDDING)


def test_budget_kinds_are_independent():
    b = TurnBudget()
    b.record_call(CallKind.GENERATION)
    b.record_call(CallKind.EMBEDDING)
    b.record_call(CallKind.RERANK)
    b.record_call(CallKind.ROUTING)
    assert b.remaining(CallKind.GENERATION) == 0
    assert b.remaining(CallKind.EMBEDDING) == 0


def test_budget_default_caps_match_directive():
    b = TurnBudget()
    assert b.caps[CallKind.ROUTING] == 1
    assert b.caps[CallKind.EMBEDDING] == 1
    assert b.caps[CallKind.RERANK] == 1
    assert b.caps[CallKind.GENERATION] == 1


# ─── Path A: structured-data ─────────────────────────────────────────────────


async def test_path_a_benefit_lookup_with_data(monkeypatch):
    fake_result = MagicMock(
        found=True,
        data=[{"name": "Phụ cấp", "value": 500000, "currency": "VND", "cadence": "monthly", "eligibility": None}],
    )
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_benefits", AsyncMock(return_value=fake_result)
    )
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.format_benefits",
        MagicMock(return_value="formatted benefits"),
    )
    budget = TurnBudget()
    outcome = await path_a_structured(
        intent="benefit_lookup", entities={"job_id": "j1"}, db=MagicMock(), budget=budget
    )
    assert outcome.outcome_label == "structured"
    assert outcome.reply == "formatted benefits"
    assert not outcome.cannot_handle
    assert budget.used == {}  # zero LLM calls


async def test_path_a_signals_cannot_handle_on_miss(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_benefits",
        AsyncMock(return_value=MagicMock(found=False, data=[])),
    )
    outcome = await path_a_structured(
        intent="benefit_lookup", entities={"job_id": "j1"}, db=MagicMock(), budget=TurnBudget()
    )
    assert outcome.cannot_handle is True


async def test_path_a_unsupported_intent_signals_cannot_handle():
    outcome = await path_a_structured(
        intent="recommend", entities={}, db=MagicMock(), budget=TurnBudget()
    )
    assert outcome.cannot_handle is True


# ─── Path B: FAQ ─────────────────────────────────────────────────────────────


async def test_path_b_returns_curated_answer(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_faq_entry",
        AsyncMock(return_value=MagicMock(found=True, data=[{"answer": "CCCD + SYLL", "resolution_type": "static_answer"}])),
    )
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.format_faq", MagicMock(return_value="CCCD + SYLL")
    )
    outcome = await path_b_faq(
        user_text="hồ sơ gì",
        normalized_question="hồ sơ gì",
        db=MagicMock(),
        budget=TurnBudget(),
    )
    assert outcome.reply == "CCCD + SYLL"
    assert outcome.outcome_label == "faq_cache"


async def test_path_b_misses_fall_through(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_faq_entry",
        AsyncMock(return_value=MagicMock(found=False, data=[])),
    )
    outcome = await path_b_faq(
        user_text="?", normalized_question="?", db=MagicMock(), budget=TurnBudget()
    )
    assert outcome.cannot_handle is True


async def test_path_b_dynamic_faq_signals_cannot_handle(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_faq_entry",
        AsyncMock(return_value=MagicMock(found=True, data=[{"answer": "", "resolution_type": "tool", "tool_name": "get_next_bus"}])),
    )
    outcome = await path_b_faq(
        user_text="cho mình xin thêm thông tin",
        normalized_question="cho mình xin thêm thông tin",
        db=MagicMock(),
        budget=TurnBudget(),
    )
    assert outcome.cannot_handle is True
    assert outcome.outcome_label == "faq_dynamic"


async def test_path_b_volatile_question_bypasses_static_faq():
    db = MagicMock()
    outcome = await path_b_faq(
        user_text="Lương vị trí này bao nhiêu?",
        normalized_question="lương vị trí này bao nhiêu",
        db=db,
        budget=TurnBudget(),
    )
    assert outcome.cannot_handle is True
    assert outcome.outcome_label == "faq_volatile"
    db.execute.assert_not_called()


async def test_path_b_allows_curated_vacancy_evidence_when_the_caller_scopes_it(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.get_faq_entry",
        AsyncMock(return_value=MagicMock(found=True, data=[{"answer": "LG đang tuyển", "resolution_type": "static_answer"}])),
    )
    monkeypatch.setattr(
        "app.services.knowledge.tools.domain_tools.format_faq", MagicMock(return_value="LG đang tuyển")
    )

    outcome = await path_b_faq(
        user_text="LG đang tuyển không?",
        normalized_question="lg dang tuyen khong",
        db=MagicMock(),
        budget=TurnBudget(),
        published_vacancy_evidence=True,
    )

    assert outcome.reply == "LG đang tuyển"
    assert outcome.outcome_label == "faq_cache"


async def test_path_b_keeps_contact_and_transport_facts_out_of_vacancy_faq_scope():
    for user_text in ("Hotline là số nào?", "LG có xe đưa đón không?"):
        db = MagicMock()
        outcome = await path_b_faq(
            user_text=user_text,
            normalized_question=user_text.casefold(),
            db=db,
            budget=TurnBudget(),
            published_vacancy_evidence=True,
        )

        assert outcome.cannot_handle is True
        assert outcome.outcome_label == "faq_volatile"
        db.execute.assert_not_called()


# ─── Path C: retrieval ───────────────────────────────────────────────────────


async def test_path_c_records_one_generation_call():
    async def fake_agent():
        return "agent reply"

    budget = TurnBudget()
    outcome = await path_c_retrieval(user_text="?", agent_turn_fn=fake_agent, budget=budget)
    assert outcome.reply == "agent reply"
    assert budget.used.get(CallKind.GENERATION, 0) == 1


async def test_path_c_budget_exhaustion_returns_fallback():
    budget = TurnBudget()
    budget.record_call(CallKind.GENERATION)  # pre-exhaust

    async def fake_agent():
        return "should not reach"

    outcome = await path_c_retrieval(user_text="?", agent_turn_fn=fake_agent, budget=budget)
    assert outcome.outcome_label == "budget_exhausted"
    assert "đợi" in outcome.reply.lower() or "vui lòng" in outcome.reply.lower()


# ─── Path D: clarification ───────────────────────────────────────────────────


async def test_path_d_renders_clarification_with_two_intents():
    outcome = await path_d_clarify(
        top_intents=["benefit_lookup", "working_hours_lookup"], budget=TurnBudget()
    )
    assert "phúc lợi" in outcome.reply
    assert "giờ làm việc" in outcome.reply
    assert outcome.outcome_label == "clarify"


async def test_path_d_single_intent_signals_cannot_handle():
    outcome = await path_d_clarify(top_intents=["benefit_lookup"], budget=TurnBudget())
    assert outcome.cannot_handle is True
