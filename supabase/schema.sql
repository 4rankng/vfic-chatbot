-- =============================================================================
-- VFIC Chatbot — live Supabase `public` schema snapshot
-- =============================================================================
-- Source     : Supabase project "VFIC-Chatbot" (ref: vichwmxeptglqmzefsiq,
--              region ap-northeast-2, Postgres 17).
-- Snapshot   : 2026-06-23 (generated via pg_catalog queries — pg_dump / the
--              Supabase CLI are not installed in this environment).
-- Purpose    : Disaster recovery / service replication. Together with
--              `supabase/migrations/` (incremental apply-order source of truth)
--              and `n8n-workflows/`, this file lets anyone with the repo rebuild
--              the database even if the Supabase account is lost.
--
-- Relationship to migrations/ :
--   * `supabase/migrations/*.sql` is the authoritative, ordered change log.
--   * THIS file is a consolidated point-in-time snapshot for reference / DR.
--     Regenerate it after every live schema change (see CLAUDE.md "sync to local").
--
-- Restore order : extensions -> enums -> tables -> foreign keys -> indexes ->
--                  functions -> triggers -> RLS enable -> policies.
-- Note         : `profiles.id` references `auth.users(id)` (Supabase Auth), so
--                restore on a Supabase project where Auth is initialised.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS plpgsql;
CREATE EXTENSION IF NOT EXISTS pgcrypto;          -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;            -- embedding type (vector(3072))
CREATE EXTENSION IF NOT EXISTS pg_trgm;           -- trigram GIN indexes
CREATE EXTENSION IF NOT EXISTS unaccent;
-- pg_stat_statements, supabase_vault are Supabase-managed; available by default.

-- -----------------------------------------------------------------------------
-- Enums
-- -----------------------------------------------------------------------------
CREATE TYPE app_role   AS ENUM ('admin', 'recruiter');
CREATE TYPE conv_mode  AS ENUM ('bot', 'human');

-- =============================================================================
-- Tables
-- =============================================================================

CREATE TABLE public.projects (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug       text NOT NULL,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT projects_slug_key UNIQUE (slug)
);

CREATE TABLE public.companies (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  name       text NOT NULL,
  aliases    text[] NOT NULL DEFAULT '{}'::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT companies_project_id_name_key UNIQUE (project_id, name)
);

CREATE TABLE public.knowledge_sources (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id         uuid NOT NULL,
  company_id         uuid,
  source_name        text NOT NULL,
  source_type        text NOT NULL DEFAULT 'text'::text,
  document_type      text NOT NULL,
  source_ref         text,
  version            text NOT NULL DEFAULT ''::text,
  status             text NOT NULL DEFAULT 'published'::text,
  metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_sources_project_id_company_id_source_name_documen_key
    UNIQUE (project_id, company_id, source_name, document_type, version)
);

CREATE TABLE public.bus_routes (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          uuid NOT NULL,
  company_id          uuid NOT NULL,
  knowledge_source_id uuid,
  route_name          text NOT NULL,
  route_no            text,
  route_variant       text NOT NULL DEFAULT ''::text,
  shift               text NOT NULL,
  direction           text NOT NULL DEFAULT 'outbound'::text,
  area                text,
  mode                text,
  source_page         text NOT NULL DEFAULT ''::text,
  notes               text,
  metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  route_group_key     text NOT NULL,
  CONSTRAINT bus_routes_shift_check     CHECK (shift = ANY (ARRAY['day','night','admin'])),
  CONSTRAINT bus_routes_direction_check CHECK (direction = ANY (ARRAY['outbound','return'])),
  CONSTRAINT bus_routes_company_route_variant_shift_mode_key
    UNIQUE (company_id, route_name, route_variant, shift, direction, source_page, mode)
);

CREATE TABLE public.bus_stops (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  route_id      uuid NOT NULL,
  stop_order    integer NOT NULL,
  stop_name     text NOT NULL,
  stop_aliases  text[] NOT NULL DEFAULT '{}'::text[],
  scheduled_time time without time zone,
  raw_stop_text text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bus_stops_route_id_stop_order_key UNIQUE (route_id, stop_order)
);

