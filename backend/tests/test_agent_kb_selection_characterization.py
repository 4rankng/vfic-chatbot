"""Characterize provider-scoped inbound Agent-selection authority.

Each adapter resolves one effective Persona from its explicit override or the
global default. Project selection remains an independent knowledge concern.
"""

from __future__ import annotations

from app.graph.context import resolve_persona


async def test_inbound_agent_selection_uses_active_global_persona() -> None:
    class _Retrieval:
        async def active_persona_body(self, provider: str | None = None) -> str | None:
            assert provider == "zalo_bot"
            return "Global agent body"

    assert await resolve_persona(_Retrieval(), provider="zalo_bot") == "Global agent body"


async def test_inbound_agent_selection_does_not_require_project_assignment() -> None:
    class _Retrieval:
        async def active_persona_body(self, provider: str | None = None) -> str | None:
            assert provider == "zalo_oa"
            return "Global agent body"

        async def active_projects_with_card(self) -> list[object]:
            raise AssertionError("Persona selection must not inspect Project defaults")

    assert await resolve_persona(_Retrieval(), provider="zalo_oa") == "Global agent body"
