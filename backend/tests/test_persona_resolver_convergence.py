"""One persona, every lane.

The agent lane and the direct-context lane used to read the persona through two
different paths — the agent lane via ``context.resolve_effective_persona`` (which
stripped the legacy privacy/refusal rules), the direct-context lane raw from
``PersonaRepository.active_persona_body``. A persona still carrying those rules made
the bot refuse/hedge on focused-project turns while the same persona answered
normally on agent turns: the exact drift this module exists to prevent.

Persona storage was removed on 2026-10-04, so the drift source is gone rather than
policed: both lanes read the same code constant, and neither can reach a second
copy. These tests hold that invariant, plus the two rules blocks that must ride
along with the persona on **both** lanes.
"""

from __future__ import annotations


from app.graph.context import build_system_prompt, resolve_effective_persona
from app.graph.direct_context import DirectContext, build_direct_system
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.prompts.vfic_persona import IDENTITY_AND_OPENING_RULES


class _Retrieval:
    """A repository that can only serve the project index, and serves none.

    The persona used to be read through this same port. It now has no persona
    method at all, which is the point: a lane that still tried to read one would
    raise ``AttributeError`` rather than silently diverge.
    """

    async def active_projects_with_card(self) -> list[object]:
        return []


async def test_resolver_is_the_committed_persona():
    assert resolve_effective_persona() == AGENT_SYSTEM_PROMPT


async def test_agent_lane_gets_the_persona_with_no_persona_read():
    """A repository with no persona method must not stop the turn."""
    prompt, _cache_hit = await build_system_prompt(_Retrieval(), provider="zalo_bot")

    assert prompt.startswith(AGENT_SYSTEM_PROMPT)


async def test_agent_lane_ends_with_the_identity_and_opening_rules():
    """The rules must be the last thing the model reads before it replies.

    They override the persona's own §1 and §5, so a persona body appended after
    them would quietly win the conflict.
    """
    prompt, _cache_hit = await build_system_prompt(_Retrieval(), provider="zalo_bot")

    assert IDENTITY_AND_OPENING_RULES in prompt
    assert prompt.index(IDENTITY_AND_OPENING_RULES) > prompt.index("### 1. Vai trò của tôi")


async def test_direct_context_lane_carries_the_same_rules():
    """The lane most likely to miss them: it builds its own prompt.

    ``build_direct_system`` receives none of the agent lane's rule blocks, so a
    rule added only to ``context.build_system_prompt`` silently does not apply to
    every focused-project turn.
    """
    direct = build_direct_system(
        DirectContext(
            knowledge_base_id="kb-1",
            persona_body=AGENT_SYSTEM_PROMPT,
            knowledge_text="KB TEXT",
        )
    )

    assert IDENTITY_AND_OPENING_RULES in direct
    assert direct.startswith(AGENT_SYSTEM_PROMPT)


async def test_the_rules_never_name_the_bot_an_ai_or_a_helper():
    """The regression this all exists for.

    Production opened every conversation with "Em là trợ lý của Nhân lực VFIC…"
    and asked for a phone number as the closing line of an opening message that
    had delivered nothing. Enforcement is prompt-only by decision, so the rule text
    is the only lever — these assertions are the ratchet.
    """
    for text in (AGENT_SYSTEM_PROMPT, IDENTITY_AND_OPENING_RULES):
        lowered = text.lower()
        assert "trợ lý ai" not in lowered
        assert "một trợ lý ai" not in lowered

    assert "Bạn là Dũng" in AGENT_SYSTEM_PROMPT
    assert "KHÔNG" in IDENTITY_AND_OPENING_RULES
    for marker in ("AI", "bot", "robot"):
        assert marker in IDENTITY_AND_OPENING_RULES, marker


def test_the_persona_port_no_longer_exists():
    """The DB persona seam is gone from the ports, not just unused."""
    from app.graph import ports as graph_ports
    from app.recruitment.application import ports as recruitment_ports

    assert not hasattr(recruitment_ports, "PersonaBodyResolver")
    assert not hasattr(recruitment_ports, "PersonaFollowupRulesResolver")
    assert not hasattr(recruitment_ports, "ProactiveStatePort")
    assert "PersonaBodyResolver" not in graph_ports.__all__


def test_manifest_persona_is_deliberately_composed_verbatim():
    """The manifest lane's persona is pinned installation content.

    ``build_policy_system_prompt`` composes ``policy.persona_body`` verbatim.
    Rewriting lines out of a checksummed manifest would change installation
    content behind its own checksum, so that lane is intentionally NOT run
    through the retrieval/composition path. Pinned so the result reads as a
    decision rather than an omission.
    """
    from app.graph.runtime_policy import build_policy_system_prompt
    from app.graph.types import ResolvedRuntimePolicy, ResolvedToolRegistry

    policy = ResolvedRuntimePolicy(
        revision_id="r1",
        fingerprint_checksum="c" * 64,
        pack_key="recruitment",
        capability_ids=frozenset(),
        terminology={},
        persona_body="PERSONA ĐÃ PIN",
        tool_registry=ResolvedToolRegistry(names=frozenset()),
    )

    prompt = build_policy_system_prompt(policy)

    assert prompt.startswith("PERSONA ĐÃ PIN")
    assert "RUNTIME AUTHORITY" in prompt