CREATE TABLE public.bus_route_service_days (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          uuid NOT NULL,
  company_id          uuid NOT NULL,
  knowledge_source_id uuid,
  route_group_key     text NOT NULL,
  route_group_name    text NOT NULL,
  day_group           text NOT NULL,
  day_label           text NOT NULL,
  service_type        text NOT NULL,
  availability_code   text NOT NULL,
  metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bus_route_service_days_day_group_check
    CHECK (day_group = ANY (ARRAY['mon_thu','fri','sat','sun'])),
  CONSTRAINT bus_route_service_days_service_type_check
    CHECK (service_type = ANY (ARRAY['outbound_admin_and_day','return_night','return_admin','outbound_night','return_day'])),
  CONSTRAINT bus_route_service_days_availability_code_check
    CHECK (availability_code = ANY (ARRAY['A','M','X']))
);

CREATE TABLE public.conversations (
  id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  zalo_chat_id               text NOT NULL,
  mode                       conv_mode NOT NULL DEFAULT 'bot'::conv_mode,
  taken_over_at              timestamptz,
  version                    integer NOT NULL DEFAULT 1,
  last_inbound_at            timestamptz,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now(),
  assigned_recruiter_id      uuid,
  unread_count               integer NOT NULL DEFAULT 0,   -- added 2026-06-23 (unread tracking)
  CONSTRAINT conversations_zalo_chat_id_key UNIQUE (zalo_chat_id)
);

CREATE TABLE public.bot_runs (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id  uuid NOT NULL,
  started_at       timestamptz NOT NULL DEFAULT now(),
  ended_at         timestamptz,
  version_at_start integer NOT NULL,
  proposed_reply   text,
  outcome          text NOT NULL,
  CONSTRAINT bot_runs_outcome_check
    CHECK (outcome = ANY (ARRAY['sent','suppressed','error']))
);

CREATE TABLE public.bridge_event_log (
  event_id    text PRIMARY KEY,
  received_at timestamptz NOT NULL DEFAULT now(),
  payload     jsonb NOT NULL,
  processed   boolean NOT NULL DEFAULT false
);

CREATE TABLE public.documents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content       text,
  metadata      jsonb DEFAULT '{}'::jsonb,
  embedding     vector(3072),
  drive_file_id text GENERATED ALWAYS AS (NULLIF(metadata ->> 'file_id', '')) STORED,
  source        text GENERATED ALWAYS AS (NULLIF(metadata ->> 'source', '')) STORED
);

CREATE TABLE public.leads (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  zalo_id           text,
  name              text,
  phone             text,
  region            text,
  desired_job       text,
  lead_score        text,
  status            text NOT NULL DEFAULT 'new'::text,   -- LEGACY, superseded by lead_stage
  notes             text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  birth_year        integer,
  age               integer,
  living_area       text,
  address           text,
  gender            text,
  years_experience  text,
  latest_company    text,
  expected_salary   text,
  lead_stage        text,                                -- canonical recruitment stage
  CONSTRAINT leads_zalo_id_key      UNIQUE (zalo_id),
  CONSTRAINT leads_lead_score_check CHECK (lead_score = ANY (ARRAY['hot','warm','not_interested'])),
  CONSTRAINT leads_lead_stage_check CHECK (lead_stage = ANY (ARRAY['NEW','ENGAGED','QUALIFIED','APPLIED','HIRED','LOST','UNQUALIFIED']))
);
COMMENT ON TABLE public.leads IS 'VFIC recruitment chatbot leads collected via Zalo OA.';
COMMENT ON COLUMN public.leads.lead_stage IS 'Canonical recruitment stage (HLD §7.2). CRM reads/writes this.';
COMMENT ON COLUMN public.leads.status IS 'LEGACY — superseded by lead_stage. Not written by the bot; vestigial.';

