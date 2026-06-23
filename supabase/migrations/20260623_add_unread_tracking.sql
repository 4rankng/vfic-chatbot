-- 20260623_add_unread_tracking.sql
-- Unread message tracking for the VFIC inbox.
-- Applied live via Supabase MCP on 2026-06-23 (project vichwmxeptglqmzefsiq).
-- Mirrored here so supabase/migrations/ stays the apply-order source of truth.

-- 1) Denormalized unread counter on conversations (existing history stays "read" = 0).
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS unread_count integer NOT NULL DEFAULT 0;

-- 2) Trigger fn: bump unread_count on each INBOUND candidate message.
--    SECURITY DEFINER so the bot/service insert path increments regardless of role.
CREATE OR REPLACE FUNCTION public.vfic_inc_unread()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- inbound candidate = human message with no recruiter_id
  IF NEW.message->>'type' = 'human'
     AND (NEW.message->'data'->>'recruiter_id') IS NULL THEN
    UPDATE conversations
       SET unread_count = unread_count + 1
     WHERE zalo_chat_id = NEW.session_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS vfic_chat_histories_unread ON public.vfic_chat_histories;
CREATE TRIGGER vfic_chat_histories_unread
AFTER INSERT ON public.vfic_chat_histories
FOR EACH ROW
EXECUTE FUNCTION public.vfic_inc_unread();

-- 3) mark-as-read RPC: resets ONLY unread_count (must not bump updated_at —
--    see 20260623_fix_mark_read_skip_touch.sql for the suppression mechanism).
CREATE OR REPLACE FUNCTION public.vfic_mark_read(p_zalo_chat_id text)
RETURNS void
LANGUAGE sql
AS $$
  UPDATE conversations SET unread_count = 0 WHERE zalo_chat_id = p_zalo_chat_id;
$$;

-- 4) Batched latest-message-per-conversation peek (single call, not N+1).
CREATE OR REPLACE FUNCTION public.vfic_last_messages(p_session_ids text[])
RETURNS TABLE(session_id text, id integer, message jsonb)
LANGUAGE sql
AS $$
  SELECT DISTINCT ON (h.session_id)
         h.session_id::text AS session_id,
         h.id               AS id,
         h.message          AS message
    FROM public.vfic_chat_histories AS h
   WHERE h.session_id = ANY(p_session_ids)
   ORDER BY h.session_id, h.id DESC;
$$;
