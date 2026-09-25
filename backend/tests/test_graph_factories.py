"""Tests for graph factories and GraphDeps wiring."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.graph.clients import MiniMaxAgent, OpenRouterEmbedder
from app.graph.adapters import (
    _DirectContextAdapter,
    _asks_to_explore,
    _is_general_or_comparative,
)
from app.graph.factories import (
    _build_fast_llm,
    aclose_client_cache,
    build_deps,
    make_minimax_llm_json,
    reset_client_cache,
)
from app.graph.types import GraphDeps
from app.recruitment.infrastructure.service_adapters import ServiceLeadContextAdapter


@pytest.mark.parametrize(
    "message",
    ["cho toi xem du an khac", "con viec khac khong", "quay lai tim viec"],
)
def test_explicit_exploration_request_releases_project_focus(message):
    assert _asks_to_explore(message) is True


def test_normal_project_followup_keeps_focus():
    assert _asks_to_explore("luong bao nhieu") is False


@pytest.mark.parametrize(
    "message",
    [
        "luong 20 trieu",
        # The reported inconsistent-salary message: a factory-agnostic threshold
        # hypothetical that was wrongly answered from LG Display's KB alone.
        "minh lam luong 20 trieu mot thang, neu luong nam cong thuong chia deu 12 thang co dc 20tr ko",
        "lam 15 trieu duoc khong",
        "luong cao nhat",
        "nha may nao luong cao nhat",
        "co bao nhieu nha may",
        "so sanh luong cac nha may",
        "viec lam nao gan nhat",
    ],
)
def test_general_or_comparative_question_is_detected(message):
    assert _is_general_or_comparative(message) is True


@pytest.mark.parametrize(
    "message",
    ["luong bao nhieu", "luong the nao", "ca lam viec gi", "co ktx khong", "ho so can gi"],
)
def test_focused_project_followup_is_not_general(message):
    # Ordinary project-scoped follow-ups must keep the established focus.
    assert _is_general_or_comparative(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "luong mong muon cua em la 20 trieu",
        "em dang nhan luong 20 trieu",
        "thu nhap hien tai cua em la 15 trieu",
    ],
)
def test_salary_profile_statement_is_not_general_comparison(message):
    assert _is_general_or_comparative(message) is False


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Doubles the two reads the direct-context lane makes per turn.

    ``execute`` serves the catalog query; ``scalar`` serves the targeted
    direct-file fetch for the selected project.
    """

    def __init__(self, rows, *, scalar_value=None):
        self._rows = rows
        self._scalar_value = scalar_value
        self.scalar_calls = 0

    async def execute(self, _stmt):
        return _FakeResult(self._rows)

    async def scalar(self, _stmt):
        self.scalar_calls += 1
        return self._scalar_value

    async def commit(self):
        return None


async def test_general_salary_question_not_locked_to_focused_project():
    """A factory-agnostic salary question must not be pinned to the focused
    project's KB, across two active projects, even when ``focused_project_id``
    is set and the message names no factory. Regression for the
    LG-Display-vs-Rorze 20M inconsistency."""
    from app.models.conversation import ConversationProjectState

    kb = SimpleNamespace(id="kb", mode=SimpleNamespace(value="rag"))
    proj_a = SimpleNamespace(id="a", slug="lg-display", name="LG Display", aliases=[])
    proj_b = SimpleNamespace(id="b", slug="rorze", name="Rorze", aliases=[])
    rows = [(proj_a, kb), (proj_b, kb)]
    conversation = SimpleNamespace(
        focused_project_id="a",
        project_context_state=ConversationProjectState.FOCUSED,
    )
    ctx = await _DirectContextAdapter(_FakeDB(rows)).resolve(
        conversation,
        "luong 20 trieu",
    )
    assert ctx.state == "EXPLORE"
    assert ctx.project_id is None
    assert ctx.project_slug is None
    # The focus is preserved for a subsequent project-specific question.
    assert conversation.focused_project_id == "a"