CREATE TABLE public.memories (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content       text,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  embedding     vector(3072),
  created_at    timestamptz NOT NULL DEFAULT now(),
  chat_id       text GENERATED ALWAYS AS (NULLIF(COALESCE(metadata ->> 'chat_id', metadata ->> 'zalo_id'), '')) STORED,
  canonical_key text GENERATED ALWAYS AS (NULLIF(metadata ->> 'canonical_key', '')) STORED,
  zalo_id       text GENERATED ALWAYS AS (metadata ->> 'zalo_id') STORED,
  CONSTRAINT memories_metadata_has_chat_id CHECK ((metadata ? 'chat_id' OR metadata ? 'zalo_id')) NOT VALID
);
COMMENT ON TABLE public.memories IS 'Per-candidate semantic memory facts for VFIC chatbot (RAG). Filter by metadata.chat_id.';

CREATE TABLE public.profiles (
  id         uuid PRIMARY KEY,                          -- FK -> auth.users(id)
  email      text,
  full_name  text,
  role       app_role NOT NULL DEFAULT 'recruiter'::app_role,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.vfic_chat_histories (
  id         serial PRIMARY KEY,                        -- integer sequence
  session_id varchar(255) NOT NULL,                     -- joins conversations.zalo_chat_id
  message    jsonb NOT NULL
);

CREATE TABLE public.vfic_message_dedup (
  chat_id  text NOT NULL,
  msg_hash text NOT NULL,
  seen_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT vfic_message_dedup_pkey PRIMARY KEY (chat_id, msg_hash)
);

-- -----------------------------------------------------------------------------
-- Foreign keys (added after all tables exist)
-- -----------------------------------------------------------------------------
ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.companies
  ADD CONSTRAINT companies_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE public.knowledge_sources
  ADD CONSTRAINT knowledge_sources_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE,
  ADD CONSTRAINT knowledge_sources_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.bus_routes
  ADD CONSTRAINT bus_routes_project_id_fkey          FOREIGN KEY (project_id)          REFERENCES public.projects(id)          ON DELETE CASCADE,
  ADD CONSTRAINT bus_routes_company_id_fkey          FOREIGN KEY (company_id)          REFERENCES public.companies(id)         ON DELETE CASCADE,
  ADD CONSTRAINT bus_routes_knowledge_source_id_fkey FOREIGN KEY (knowledge_source_id) REFERENCES public.knowledge_sources(id) ON DELETE SET NULL;

ALTER TABLE public.bus_stops
  ADD CONSTRAINT bus_stops_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.bus_routes(id) ON DELETE CASCADE;

ALTER TABLE public.bus_route_service_days
  ADD CONSTRAINT bus_route_service_days_project_id_fkey          FOREIGN KEY (project_id)          REFERENCES public.projects(id)          ON DELETE CASCADE,
  ADD CONSTRAINT bus_route_service_days_company_id_fkey          FOREIGN KEY (company_id)          REFERENCES public.companies(id)         ON DELETE CASCADE,
  ADD CONSTRAINT bus_route_service_days_knowledge_source_id_fkey FOREIGN KEY (knowledge_source_id) REFERENCES public.knowledge_sources(id) ON DELETE CASCADE;

ALTER TABLE public.conversations
  ADD CONSTRAINT conversations_assigned_recruiter_id_fkey FOREIGN KEY (assigned_recruiter_id) REFERENCES public.profiles(id);

ALTER TABLE public.bot_runs
  ADD CONSTRAINT bot_runs_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;

-- -----------------------------------------------------------------------------
-- Indexes (standalone — PK/UNIQUE-constraint indexes are created above)
-- -----------------------------------------------------------------------------
CREATE INDEX bus_route_service_days_project_route_day_idx
  ON public.bus_route_service_days (project_id, route_group_key, day_group);
CREATE UNIQUE INDEX bus_route_service_days_company_route_day_service_key
  ON public.bus_route_service_days (company_id, route_group_key, day_group, service_type);

CREATE INDEX bus_routes_company_shift_idx ON public.bus_routes (company_id, shift, direction);
CREATE INDEX bus_routes_group_key_idx     ON public.bus_routes (company_id, route_group_key, shift, direction);
CREATE INDEX bus_routes_name_trgm_idx     ON public.bus_routes USING gin (route_name gin_trgm_ops);

CREATE INDEX bus_stops_route_idx      ON public.bus_stops (route_id, stop_order);
CREATE INDEX bus_stops_name_trgm_idx  ON public.bus_stops USING gin (stop_name gin_trgm_ops);

CREATE INDEX companies_project_idx ON public.companies (project_id);

CREATE INDEX conversations_assigned_recruiter_id_idx ON public.conversations (assigned_recruiter_id);

CREATE INDEX documents_drive_file_id_idx          ON public.documents (drive_file_id);
CREATE INDEX documents_source_drive_file_id_idx   ON public.documents (source, drive_file_id) WHERE (source IS NOT NULL AND drive_file_id IS NOT NULL);

CREATE INDEX leads_score_idx ON public.leads (lead_score) WHERE (lead_score IS NOT NULL);
CREATE INDEX leads_zalo_id_idx ON public.leads (zalo_id);

CREATE INDEX memories_chat_id_idx        ON public.memories (chat_id);
CREATE INDEX memories_metadata_idx       ON public.memories USING gin (metadata jsonb_path_ops);
CREATE INDEX memories_chat_metadata_idx  ON public.memories USING gin (metadata jsonb_path_ops);
CREATE UNIQUE INDEX memories_chat_canonical_unique_idx
  ON public.memories (chat_id, canonical_key) WHERE (chat_id IS NOT NULL AND canonical_key IS NOT NULL);
CREATE UNIQUE INDEX memories_chat_content_unique_idx
  ON public.memories (chat_id, md5(COALESCE(content, ''))) WHERE (chat_id IS NOT NULL AND content IS NOT NULL);

CREATE INDEX bot_runs_conv_idx ON public.bot_runs (conversation_id, started_at DESC);

-- =============================================================================
-- Functions (business logic only — excludes pgvector's C helpers)
-- =============================================================================

-- RLS membership helpers (SECURITY DEFINER, stable, fixed search_path)
CREATE OR REPLACE FUNCTION public.is_vfic_staff()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
    WHERE id = auth.uid() AND role IN ('admin', 'recruiter')
  );
$$;

CREATE OR REPLACE FUNCTION public.is_vfic_admin()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
    WHERE id = auth.uid() AND role = 'admin'
  );
