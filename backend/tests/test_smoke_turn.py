"""Regression tests for the pre-flip deployment smoke wiring."""

from scripts.smoke_turn import _StubAgent, _StubZalo, _build_smoke_deps, _stub_embedder


def test_smoke_deps_skip_provider_client_construction(monkeypatch):
    from app.graph import factories
    from app.recruitment.infrastructure.service_adapters import ServiceLeadContextAdapter
    from app.services.conversation import ConversationService
    from app.services.retrieval import RetrievalRepository

    def _provider_clients_must_not_be_built(*_args, **_kwargs):
        raise AssertionError("deployment smoke must not construct provider clients")

    monkeypatch.setattr(factories, "_build_cached_clients", _provider_clients_must_not_be_built)
    db = object()

    deps = _build_smoke_deps(db)

    assert deps.db is db
    assert isinstance(deps.agent, _StubAgent)
    assert isinstance(deps.zalo, _StubZalo)
    assert deps.embedder is _stub_embedder
    assert isinstance(deps.conversation, ConversationService)
    assert isinstance(deps.retrieval, RetrievalRepository)
    assert isinstance(deps.lead, ServiceLeadContextAdapter)
