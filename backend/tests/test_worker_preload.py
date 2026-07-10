"""Regression coverage for the chatbot worker's fork-time import preload."""

from __future__ import annotations

import builtins


def test_preload_imports_includes_lazy_langchain_modules(monkeypatch):
    """Modules imported lazily by client construction must be warm before RQ forks."""
    from app.workers.chatbot_worker import preload_imports

    imported: list[str] = []
    original_import = builtins.__import__

    def recording_import(name, globals=None, locals=None, fromlist=(), level=0):
        imported.append(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", recording_import)

    preload_imports()

    assert "langchain_openai" in imported
    assert "langchain_core.messages" in imported
