"""Characterize the existing inbound Agent-selection authority.

The standalone-KB migration must attach the KB selected for an inbound bot turn
to the active global Persona.  Project default Personas remain project guidance;
they do not currently select an Agent for a conversation.
"""

from __future__ import annotations

from app.graph.context import resolve_persona


async def test_inbound_agent_selection_uses_active_global_persona() -> None:
    class _Retrieval:
        async def active_persona_body(self) -> str | None:
            return "Global agent body"

    assert await resolve_persona(_Retrieval()) == "Global agent body"


async def test_inbound_agent_selection_does_not_require_project_assignment() -> None:
    class _Retrieval:
        async def active_persona_body(self) -> str | None:
            return "Global agent body"

        async def active_projects_with_card(self) -> list[object]:
            raise AssertionError("Persona selection must not inspect Project defaults")

    assert await resolve_persona(_Retrieval()) == "Global agent body"