async def test_single_active_project_still_uses_focused_fallback():
    """With only one active project there is nothing to compare across, so a
    general question still falls back to the focused project (no behavior change
    for single-project installations)."""
    from app.models.conversation import ConversationProjectState

    proj_a = SimpleNamespace(id="a", slug="lg-display", name="LG Display", aliases=[])
    kb = SimpleNamespace(id="kb", mode=SimpleNamespace(value="rag"))
    rows = [(proj_a, kb)]
    conversation = SimpleNamespace(
        focused_project_id="a",
        project_context_state=ConversationProjectState.FOCUSED,
    )
    ctx = await _DirectContextAdapter(_FakeDB(rows)).resolve(
        conversation,
        "minh lam luong 20 trieu mot thang co dc 20tr ko",
    )
    # Falls through the general guard (len(entries) < 2) to the focused path.
    assert ctx.state == "FOCUSED"
    assert ctx.project_id == "a"


@pytest.mark.asyncio
async def test_direct_context_catalog_cache_hit_skips_database(monkeypatch):
    """A warm preamble cache serves the routing catalog; no DB query runs."""
    import app.core.cache as cache_mod
    from app.models.conversation import ConversationProjectState

    async def fake_cache_version(_namespace):
        return "7"

    async def fake_cache_get(_key):
        return [
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "slug": "lg-display",
                "name": "LG Display",
                "aliases": ["LG"],
                "kb_id": "22222222-2222-2222-2222-222222222222",
                "mode": "RAG",
            }
        ]

    async def fail_execute(_stmt):
        raise AssertionError("catalog query must not run on a cache hit")

    class _RefusingDB:
        async def execute(self, _stmt):
            await fail_execute(_stmt)

        async def commit(self):
            return None

    monkeypatch.setattr(cache_mod, "cache_version", fake_cache_version)
    monkeypatch.setattr(cache_mod, "cache_get_json", fake_cache_get)
    monkeypatch.setattr(cache_mod, "cache_set_json", fake_cache_version)
    adapter = _DirectContextAdapter(_RefusingDB())
    conversation = SimpleNamespace(
        focused_project_id=None,
        project_context_state=ConversationProjectState.EXPLORE,
    )
    ctx = await adapter.resolve(conversation, "xin chao LG Display")
    assert ctx.state == "FOCUSED"
    assert ctx.project_slug == "lg-display"
    assert ctx.project_id == "11111111-1111-1111-1111-111111111111"
    assert ctx.direct_context is None  # RAG mode: no direct text is fetched


@pytest.mark.asyncio
async def test_direct_context_catalog_cold_path_writes_cache(monkeypatch):
    """On a cache miss the catalog is read from the DB and written back once."""
    import app.core.cache as cache_mod
    from app.models.conversation import ConversationProjectState

    async def fake_cache_version(_namespace):
        return "3"

    captured: dict = {}

    async def fake_cache_get(_key):
        return None

    async def fake_cache_set(key, value, *, ttl_seconds):
        captured["key"] = key
        captured["value"] = value
        captured["ttl"] = ttl_seconds

    proj = SimpleNamespace(id="p1", slug="rorze", name="Rorze", aliases=["RZ"])
    kb = SimpleNamespace(id="kb1", mode=SimpleNamespace(value="RAG"))
    db = _FakeDB([(proj, kb)])
    monkeypatch.setattr(cache_mod, "cache_version", fake_cache_version)
    monkeypatch.setattr(cache_mod, "cache_get_json", fake_cache_get)
    monkeypatch.setattr(cache_mod, "cache_set_json", fake_cache_set)

    conversation = SimpleNamespace(
        focused_project_id=None,
        project_context_state=ConversationProjectState.EXPLORE,
    )
    ctx = await _DirectContextAdapter(db).resolve(conversation, "thong tin Rorze")
    assert ctx.state == "FOCUSED"
    assert captured["key"] == "preamble:direct_context_catalog:v3"
    assert captured["ttl"] == 600
    assert captured["value"] == [
        {
            "project_id": "p1",
            "slug": "rorze",
            "name": "Rorze",
            "aliases": ["RZ"],
            "kb_id": "kb1",
            "mode": "RAG",
        }
    ]


