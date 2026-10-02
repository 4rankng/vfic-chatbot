---
id: OPS-32
title: "Migration 0059: legacy YAML sources with a --- doc marker skip the category-drift sanity check"
severity: low
area: backend
labels: [backend, migrations, data-integrity, tech-debt]
effort: S
status: todo
column: TODO
opened: 2026-10-02
---

# OPS-32 — Migration 0059: legacy YAML sources with a `---` doc marker skip the category-drift sanity check

**Severity:** low · **Area:** backend · **Effort:** S · **Labels:** backend, migrations, data-integrity, tech-debt

**Trạng thái:** TODO

## Problem

`backend/alembic/versions/0059_category_markdown_source.py`, `_legacy_category_matches` (lines 347–348):

```python
if legacy_text.lstrip().startswith("---"):
    return
```

The module docstring promises the legacy-source sanity check "requires the old `source_yaml` text to parse as a YAML or JSON mapping whose top-level `category` matches the row — stored source/payload drift fails loudly instead of converting." The early return exists for the re-upgrade case (already-converted markdown front-matter starts with `---`). But a legacy YAML source that uses a YAML document-start marker **also** starts with `---`, so such rows skip the category-match check entirely.

## Impact

Corner case — requires both a `---` doc marker in the stored source AND drift between the stored category and the row's category — so low severity. But when it hits, a category revision converts silently to markdown under the wrong category instead of failing loudly as documented, i.e. silent miscategorization during the KB cutover.

## Suggested fix

Narrow the early return to the actual markdown front-matter signature (e.g. `---\nschema_version:`) instead of bare `---`, so genuine legacy YAML with a doc marker still goes through the drift check. A regression test with a drifted `---`-prefixed legacy source asserting `RuntimeError` would lock it in.

## Notes

Found 2026-10-02 in the read-only code audit. The migration's upgrade/downgrade is otherwise carefully designed (round-trip verification before rename, transactional rollback, documented lossy downgrade) — this is the only hole found. Related but distinct: OPS-28 (migration chain can't reach base 0006), TEST-13 (migration roundtrip coverage). No code was changed by the audit.

---

_Opened 2026-10-02 from the read-only code audit of /Volumes/LexarSSD/projects/chatbot. No code was changed by the audit; every claim is grounded in the file locations above._
