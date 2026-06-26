# legacy/ — decommissioned code (history only)

Nothing under `legacy/` runs in production. Kept for traceability / disaster
recovery history.

- `supabase-pre-rewrite/` — the pre-2026-06-26 Supabase data layer. See its
  README. Replaced by `backend/alembic/`.
- `migrate_from_supabase.py` — one-shot migration script that ported live
  Supabase rows into the new self-hosted schema at cutover. Already executed;
  kept for traceability. (Originally lived at `backend/scripts/`.)

For the legacy **n8n** workflows, see `../n8n-workflows/` (still read by
backend tests/scripts as prompt ground truth — not moved here).
