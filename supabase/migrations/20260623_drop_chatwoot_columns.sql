-- Drop unused Chatwoot-era columns and legacy takeover functions.
-- Context (2026-06-23): Chatwoot fully decommissioned; chat.tingting.vip is no
-- longer part of the VFIC stack. All three columns below were NULL across every
-- conversations row, and the two legacy functions took a chatwoot_agent_id with
-- zero callers. The ACTIVE recruiter-takeover path is vfic_take_over /
-- vfic_release (recruiter-uuid based); taken_over_at is KEPT (they set it).

DROP FUNCTION IF EXISTS public.take_over_conversation(text, bigint);
DROP FUNCTION IF EXISTS public.release_to_bot(text, bigint);

ALTER TABLE public.conversations
  DROP COLUMN IF EXISTS chatwoot_conversation_id,
  DROP COLUMN IF EXISTS chatwoot_contact_id,
  DROP COLUMN IF EXISTS assigned_chatwoot_agent_id;