@pytest.mark.asyncio
async def test_focused_direct_context_turn_fetches_only_the_selected_file(monkeypatch):
    """Only the selected project's direct text is fetched, once, and the
    capacity guard runs on that pre-fetched file (no re-SELECT)."""
    import app.core.cache as cache_mod
    from app.models.conversation import ConversationProjectState
    from app.services import knowledge_base_capacity
    from app.services.personas.repository import PersonaRepository

    async def fake_cache_version(_namespace):
        return "1"

    async def fake_cache_get(_key):
        return None

    async def noop_cache_set(_key, _value, *, ttl_seconds):
        return None

    proj = SimpleNamespace(id="p1", slug="lg-display", name="LG Display", aliases=[])
    kb = SimpleNamespace(id="kb1", mode=SimpleNamespace(value="DIRECT_CONTEXT"))
    db = _FakeDB(
        [(proj, kb)],
        scalar_value=SimpleNamespace(normalized_text="KB TEXT"),
    )
    monkeypatch.setattr(cache_mod, "cache_version", fake_cache_version)
    monkeypatch.setattr(cache_mod, "cache_get_json", fake_cache_get)
    monkeypatch.setattr(cache_mod, "cache_set_json", noop_cache_set)

    async def fake_active_model(_db):
        return "minimax", "MiniMax-M2.7-highspeed", 1_024_000

    async def fake_persona_body(_self, _provider):
        return "PERSONA BODY"

    monkeypatch.setattr(
        knowledge_base_capacity, "_active_model_context", fake_active_model
    )
    monkeypatch.setattr(PersonaRepository, "active_persona_body", fake_persona_body)
    conversation = SimpleNamespace(
        focused_project_id=None,
        project_context_state=ConversationProjectState.EXPLORE,
    )
    ctx = await _DirectContextAdapter(db).resolve(conversation, "xin chao LG Display")
    assert ctx.state == "FOCUSED"
    assert ctx.knowledge_mode == "DIRECT_CONTEXT"
    assert ctx.direct_context is not None
    assert ctx.direct_context.knowledge_text == "KB TEXT"
    assert db.scalar_calls == 1


class _Settings:
    minimax_enable = True
    llm_default_provider = "minimax"
    minimax_api_key = "sk-mm-fake"
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_request_timeout = 60
    minimax_digest_timeout = 180
    openrouter_enable = False
    embedding_provider = "openrouter"
    embedding_dim = 3072
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_api_key = ""
    openrouter_agent_model = "deepseek/deepseek-v4-flash"
    openrouter_safety_model = "deepseek/deepseek-v4-flash"
    openrouter_digest_model = "deepseek/deepseek-v4-flash"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    openrouter_embedding_timeout = 60
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180
    max_llm_calls_per_turn = 5
    # IntegrationSettingsCipher reads one of these to decrypt stored secrets.
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    # ZaloRuntimeConfig fallback fields (env defaults when nothing is stored).
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
    zalo_oa_refresh_token = ""


class _SettingsWithBothProviders(_Settings):
    """Both generation providers are enabled; one is selected per client."""

    minimax_api_key = "sk-mm-fake"
    openrouter_enable = True
    openrouter_api_key = "sk-or-fake"
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_safety_model = "deepseek/deepseek-v3.2"
    openrouter_digest_model = "deepseek/deepseek-v3.2"
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180


