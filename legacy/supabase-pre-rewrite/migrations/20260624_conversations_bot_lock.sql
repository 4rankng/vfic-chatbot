-- Per-chat bot-run mutex column.
-- Acquired by the VFIC Chatbot "Acquire Chat Lock" node at run start
-- (UPDATE conversations SET bot_locked_until = now()+30s
--   WHERE zalo_chat_id = $1 AND (bot_locked_until IS NULL OR bot_locked_until < now())
--   RETURNING id, mode, version) and cleared at the terminal Update Sent / Update Suppressed
-- nodes (bot_locked_until = NULL). A 30s TTL auto-releases runs that crash before reaching a
-- terminal. Used INSTEAD of pg_try_advisory_xact_lock because each n8n Postgres node auto-commits,
-- releasing a transaction-scoped advisory lock instantly (before the AI agent runs).
ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS bot_locked_until timestamptz;
