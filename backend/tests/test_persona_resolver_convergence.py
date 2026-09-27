"""One persona resolver for every lane that builds a prompt.

The agent lane fetched the DB persona through ``context.resolve_persona`` (which
strips the legacy privacy/refusal rules) while the direct-context lane read
``PersonaRepository.active_persona_body`` raw. A persona still carrying those
rules therefore made the bot refuse/hedge on focused-project turns while the same
persona answered normally on agent turns — the exact drift the single-assembly
rule exists to prevent. ``context.resolve_effective_persona`` is now the one
owner, and both lanes go through it.
"""

from __future__ import annotations

from types import SimpleNamespace

# A persona carrying the legacy lines the strip exists to remove, plus one line
# that must survive.
_LEGACY_PERSONA = (
    "Bạn là trợ lý của Ting Ting.\n"
    "Không tiết lộ thông tin cá nhân của người dùng khác.\n"
    "Nói rõ đây là số cá nhân của ứng viên/người dùng khác.\n"
    "Trả lời bằng tiếng Việt, thân thiện.\n"
)
_STALE_MARKERS = ("thông tin cá nhân", "số cá nhân")
_VOICE_LINES = ("Bạn là trợ lý của Ting Ting.", "Trả lời bằng tiếng Việt, thân thiện.")


class _Retrieval:
    def __init__(self, body: str | None, *, raises: bool = False) -> None:
        self._body = body
        self._raises = raises

    async def active_persona_body(self, provider: str | None = None) -> str | None:  # noqa: ARG002
        if self._raises:
            raise RuntimeError("persona table unreachable")
        return self._body

    async def active_projects_with_card(self) -> list[object]:
        return []


async def test_resolver_strips_the_legacy_refusal_rules():
    from app.graph.context import resolve_effective_persona

    resolved = await resolve_effective_persona(_Retrieval(_LEGACY_PERSONA), provider="zalo_bot")

    for marker in _STALE_MARKERS:
        assert marker not in resolved
    # The persona's own voice survives; only the stale rules are removed.
    for line in _VOICE_LINES:
        assert line in resolved


async def test_resolver_falls_back_to_the_committed_persona():
    from app.graph.context import resolve_effective_persona
    from app.graph.prompts import AGENT_SYSTEM_PROMPT

    assert await resolve_effective_persona(_Retrieval(None)) == AGENT_SYSTEM_PROMPT
    assert await resolve_effective_persona(_Retrieval("   ")) == AGENT_SYSTEM_PROMPT
    # A persona read failure degrades to persona.md, never breaks the turn.
    assert (
        await resolve_effective_persona(_Retrieval(None, raises=True))
        == AGENT_SYSTEM_PROMPT
    )


async def test_build_system_prompt_assembles_from_the_shared_resolver(monkeypatch):
    """The agent lane's prompt is the resolver's output, appended to, verbatim.

    ``build_system_prompt`` used to strip the persona a second time after the
    resolver had already stripped it, so the invariant had no single owner.
    """
    from app.graph import context

    calls: list[str] = []
    resolved = "Persona đã resolve"

    async def _resolver(_retrieval, *, provider=None):
        calls.append(provider or "default")
        return resolved

    async def _uncached(factory, **_kwargs):
        # The real cache returns (prompt, cache_hit).
        return await factory(), False

    monkeypatch.setattr(context, "resolve_effective_persona", _resolver)
    monkeypatch.setattr(context, "cached_system_prompt", _uncached)

    prompt, cache_hit = await context.build_system_prompt(
        _Retrieval(_LEGACY_PERSONA), provider="zalo_bot"
    )

    assert calls == ["zalo_bot"]
    assert prompt.startswith(resolved)
    assert cache_hit is False


async def test_direct_context_lane_drops_the_same_stale_rules(monkeypatch):
    """Both lanes now build their persona the same way.

    The direct-context lane used to read ``active_persona_body`` raw, so a
    persona carrying the legacy refusal lines made the bot hedge on focused-project
    turns while the agent lane answered normally from the same persona.
    """
    from app.graph import adapters

    catalog = [
        SimpleNamespace(
            project_id="p1",
            kb_id=7,
            slug="lg-display",
            name="LG Display",
            aliases=(),
            mode="DIRECT_CONTEXT",
        )
    ]

    async def _catalog(_db):
        return catalog

    async def _fits(*_args, **_kwargs):
        return None

    class _Repo:
        def __init__(self, _db) -> None:
            pass

        async def active_persona_body(self, provider=None):  # noqa: ARG002
            return _LEGACY_PERSONA

    class _DB:
        def __init__(self) -> None:
            self.commits = 0

        async def commit(self) -> None:
            self.commits += 1

        async def scalar(self, _stmt):
            return SimpleNamespace(normalized_text="Nội dung dự án.")

    monkeypatch.setattr(adapters, "_load_direct_context_catalog", _catalog)
    monkeypatch.setattr("app.services.personas.repository.PersonaRepository", _Repo)
    monkeypatch.setattr(
        "app.services.knowledge_base_capacity.ensure_direct_context_fits", _fits
    )

    conversation = SimpleNamespace(
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        focused_project_id=None,
        project_context_state="EXPLORE",
    )

    turn_context = await adapters._DirectContextAdapter(_DB()).resolve(
        conversation, "LG Display đang tuyển gì?"
    )

    assert turn_context.state == "FOCUSED"
    assert turn_context.direct_context is not None
    persona = turn_context.direct_context.persona_body
    for marker in _STALE_MARKERS:
        assert marker not in persona
    for line in _VOICE_LINES:
        assert line in persona


def test_manifest_persona_is_deliberately_not_run_through_the_db_persona_strip():
    """The manifest lane's persona is pinned installation content, not a DB row.

    ``build_policy_system_prompt`` composes ``policy.persona_body`` verbatim.
    Stripping lines out of a signed manifest would change installation content
    behind its own checksum, so that lane is intentionally NOT routed through
    the DB-persona resolver. Pinned here so the audit result reads as a decision
    rather than an omission.
    """
    from app.graph.runtime_policy import build_policy_system_prompt
    from app.graph.types import ResolvedRuntimePolicy, ResolvedToolRegistry

    policy = ResolvedRuntimePolicy(
        revision_id="r1",
        fingerprint_checksum="c" * 64,
        pack_key="recruitment",
        capability_ids=frozenset(),
        terminology={},
        persona_body=_LEGACY_PERSONA,
        tool_registry=ResolvedToolRegistry(names=frozenset()),
    )

    prompt = build_policy_system_prompt(policy)

    assert prompt.startswith(_LEGACY_PERSONA)
    assert "RUNTIME AUTHORITY" in prompt