@pytest.mark.asyncio
async def test_build_deps_wires_graphdeps(monkeypatch):
    class _FakeLLM:
        pass

    reset_client_cache()
    # The agent LLM is constructed inside client_cache, and every get_settings
    # import binding must see the key-bearing fake so no real credential or
    # lru_cache order decides the outcome.
    monkeypatch.setattr("app.graph.client_cache._chat_for_role", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.client_cache.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    deps = await build_deps(object())
    assert isinstance(deps, GraphDeps)
    assert isinstance(deps.agent, MiniMaxAgent)
    # safety client is no longer constructed (LLM judge removed); field is None.
    assert deps.safety is None
    assert isinstance(deps.embedder, OpenRouterEmbedder)
    assert deps.zalo is not None

    reset_client_cache()


@pytest.mark.asyncio
async def test_inline_oa_profile_lookup_has_no_refresh_and_uses_isolated_session(monkeypatch):
    class _FakeLLM:
        pass

    profile_sessions = []
    enrichment_calls = []

    class _ProfileSender:
        def __init__(self, **kwargs):
            # Kept on the instance so assertions target the sender actually
            # handed to enrichment — ZaloChannelSender legitimately constructs
            # its own refresh-bearing ZaloOASender when imported lazily.
            self.kwargs = kwargs

        async def get_user_detail(self, _user_id):
            return None

    class _ProfileService:
        def __init__(self, db, sender):
            self.db = db
            self.sender = sender

        async def enrich_oa_user(self, zalo_id, *, user_id):
            enrichment_calls.append((self.db, self.sender, zalo_id, user_id))
            return True

    profile_db = object()

    @asynccontextmanager
    async def session_factory():
        profile_sessions.append(profile_db)
        yield profile_db

    reset_client_cache()
    # Same binding discipline as test_build_deps_wires_graphdeps: the operative
    # _chat_for_role lives in client_cache, and every get_settings import sees
    # the fake instead of the lru_cached real settings.
    monkeypatch.setattr("app.graph.client_cache._chat_for_role", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.client_cache.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.services.zalo_oa_service.ZaloOASender", _ProfileSender)
    monkeypatch.setattr("app.services.profile_enrichment.ProfileEnrichmentService", _ProfileService)

    deps = await build_deps(object(), session_factory=session_factory)
    await deps.enrich_oa_profile("oa:user-1", "user-1")

    profile_sender = enrichment_calls[0][1]
    assert set(profile_sender.kwargs) == {"access_token"}
    assert profile_sender.kwargs["access_token"] is not None
    assert profile_sessions == [profile_db]
    assert enrichment_calls[0][0] is profile_db
    assert enrichment_calls[0][2:] == ("oa:user-1", "user-1")

    reset_client_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chat_id", "expected_profile_name"),
    [("oa:user-1", "Bé Gấu"), ("bot-user-1", None)],
)
async def test_lead_context_personalizes_only_oa_profiles(
    monkeypatch, chat_id, expected_profile_name
):
    profile_names = []

    class _Repo:
        def __init__(self, _db):
            pass

        async def by_zalo_id(self, _chat_id):
            return {"name": "Nguyễn Văn An" if not _chat_id.startswith("oa:") else None}

    class _ConversationService:
        def __init__(self, _db):
            pass

        async def get_by_zalo(self, _chat_id):
            return type(
                "_Conversation",
                (),
                {"contact": type("_Contact", (), {"display_name": "Bé Gấu"})()},
            )()

    def _profile_text(
        _lead,
        *,
        oa_profile_display_name=None,
        use_oa_profile_name=False,
        personalize=False,
    ):
        profile_names.append(oa_profile_display_name)
        assert use_oa_profile_name is False
        assert personalize is chat_id.startswith("oa:")
        return "profile"

    monkeypatch.setattr("app.services.lead.repository.LeadRepository", _Repo)
    monkeypatch.setattr("app.services.conversation.ConversationService", _ConversationService)
    monkeypatch.setattr("app.services.lead.lead_profile_text", _profile_text)
    monkeypatch.setattr(
        "app.services.lead.probing.lead_collection_question",
        lambda **_kwargs: "phone question",
    )

    profile, question = await ServiceLeadContextAdapter(object()).context(
        chat_id, "hello", []
    )

    assert profile == "profile"
    if chat_id.startswith("oa:"):
        assert "Bé Gấu" in question
    else:
        assert question == "phone question"
    assert profile_names == [expected_profile_name]


@pytest.mark.asyncio
async def test_lead_context_uses_clear_oa_profile_name_without_reasking(monkeypatch):
    profile_leads = []
    profile_kwargs = []
    collection_leads = []
    upserts = []

    class _Repo:
        def __init__(self, _db):
            pass

        async def by_zalo_id(self, _chat_id):
            return {"name": None, "zalo_id": "oa:user-1"}

        async def upsert(self, lead):
            upserts.append(lead)
            return 1

    class _ConversationService:
        def __init__(self, _db):
            pass

        async def get_by_zalo(self, _chat_id):
            return type(
                "_Conversation",
                (),
                {"contact": type("_Contact", (), {"display_name": "Nguyễn Hùng"})()},
            )()

    class _Db:
        async def commit(self):
            return None

    def _profile_text(lead, **kwargs):
        profile_leads.append(lead)
        profile_kwargs.append(kwargs)
        return "profile"

    def _collection_question(**kwargs):
        collection_leads.append(kwargs["lead"])
        return "phone question"

    monkeypatch.setattr("app.services.lead.repository.LeadRepository", _Repo)
    monkeypatch.setattr("app.services.conversation.ConversationService", _ConversationService)
    monkeypatch.setattr("app.services.lead.lead_profile_text", _profile_text)
    monkeypatch.setattr(
        "app.services.lead.probing.lead_collection_question",
        _collection_question,
    )

    profile, question = await ServiceLeadContextAdapter(_Db()).context(
        "oa:user-1", "CTY ở đâu vậy", []
    )

    assert profile == "profile"
    assert question == "phone question"
    # The accepted profile name was persisted, so the prompt reads the merged
    # lead (known name) instead of the unconfirmed display-label block.
    assert profile_leads == [{"zalo_id": "oa:user-1", "name": "Nguyễn Hùng"}]
    assert profile_kwargs == [
        {
            "oa_profile_display_name": "Nguyễn Hùng",
            "use_oa_profile_name": False,
            "personalize": True,
        }
    ]
    assert collection_leads == [{"zalo_id": "oa:user-1", "name": "Nguyễn Hùng"}]
    assert upserts and upserts[0]["name"] == "Nguyễn Hùng"


def test_minimax_json_missing_key_names_minimax(monkeypatch):
    class _NoKeySettings(_Settings):
        minimax_api_key = ""

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _NoKeySettings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        make_minimax_llm_json()


def test_active_provider_no_xor_when_both_enabled(monkeypatch):
    """_active_llm_provider returns the configured default when both are enabled."""
    from app.graph.clients import _active_llm_provider

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithBothProviders())
    assert _active_llm_provider() == "minimax"