$$;

-- Shared updated_at refresher. Supports a transaction-local opt-out
-- (app.skip_touch_updated_at = 'on') so callers like vfic_mark_read can update a
-- column without re-sorting updated_at-ordered lists.
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS trigger LANGUAGE plpgsql
AS $$
BEGIN
  IF current_setting('app.skip_touch_updated_at', true) = 'on' THEN
    RETURN NEW;
  END IF;
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- Unread tracking: bump conversations.unread_count on each inbound candidate
-- message. SECURITY DEFINER so the bot/service insert path increments regardless
-- of the inserter's role.
CREATE OR REPLACE FUNCTION public.vfic_inc_unread()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  -- inbound candidate = human message with no recruiter_id
  IF NEW.message->>'type' = 'human'
     AND (NEW.message->'data'->>'recruiter_id') IS NULL THEN
    UPDATE public.conversations
       SET unread_count = unread_count + 1
     WHERE zalo_chat_id = NEW.session_id;
  END IF;
  RETURN NEW;
END;
$$;

-- Reset a conversation's unread_count to 0 WITHOUT touching updated_at
-- (suppresses touch_updated_at via the GUC above) — opening a chat must not
-- re-sort the inbox.
CREATE OR REPLACE FUNCTION public.vfic_mark_read(p_zalo_chat_id text)
RETURNS void LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM set_config('app.skip_touch_updated_at', 'on', true);
  UPDATE public.conversations SET unread_count = 0 WHERE zalo_chat_id = p_zalo_chat_id;
END;
$$;

-- Batched "latest message per conversation" peek (single call, not N+1).
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

