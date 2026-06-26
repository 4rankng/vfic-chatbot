-- 20260623_fix_mark_read_skip_touch.sql
-- Fix: vfic_mark_read must NOT bump conversations.updated_at, or the just-read
-- conversation re-sorts to the top of the (updated_at DESC) inbox.
-- Applied live via Supabase MCP on 2026-06-23 (project vichwmxeptglqmzefsiq).
--
-- Approach: add a transaction-local GUC opt-out to the shared touch_updated_at()
-- trigger fn (used by conversations_touch & profiles_touch). The guard is inert
-- unless explicitly set, so profiles and all normal updates are unaffected.

CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  -- Callers may opt out of the updated_at refresh (e.g. unread-count resets).
  IF current_setting('app.skip_touch_updated_at', true) = 'on' THEN
    RETURN NEW;
  END IF;
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- Recreate mark_read as plpgsql so it can set the GUC before the UPDATE.
CREATE OR REPLACE FUNCTION public.vfic_mark_read(p_zalo_chat_id text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM set_config('app.skip_touch_updated_at', 'on', true);  -- transaction-local
  UPDATE conversations
     SET unread_count = 0
   WHERE zalo_chat_id = p_zalo_chat_id;
END;
$$;