def test_active_provider_openrouter_default_when_both_enabled(monkeypatch):
    """_active_llm_provider can use OpenRouter as primary when both are enabled."""
    from app.graph.clients import _active_llm_provider

    class _OpenRouterDefault(_SettingsWithBothProviders):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    assert _active_llm_provider() == "openrouter"


def test_active_provider_openrouter_only(monkeypatch):
    """_active_llm_provider returns 'openrouter' when only OpenRouter is enabled."""
    from app.graph.clients import _active_llm_provider

    s = _SettingsWithBothProviders()
    s.minimax_enable = False
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: s)
    assert _active_llm_provider() == "openrouter"


def test_chat_for_role_returns_plain_client_default_minimax(monkeypatch):
    """_chat_for_role returns a plain ChatOpenAI for the default provider (no wrapper)."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithBothProviders())
    llm = _chat_for_role("agent", temperature=0.3)
    # A plain ChatOpenAI is used for the selected provider.
    assert isinstance(llm, ChatOpenAI)


def test_chat_for_role_returns_openrouter_client_when_default(monkeypatch):
    """_chat_for_role honors LLM_DEFAULT_PROVIDER=openrouter at the client level."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    class _OpenRouterDefault(_SettingsWithBothProviders):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    llm = _chat_for_role("agent", temperature=0.3)
    assert isinstance(llm, ChatOpenAI)
    # The model name reflects the openrouter config, proving provider selection.
    assert "deepseek" in llm.model_name