-- Takeover / release (recruiter handoff) — race-guarded via version + ownership.
CREATE OR REPLACE FUNCTION public.vfic_take_over(p_zalo_chat_id text, p_recruiter uuid)
RETURNS public.conversations LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $$
DECLARE v_row public.conversations;
BEGIN
  IF auth.uid() IS DISTINCT FROM p_recruiter THEN
    RAISE EXCEPTION 'takeover forbidden: recruiter must match auth user' USING errcode = '42501';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.profiles WHERE id = p_recruiter AND role IN ('admin','recruiter')) THEN
    RAISE EXCEPTION 'takeover forbidden: recruiter profile not allowed' USING errcode = '42501';
  END IF;
  INSERT INTO public.conversations (zalo_chat_id, mode, assigned_recruiter_id, taken_over_at, version)
  VALUES (p_zalo_chat_id, 'human', p_recruiter, now(), 2)
  ON CONFLICT (zalo_chat_id) DO UPDATE
    SET mode = 'human', assigned_recruiter_id = p_recruiter, taken_over_at = now(),
        version = public.conversations.version + 1, updated_at = now()
    WHERE public.conversations.assigned_recruiter_id IS NULL
       OR public.conversations.assigned_recruiter_id = p_recruiter
  RETURNING * INTO v_row;
  IF v_row.id IS NULL THEN
    RAISE EXCEPTION 'conversation already owned by another recruiter' USING errcode = '55006';
  END IF;
  RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.vfic_release(p_zalo_chat_id text, p_recruiter uuid)
RETURNS public.conversations LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $$
DECLARE v_row public.conversations;
BEGIN
  IF auth.uid() IS DISTINCT FROM p_recruiter THEN
    RAISE EXCEPTION 'release forbidden: recruiter must match auth user' USING errcode = '42501';
  END IF;
  UPDATE public.conversations
     SET mode = 'bot', assigned_recruiter_id = NULL, taken_over_at = NULL,
         version = public.conversations.version + 1, updated_at = now()
   WHERE zalo_chat_id = p_zalo_chat_id AND assigned_recruiter_id = p_recruiter
  RETURNING * INTO v_row;
  IF v_row.id IS NULL THEN
    RAISE EXCEPTION 'release forbidden: not the assigned recruiter' USING errcode = '42501';
  END IF;
  RETURN v_row;
END;
$$;

-- =============================================================================
-- Triggers
-- =============================================================================
CREATE TRIGGER conversations_touch
  BEFORE UPDATE ON public.conversations
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER profiles_touch
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER vfic_chat_histories_unread
  AFTER INSERT ON public.vfic_chat_histories
  FOR EACH ROW EXECUTE FUNCTION public.vfic_inc_unread();

-- =============================================================================
-- Row Level Security
-- =============================================================================
ALTER TABLE public.projects                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.companies                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_sources        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bus_routes               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bus_stops                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bus_route_service_days   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_runs                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_event_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vfic_chat_histories      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vfic_message_dedup       ENABLE ROW LEVEL SECURITY;

-- Policies
CREATE POLICY conversations_access
  ON public.conversations FOR ALL TO authenticated
  USING (public.is_vfic_staff()) WITH CHECK (public.is_vfic_staff());

CREATE POLICY leads_access
  ON public.leads FOR ALL TO authenticated
  USING (public.is_vfic_staff()) WITH CHECK (public.is_vfic_staff());

CREATE POLICY profiles_admin_write
  ON public.profiles FOR ALL TO authenticated
  USING (public.is_vfic_admin()) WITH CHECK (public.is_vfic_admin());

CREATE POLICY profiles_read
  ON public.profiles FOR SELECT TO authenticated
  USING (public.is_vfic_staff() OR (id = auth.uid()));

CREATE POLICY bot_runs_access
  ON public.bot_runs FOR ALL TO authenticated
  USING (EXISTS (SELECT 1 FROM public.profiles p
                 WHERE p.id = auth.uid() AND p.role = ANY (ARRAY['admin'::app_role, 'recruiter'::app_role])))
  WITH CHECK (EXISTS (SELECT 1 FROM public.profiles p
                      WHERE p.id = auth.uid() AND p.role = ANY (ARRAY['admin'::app_role, 'recruiter'::app_role])));

CREATE POLICY bridge_event_log_read
  ON public.bridge_event_log FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.profiles p
                 WHERE p.id = auth.uid() AND p.role = ANY (ARRAY['admin'::app_role, 'recruiter'::app_role])));

CREATE POLICY chat_histories_read
  ON public.vfic_chat_histories FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.profiles p
                 WHERE p.id = auth.uid() AND p.role = ANY (ARRAY['admin'::app_role, 'recruiter'::app_role])));
