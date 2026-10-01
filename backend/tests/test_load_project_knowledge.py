"""The load_project_knowledge tool: scope resolution, rendering, budgets."""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.tools.knowledge import load_project_knowledge


class _FakeRetrieval:
    def __init__(self, rows, *, pid=None, active_ids=None):
        self.rows = rows
        self.pid = pid
        self.active_ids = active_ids
        self.slug_calls: list[tuple] = []
        self.load_calls: list[tuple] = []

    async def project_id_by_slug(self, slug, *, active_only=False):
        self.slug_calls.append((slug, active_only))
        return self.pid

    async def active_project_ids(self):
        return list(self.active_ids or [])

    async def load_category_knowledge(self, project_ids, category_key):
        self.load_calls.append((list(project_ids), category_key))
        return self.rows


def _row(slug="eva", key="contacts", text="SĐT: 0859256588"):
    return SimpleNamespace(slug=slug, category_key=key, text=text)


async def test_loads_one_project_one_category_with_headers():
    retrieval = _FakeRetrieval([_row()], pid="pid-1")

    result = await load_project_knowledge(retrieval, "eva", "contacts")

    assert retrieval.slug_calls == [("eva", True)]
    assert retrieval.load_calls == [(["pid-1"], "contacts")]
    assert "## Dự án: eva — mục: contacts" in result
    assert "0859256588" in result


async def test_unknown_project_reports_it_without_loading():
    retrieval = _FakeRetrieval([], pid=None)

    result = await load_project_knowledge(retrieval, "missing", "all")

    assert "Không tìm thấy dự án 'missing'" in result
    assert retrieval.load_calls == []


async def test_omitted_slug_loads_every_active_project_with_all_categories():
    retrieval = _FakeRetrieval([_row(slug="a"), _row(slug="b")], active_ids=["b", "a"])

    result = await load_project_knowledge(retrieval, None)

    assert retrieval.load_calls == [(["a", "b"], "all")]
    assert "## Dự án: a" in result
    assert "## Dự án: b" in result


async def test_empty_scope_says_so():
    retrieval = _FakeRetrieval([], pid="pid-1")

    result = await load_project_knowledge(retrieval, "eva")

    assert result == "Không có kiến thức đang hoạt động cho phạm vi này."


async def test_truncated_load_warns_and_asks_to_narrow():
    rows = [_row(slug=f"p{i}", text="x" * 13000) for i in range(6)]
    retrieval = _FakeRetrieval(rows, pid="pid-1")

    result = await load_project_knowledge(retrieval, "eva")

    assert "Lưu ý: dữ liệu đã bị cắt" in result
    assert "project_slug" in result


async def test_single_category_is_clipped_with_ellipsis():
    retrieval = _FakeRetrieval([_row(text="z" * 20000)], pid="pid-1")

    result = await load_project_knowledge(retrieval, "eva", "contacts")

    assert "…" in result
    assert len(result) < 13000