def test_openrouter_fast_tier_requests_returned_reasoning(monkeypatch):
    captured: dict = {}
    fast_client = object()

    def fake_openrouter_chat(model, **kwargs):
        captured.update({"model": model, **kwargs})
        return fast_client

    monkeypatch.setattr(
        "app.graph.factories.get_settings",
        lambda: SimpleNamespace(
            minimax_fast_model="",
            openrouter_fast_model="deepseek/deepseek-v4-flash",
            openrouter_request_timeout=60,
        ),
    )
    monkeypatch.setattr("app.graph.factories._openrouter_chat", fake_openrouter_chat)

    result = _build_fast_llm(
        minimax_config=SimpleNamespace(enabled=False, api_key="", default_provider="openrouter"),
        openrouter_config=SimpleNamespace(enabled=True, api_key="test-key"),
    )

    assert result is fast_client
    assert captured["capture_reasoning"] is True


# ── US-001: LLM client cache ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_client_cache_isolates_failures_and_closes_embedder_pool():
    from app.graph import client_cache

    closed: list[str] = []

    class _RootClient:
        def __init__(self, name: str, *, fails: bool = False) -> None:
            self.name = name
            self.fails = fails

        async def close(self) -> None:
            closed.append(self.name)
            if self.fails:
                raise RuntimeError("close failed")

    class _EmbedAio:
        async def aclose(self) -> None:
            closed.append("embedder")

    failing_client = SimpleNamespace(root_async_client=_RootClient("agent", fails=True))
    fast_client = SimpleNamespace(root_async_client=_RootClient("fast"))
    embedder = SimpleNamespace(_client=SimpleNamespace(aio=_EmbedAio()))
    client_cache._client_cache["test"] = client_cache._CachedClients(
        agent_llm=failing_client,
        fast_llm=fast_client,
        embedder=embedder,
    )

    await aclose_client_cache()

    assert closed == ["agent", "fast", "embedder"]
    assert client_cache._client_cache == {}


@pytest.mark.asyncio
async def test_build_deps_caches_llm_clients_across_turns(monkeypatch):
    """Two build_deps calls with the same settings version build clients ONCE.

    This is the core latency fix: the expensive ChatOpenAI construction (and
    the langchain_openai import it triggers on a cold process) happens once per
    worker process, not once per turn. We count constructions by counting
    _chat_for_role invocations.
    """
    reset_client_cache()

    class _FakeLLM:
        pass

    call_count = {"n": 0}

    def _counting_chat_for_role(*args, **kwargs):
        call_count["n"] += 1
        return _FakeLLM()

    monkeypatch.setattr("app.graph.client_cache._chat_for_role", _counting_chat_for_role)
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.client_cache.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    await build_deps(object())
    first_count = call_count["n"]
    assert first_count == 1  # agent only (safety client removed)

    deps2 = await build_deps(object())
    # No additional _chat_for_role calls — clients came from the cache.
    assert call_count["n"] == first_count
    assert isinstance(deps2.agent, MiniMaxAgent)

    reset_client_cache()


