---
id: TEST-09
title: "Implementation is pinned by inspect.getsource substring assertions"
severity: medium
area: testing
labels: [testing]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# TEST-09 — Implementation is pinned by inspect.getsource substring assertions

**Severity:** medium · **Area:** testing · **Effort:** M · **Labels:** testing

**Trạng thái:** IN_PROGRESS

## Problem

Several backend tests read a module's source text and assert that specific tokens appear in it, which is the inverse of test value: they pass on a refactor that extracts behaviour into a helper and fail on a pure reformat. They also give false confidence that the KB-version join is correct without ever executing a query.

## Evidence

- `backend/tests/test_fact_repository.py:17-20` — `assert "Project.active_kb_version_id == StructuredFact.kb_version_id" in source`, repeated at `:55-57` and `:68-70`.
- `backend/tests/test_outbox.py:416-437` — `assert "raise RuntimeError" in src`, `assert "except Exception" in src`, `assert "return None" in src`; `:363` and `:391` parse the source AST to assert docstring-versus-code structure.
- `backend/tests/test_logging_credentials.py:31-32` and `backend/tests/test_outbound_dispatch_worker.py:25-31` — token pins (`silence_credential_bearing_transport_loggers`; `assert "app.services" not in source`).
- `backend/tests/test_domain_tools.py:182-185` — a forbidden-token scan of `domain_tools` source; this is a legitimate absence guard and is unlike the positive pins above.

## Impact

A semantic inversion (`==` → `!=`, or dropping the `IS NULL` legacy fallback) that keeps the asserted token present would still pass, so these tests stand in for behaviour without proving it.

## Suggested fix

Assert behaviour instead: seed a `Project` with `active_kb_version_id = v2` plus one `StructuredFact` at `v2` and one at `v3`, call `query_active_structured_facts` and assert exactly the `v2` row returns; call `create_pending_outbox` against a failing session and assert it raises, then `enqueue_outbox` and assert it returns `None`. `backend/tests/integration/conftest.py` already provides the disposable DB. Keep the pure absence guards (`test_domain_tools.py:182`, `test_architecture_boundaries.py`).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
