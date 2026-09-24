"""Model-tier eligibility pins for the Jev-backed route policy.

The keyword router these tests originally pinned is gone; eligibility is a
pure function of the mapped strategy, so the pins are decisions-level now.
"""

from app.graph.ports import TurnDecisions
from app.graph.router import route_from_decisions, should_use_fast_model


def _route(**decision_kwargs) -> "object":
    return route_from_decisions("x", TurnDecisions(**decision_kwargs))


def test_small_talk_rides_the_agent_lane_and_is_not_fast_eligible() -> None:
    # The template fast lane was removed: every message reaches the LLM, so a
    # pleasantry uses the agent strategy and stays off the fast tier like the
    # other conversation-carrying routes.
    route = route_from_decisions(
        "cảm ơn bạn nhiều", TurnDecisions(pleasantry=True, intent_confidence=0.95)
    )
    assert route.strategy == "agent"
    assert not should_use_fast_model(route)


def test_safe_redirect_is_fast_eligible() -> None:
    assert not should_use_fast_model(_route(intent="faq_detail", intent_confidence=0.9))
    assert should_use_fast_model(_route(intent="out_of_scope", intent_confidence=0.9))


def test_knowledge_lookup_is_not_fast_eligible() -> None:
    # Detail questions (pay, shifts, dorm) are where a lead is won; the
    # reasoning model stays on this route deliberately.
    assert not should_use_fast_model(_route(intent="faq_detail", intent_confidence=0.9))
    assert not should_use_fast_model(_route(intent="contact", intent_confidence=0.9))


def test_conversion_routes_are_not_fast_eligible() -> None:
    assert not should_use_fast_model(_route(intent="recommend", intent_confidence=0.9))
    assert not should_use_fast_model(
        _route(intent="recommend", intent_confidence=0.94, vacancy_listing=True)
    )
    assert not should_use_fast_model(_route(intent="profile_update", intent_confidence=0.8))
    assert not should_use_fast_model(_route(intent="timetable", intent_confidence=0.9))
    assert not should_use_fast_model(_route(intent="general"))