@pytest.mark.asyncio
async def test_build_deps_cache_invalidates_on_version_change(monkeypatch):
    """A bumped minimax/openrouter cache version rebuilds the LLM clients.

    The fake cache_version namespaces its responses, so this catches a
    regression where the cache key omits a namespace. The LLM client cache key
    covers only minimax + openrouter — the two providers whose settings drive
    agent_llm / embedder / fast_llm construction.
    """
    from app.graph import client_cache, factories

    reset_client_cache()

    class _FakeLLM:
        pass

    monkeypatch.setattr("app.graph.client_cache._chat_for_role", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.client_cache.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    versions = {
        "integration_minimax": "1",
        "integration_openrouter": "1",
        "integration_custom_llm": "1",
        "integration_zalo": "1",
    }

    async def _fake_cache_version(namespace):
        return versions[namespace]

    monkeypatch.setattr("app.core.cache.cache_version", _fake_cache_version)

    await factories.build_deps(object())
    assert len(client_cache._client_cache) == 1
    assert "mm:1|or:1|fb:1" in client_cache._client_cache

    # A minimax bump (admin edited the agent model / key) invalidates.
    versions["integration_minimax"] = "2"
    await factories.build_deps(object())
    assert "mm:2|or:1|fb:1" in client_cache._client_cache

    reset_client_cache()


@pytest.mark.asyncio
async def test_build_deps_cache_survives_zalo_version_change(monkeypatch):
    """A zalo-only version bump (OA token refresh) must NOT rebuild LLM clients.

    Regression guard: the cache key previously included the zalo namespace, so
    every OA token refresh invalidated the expensive LLM client cache (5-7s
    rebuild of agent_llm + embedder + fast_llm) even though none of those
    clients depend on Zalo config. ZaloConfig feeds only the per-turn
    ZaloChannelSender, which is resolved fresh in build_deps — so a rotated
    token still takes effect on the next turn without touching this cache.
    """
    from app.graph import client_cache, factories

    reset_client_cache()

    builds = {"n": 0}

    class _FakeLLM:
        pass

    def _counting_chat_for_role(*args, **kwargs):
        builds["n"] += 1
        return _FakeLLM()

    monkeypatch.setattr("app.graph.client_cache._chat_for_role", _counting_chat_for_role)
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.client_cache.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    versions = {
        "integration_minimax": "1",
        "integration_openrouter": "1",
        "integration_custom_llm": "1",
        "integration_zalo": "1",
    }

    async def _fake_cache_version(namespace):
        return versions[namespace]

    monkeypatch.setattr("app.core.cache.cache_version", _fake_cache_version)

    await factories.build_deps(object())
    assert "mm:1|or:1|fb:1" in client_cache._client_cache
    assert builds["n"] == 1  # agent built once

    # Only the zalo namespace bumps (OA token refresh). The cache MUST NOT rebuild.
    versions["integration_zalo"] = "2"
    await factories.build_deps(object())
    assert "mm:1|or:1|fb:1" in client_cache._client_cache  # same key, still cached
    assert builds["n"] == 1  # no additional LLM client construction

    reset_client_cache()


# ── US-002: sequential resolve_* calls (session safety) ─────────────────────


@pytest.mark.asyncio
async def test_build_deps_resolves_settings_without_concurrent_session_access(monkeypatch):
    """resolve_minimax / resolve_openrouter run sequentially, never overlapping.

    Both resolves share the same ``db`` AsyncSession. SQLAlchemy async sessions
    do NOT permit concurrent operations on one connection — running them in
    asyncio.gather causes ``InvalidRequestError: This session is provisioning a
    new connection; concurrent operations are not permitted`` (a 100% crash on
    cold cache, observed in production). This test is the regression guard: it
    wraps both resolves to track peak in-flight count, and asserts peak never
    exceeds 1 (no overlap).

    The cost is ~3ms extra on the cold path (once per process restart); warm
    turns are Redis-only and unaffected.
    """
    from app.services.integration_settings import IntegrationSettingsService

    in_flight = {"n": 0, "peak": 0}

    def _make_tracker(orig):
        async def _tracked(self):  # noqa: ANN001
            in_flight["n"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
            await asyncio.sleep(0)  # yield — if siblings were concurrent they'd overlap here
            try:
                return await orig(self)
            finally:
                in_flight["n"] -= 1

        return _tracked

    monkeypatch.setattr(
        IntegrationSettingsService,
        "resolve_minimax",
        _make_tracker(IntegrationSettingsService.resolve_minimax),
    )
    monkeypatch.setattr(
        IntegrationSettingsService,
        "resolve_openrouter",
        _make_tracker(IntegrationSettingsService.resolve_openrouter),
    )
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    reset_client_cache()
    await build_deps(object())

    assert in_flight["peak"] == 1, (
        f"resolve_* calls overlapped (peak={in_flight['peak']}); "
        "expected sequential — concurrent session access crashes SQLAlchemy"
    )
    assert in_flight["n"] == 0  # both fully completed
    reset_client_cache()
