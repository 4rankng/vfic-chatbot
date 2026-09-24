"""VFIC greenfield baseline schema (self-hosted Postgres 16 + pgvector).

Replaces the Supabase schema. Clean tables with real FKs, typed messages with
created_at, BOT/HUMAN/CLOSED modes, HNSW vector indexes, own users+JWT (no RLS,
no Supabase Auth). The bus-timetable knowledge graph + SQL functions and the
match_memories/match_documents RAG functions are ported VERBATIM from the live
Supabase catalog so chatbot behaviour is identical. A `documents` VIEW shims the
old documents table over knowledge_documents/knowledge_chunks so the verbatim
bus-rebuild function works unmodified.

Sync note (why this is NOT mirrored to ../supabase/migrations): this directory is
the schema for the NEW self-hosted Postgres that REPLACES Supabase at the big-bang
cutover (US-011). The repo-root CLAUDE.md "sync live→local" rule governs changes
to the LIVE Supabase project — and the cutover makes no live Supabase schema
change (Supabase is decommissioned, not migrated in place). Mirroring this DDL
into supabase/migrations would pollute the legacy live-Supabase change log with a
schema for a different database. backend/alembic IS the source of truth here.

Revision ID: 0001
Revises:
Create Date: 2026-06-26
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen Alembic's own version-tracking column. Alembic creates
    # alembic_version.version_num as VARCHAR(32); this project's descriptive
    # revision IDs exceed that and abort `alembic upgrade head` on the
    # version-row UPDATE. The version table exists by the time the first
    # migration runs, and widening a VARCHAR is metadata-only in Postgres
    # (no rewrite, no long lock). Idempotent; guarded for safety.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);
        EXCEPTION WHEN undefined_table THEN NULL;
        END $$;
        """
    )

    # -------------------------------------------------------------------------
    # 1. Schemas + extensions
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS extensions;
        CREATE EXTENSION IF NOT EXISTS plpgsql;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;
        """
    )

    # -------------------------------------------------------------------------
    # 2. Enums (values the bot/CRM depend on are preserved)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TYPE app_role            AS ENUM ('admin','recruiter');
        CREATE TYPE conversation_mode   AS ENUM ('BOT','HUMAN','CLOSED');
        CREATE TYPE conversation_status AS ENUM ('OPEN','CLOSED');
        CREATE TYPE message_sender      AS ENUM ('WORKER','BOT','RECRUITER','SYSTEM');
        CREATE TYPE delivery_status     AS ENUM ('PENDING','SENT','FAILED','SUPPRESSED');
        CREATE TYPE bot_run_outcome     AS ENUM ('SENT','SUPPRESSED','ERROR');
        CREATE TYPE lead_score          AS ENUM ('hot','warm','not_interested');
        CREATE TYPE lead_stage          AS ENUM ('NEW','ENGAGED','QUALIFIED','APPLIED','HIRED','LOST','UNQUALIFIED');
        CREATE TYPE job_status          AS ENUM ('DRAFT','ACTIVE','PAUSED','FULL','EXPIRED','ARCHIVED');
        CREATE TYPE knowledge_status    AS ENUM ('UPLOADED','PROCESSING','PUBLISHED','ARCHIVED','FAILED');
        CREATE TYPE followup_status     AS ENUM ('PENDING','DONE','SKIPPED','CANCELLED');
        """
    )

    # -------------------------------------------------------------------------
    # 3. Tables
    # -------------------------------------------------------------------------
    # --- auth (replaces Supabase profiles + auth.users) ---
    op.execute(
        """
        CREATE TABLE public.users (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email         text NOT NULL,
          password_hash text NOT NULL,
          full_name     text,
          role          app_role NOT NULL DEFAULT 'recruiter',
          disabled      boolean NOT NULL DEFAULT false,
          created_at    timestamptz NOT NULL DEFAULT now(),
          updated_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX users_email_key ON public.users (lower(email));
        """
    )

    # --- bus-timetable knowledge graph (VERBATIM from live schema) ---
    op.execute(
        """
        CREATE TABLE public.projects (
          id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          slug       text NOT NULL,
          name       text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX projects_slug_key ON public.projects (slug);

        CREATE TABLE public.companies (
          id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
          name       text NOT NULL,
          aliases    text[] NOT NULL DEFAULT '{}'::text[],
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX companies_project_id_name_key ON public.companies (project_id, name);
        CREATE INDEX companies_project_idx ON public.companies (project_id);

        CREATE TABLE public.knowledge_sources (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id    uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
          company_id    uuid REFERENCES public.companies(id) ON DELETE CASCADE,
          source_name   text NOT NULL,
          source_type   text NOT NULL DEFAULT 'text',
          document_type text NOT NULL,
          source_ref    text,
          version       text NOT NULL DEFAULT '',
          status        text NOT NULL DEFAULT 'published',
          metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at    timestamptz NOT NULL DEFAULT now(),
          updated_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX knowledge_sources_unique_key
          ON public.knowledge_sources (project_id, company_id, source_name, document_type, version);

        CREATE TABLE public.bus_routes (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id          uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
          company_id          uuid NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
          knowledge_source_id uuid REFERENCES public.knowledge_sources(id) ON DELETE SET NULL,
          route_name          text NOT NULL,
          route_no            text,
          route_variant       text NOT NULL DEFAULT '',
          shift               text NOT NULL CHECK (shift IN ('day','night','admin')),
          direction           text NOT NULL DEFAULT 'outbound' CHECK (direction IN ('outbound','return')),
          area                text,
          mode                text,
          source_page         text NOT NULL DEFAULT '',
          notes               text,
          metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at          timestamptz NOT NULL DEFAULT now(),
          route_group_key     text NOT NULL,
          CONSTRAINT bus_routes_company_route_variant_shift_mode_key
            UNIQUE (company_id, route_name, route_variant, shift, direction, source_page, mode)
        );

        CREATE TABLE public.bus_stops (
          id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          route_id       uuid NOT NULL REFERENCES public.bus_routes(id) ON DELETE CASCADE,
          stop_order     integer NOT NULL,
          stop_name      text NOT NULL,
          stop_aliases   text[] NOT NULL DEFAULT '{}'::text[],
          scheduled_time time WITHOUT TIME ZONE,
          raw_stop_text  text,
          created_at     timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX bus_stops_route_id_stop_order_key ON public.bus_stops (route_id, stop_order);

        CREATE TABLE public.bus_route_service_days (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id          uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
          company_id          uuid NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
          knowledge_source_id uuid REFERENCES public.knowledge_sources(id) ON DELETE CASCADE,
          route_group_key     text NOT NULL,
          route_group_name    text NOT NULL,
          day_group           text NOT NULL CHECK (day_group IN ('mon_thu','fri','sat','sun')),
          day_label           text NOT NULL,
          service_type        text NOT NULL CHECK (service_type IN ('outbound_admin_and_day','return_night','return_admin','outbound_night','return_day')),
          availability_code   text NOT NULL CHECK (availability_code IN ('A','M','X')),
          metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX bus_route_service_days_company_route_day_service_key
          ON public.bus_route_service_days (company_id, route_group_key, day_group, service_type);
        CREATE INDEX bus_route_service_days_project_route_day_idx
          ON public.bus_route_service_days (project_id, route_group_key, day_group);
        """
    )

    # --- conversation core ---
    op.execute(
        """
        CREATE TABLE public.conversations (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          zalo_chat_id          text NOT NULL,
          mode                  conversation_mode NOT NULL DEFAULT 'BOT',
          status                conversation_status NOT NULL DEFAULT 'OPEN',
          needs_human           boolean NOT NULL DEFAULT false,
          version               integer NOT NULL DEFAULT 1,
          taken_over_at         timestamptz,
          assigned_recruiter_id uuid REFERENCES public.users(id) ON DELETE SET NULL,
          unread_count          integer NOT NULL DEFAULT 0,
          bot_locked_until      timestamptz,
          last_inbound_at       timestamptz,
          last_outbound_at      timestamptz,
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT conversations_zalo_chat_id_key UNIQUE (zalo_chat_id)
        );
        CREATE INDEX conversations_assigned_recruiter_id_idx
          ON public.conversations (assigned_recruiter_id) WHERE assigned_recruiter_id IS NOT NULL;
        CREATE INDEX conversations_mode_status_idx
          ON public.conversations (mode, status, updated_at DESC);

        CREATE TABLE public.bot_runs (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          conversation_id  uuid NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
          started_at       timestamptz NOT NULL DEFAULT now(),
          ended_at         timestamptz,
          version_at_start integer NOT NULL,
          proposed_reply   text,
          outcome          bot_run_outcome NOT NULL
        );
        CREATE INDEX bot_runs_conv_idx ON public.bot_runs (conversation_id, started_at DESC);

        CREATE TABLE public.messages (
          id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          conversation_id uuid NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
          sender          message_sender NOT NULL,
          body            text NOT NULL,
          recruiter_id    uuid REFERENCES public.users(id) ON DELETE SET NULL,
          bot_run_id      bigint REFERENCES public.bot_runs(id) ON DELETE SET NULL,
          delivery_status delivery_status NOT NULL DEFAULT 'SENT',
          zalo_message_id text,
          external_error  text,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX messages_conv_created_idx ON public.messages (conversation_id, created_at DESC, id DESC);
        CREATE INDEX messages_zalo_msg_id_idx ON public.messages (zalo_message_id) WHERE zalo_message_id IS NOT NULL;

        CREATE TABLE public.outbound_messages (
          id                          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          conversation_id             uuid NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
          body                        text NOT NULL,
          expected_conversation_version integer NOT NULL,
          attempt                     integer NOT NULL DEFAULT 0,
          max_attempts                integer NOT NULL DEFAULT 3,
          next_retry_at               timestamptz,
          last_error                  text,
          delivered_message_id        bigint REFERENCES public.messages(id),
          status                      delivery_status NOT NULL DEFAULT 'PENDING',
          created_at                  timestamptz NOT NULL DEFAULT now(),
          updated_at                  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX outbound_pending_idx
          ON public.outbound_messages (status, next_retry_at) WHERE status IN ('PENDING','FAILED');

        CREATE TABLE public.message_dedup (
          chat_id  text NOT NULL,
          msg_hash text NOT NULL,
          seen_at  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (chat_id, msg_hash)
        );
        """
    )

    # --- knowledge (replaces documents) ---
    op.execute(
        """
        CREATE TABLE public.knowledge_documents (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          drive_file_id text UNIQUE,
          file_name     text NOT NULL,
          source        text NOT NULL DEFAULT 'google_drive',
          version       text,
          status        knowledge_status NOT NULL DEFAULT 'UPLOADED',
          raw_text      text,
          metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at    timestamptz NOT NULL DEFAULT now(),
          updated_at    timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE public.knowledge_chunks (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid NOT NULL REFERENCES public.knowledge_documents(id) ON DELETE CASCADE,
          chunk_index integer NOT NULL,
          content     text NOT NULL,
          embedding   vector(3072),
          metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT knowledge_chunks_document_id_chunk_index_key UNIQUE (document_id, chunk_index)
        );
        CREATE INDEX knowledge_chunks_doc_idx ON public.knowledge_chunks (document_id, chunk_index);
        """
    )

    # --- jobs ---
    op.execute(
        """
        CREATE TABLE public.jobs (
          id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id         uuid NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
          title              text NOT NULL,
          factory_name       text,
          province           text,
          district           text,
          address            text,
          salary_min         integer,
          salary_max         integer,
          shift              text,
          gender_requirement text,
          age_min            integer,
          age_max            integer,
          experience_required text,
          accommodation_support boolean,
          meal_support       boolean,
          transport_support  boolean,
          vacancy_count      integer,
          status             job_status NOT NULL DEFAULT 'ACTIVE',
          description        text,
          requirements       text,
          benefits           text,
          source_document_id uuid REFERENCES public.knowledge_documents(id) ON DELETE SET NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX jobs_status_company_idx ON public.jobs (status, company_id);
        """
    )

    # --- leads (zalo_id now a real FK to conversations.zalo_chat_id) ---
    op.execute(
        """
        CREATE TABLE public.leads (
          id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          zalo_id               text,
          name                  text,
          phone                 text,
          birth_year            integer CHECK (birth_year BETWEEN 1900 AND extract(year FROM now())::int),
          age                   integer CHECK (age BETWEEN 15 AND 80),
          living_area           text,
          address               text,
          gender                text,
          region                text,
          desired_job           text,
          years_experience      text,
          latest_company        text,
          expected_salary       text,
          lead_score            lead_score,
          lead_stage            lead_stage NOT NULL DEFAULT 'NEW',
          intent_score          numeric(3,2) CHECK (intent_score IS NULL OR intent_score BETWEEN 0 AND 1),
          qualification_reasons text[] NOT NULL DEFAULT '{}',
          next_action_at        timestamptz,
          assigned_recruiter_id uuid REFERENCES public.users(id) ON DELETE SET NULL,
          notes                 text,
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT leads_zalo_id_key UNIQUE (zalo_id),
          CONSTRAINT leads_zalo_id_fkey FOREIGN KEY (zalo_id) REFERENCES public.conversations(zalo_chat_id) ON DELETE CASCADE
        );
        CREATE INDEX leads_stage_idx ON public.leads (lead_stage);
        CREATE INDEX leads_score_idx ON public.leads (lead_score) WHERE lead_score IS NOT NULL;
        CREATE INDEX leads_recruiter_idx ON public.leads (assigned_recruiter_id) WHERE assigned_recruiter_id IS NOT NULL;

        CREATE TABLE public.lead_events (
          id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          lead_id    bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
          event_type text NOT NULL,
          payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
          actor_id   uuid REFERENCES public.users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX lead_events_lead_idx ON public.lead_events (lead_id, created_at DESC);

        CREATE TABLE public.follow_up_tasks (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          lead_id     bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
          due_at      timestamptz NOT NULL,
          note        text,
          status      followup_status NOT NULL DEFAULT 'PENDING',
          created_by  uuid REFERENCES public.users(id) ON DELETE SET NULL,
          completed_at timestamptz,
          created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX followups_pending_idx ON public.follow_up_tasks (status, due_at) WHERE status = 'PENDING';
        """
    )

    # --- memories (faithful to live: metadata jsonb + generated cols; match_memories verbatim) ---
    op.execute(
        """
        CREATE TABLE public.memories (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          content       text,
          metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
          embedding     vector(3072),
          created_at    timestamptz NOT NULL DEFAULT now(),
          chat_id       text GENERATED ALWAYS AS (NULLIF(COALESCE(metadata->>'chat_id', metadata->>'zalo_id'), '')) STORED,
          canonical_key text GENERATED ALWAYS AS (NULLIF(metadata->>'canonical_key', '')) STORED,
          zalo_id       text GENERATED ALWAYS AS (metadata->>'zalo_id') STORED,
          CONSTRAINT memories_metadata_has_chat_id CHECK (metadata ? 'chat_id' OR metadata ? 'zalo_id')
        );
        CREATE INDEX memories_chat_id_idx ON public.memories (chat_id);
        CREATE INDEX memories_metadata_idx ON public.memories USING gin (metadata jsonb_path_ops);
        CREATE UNIQUE INDEX memories_chat_canonical_unique_idx
          ON public.memories (chat_id, canonical_key) WHERE chat_id IS NOT NULL AND canonical_key IS NOT NULL;
        CREATE UNIQUE INDEX memories_chat_content_unique_idx
          ON public.memories (chat_id, md5(COALESCE(content,''))) WHERE chat_id IS NOT NULL AND content IS NOT NULL;
        """
    )

    # --- audit + settings ---
    op.execute(
        """
        CREATE TABLE public.audit_events (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          actor_id    uuid REFERENCES public.users(id) ON DELETE SET NULL,
          action      text NOT NULL,
          target_type text,
          target_id   text,
          payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_actor_idx ON public.audit_events (actor_id, created_at DESC);
        CREATE INDEX audit_action_idx ON public.audit_events (action, created_at DESC);

        CREATE TABLE public.system_settings (
          key        text PRIMARY KEY,
          value      jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # -------------------------------------------------------------------------
    # 4. `documents` VIEW — compat shim so the verbatim bus-rebuild fn works.
    #    Phase-3 parity = 1 chunk per document (whole content).
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW public.documents AS
        SELECT
          kd.id            AS id,
          kc.content       AS content,
          kd.metadata      AS metadata,
          kc.embedding     AS embedding,
          kd.drive_file_id AS drive_file_id,
          kd.source        AS source
        FROM public.knowledge_documents kd
        JOIN public.knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status NOT IN ('ARCHIVED', 'FAILED');
        """
    )

    # -------------------------------------------------------------------------
    # 5. Remaining indexes (bus trigram fuzzy search)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX bus_routes_company_shift_idx ON public.bus_routes (company_id, shift, direction);
        CREATE INDEX bus_routes_group_key_idx     ON public.bus_routes (company_id, route_group_key, shift, direction);
        CREATE INDEX bus_routes_name_trgm_idx     ON public.bus_routes USING gin (route_name gin_trgm_ops);
        CREATE INDEX bus_stops_route_idx          ON public.bus_stops (route_id, stop_order);
        CREATE INDEX bus_stops_name_trgm_idx      ON public.bus_stops USING gin (stop_name gin_trgm_ops);
        """
    )

    # -------------------------------------------------------------------------
    # 6. Vector indexes — NONE (brute-force, same as the live Supabase DB)
    # -------------------------------------------------------------------------
    # pgvector HNSW and IVFFlat indexes are capped at 2000 dimensions; our Gemini
    # embeddings are 3072-dim, so NEITHER index type can be built (verified:
    # "column cannot have more than 2000 dimensions for hnsw index"). The live
    # system also has no vector indexes and relies on exact brute-force `<=>`
    # scans inside match_memories / match_documents — fine for this small corpus
    # (<100 docs/memories). At scale, options: (a) re-embed at a lower
    # output_dimensionality so HNSW <=2000 applies, or (b) a binary-quantized
    # generated column + HNSW(bit_hamming_ops) with re-ranking. Deferred.

    # -------------------------------------------------------------------------
    # 7. Functions — ported VERBATIM from live Supabase catalog.
    # -------------------------------------------------------------------------
    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.normalize_search_text(value text)
        RETURNS text
        LANGUAGE sql
        STABLE
        SET search_path TO 'public', 'extensions'
        AS $function$
          select lower(regexp_replace(extensions.unaccent(coalesce(value, '')), '[^a-zA-Z0-9]+', ' ', 'g'));
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION public.normalize_bus_route_key(p_name text)
        RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        SET search_path = public, extensions
        AS $$
        declare
          v text := public.normalize_search_text(coalesce(p_name, ''));
        begin
          v := regexp_replace(v, '\s+', ' ', 'g');
          v := btrim(v);

          if v = '' then
            return '';
          end if;

          if v in ('ktx cd bac bo', 'ktx cao dang bac bo') then
            return 'ktx cao dang bac bo';
          end if;

          if v = 'cau rao 1' then
            return 'cau rao';
          end if;

          if v = 'tl cau dam' then
            return 'tien lang cau dam';
          end if;

          if v = 'tl hung thang' then
            return 'tien lang hung thang';
          end if;

          return v;
        end;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.match_memories(query_embedding vector, match_count integer DEFAULT 10, filter jsonb DEFAULT '{}'::jsonb)
        RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
        LANGUAGE sql
        STABLE
        SET search_path TO 'public', 'extensions'
        AS $function$
          select
            memories.id,
            memories.content,
            memories.metadata,
            1 - (memories.embedding <=> query_embedding) as similarity
          from public.memories
          where memories.embedding is not null
            and memories.metadata @> filter
          order by memories.embedding <=> query_embedding
          limit match_count;
        $function$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.match_documents(query_embedding vector, match_count integer DEFAULT 10, filter jsonb DEFAULT '{}'::jsonb)
        RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
        LANGUAGE plpgsql
        SET search_path TO 'public', 'extensions'
        AS $function$
        begin
          return query
          select
            documents.id,
            documents.content,
            documents.metadata,
            1 - (documents.embedding <=> query_embedding) as similarity
          from public.documents
          where documents.embedding is not null
            and documents.metadata @> filter
          order by documents.embedding <=> query_embedding
          limit match_count;
        end;
        $function$;
        """
    )

    # --- bus-timetable rebuild + search: VERBATIM from supabase/migrations/20260620_bus_timetable_weekday_support.sql ---
    op.execute(_REBUILD_BUS_TIMETABLE_SQL)
    op.execute(_SEARCH_BUS_TIMETABLE_SQL)

    # -------------------------------------------------------------------------
    # 8. Triggers
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TRIGGER conversations_touch
          BEFORE UPDATE ON public.conversations
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

        CREATE TRIGGER users_touch
          BEFORE UPDATE ON public.users
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )


def downgrade() -> None:
    # downgrade: FORWARD_ONLY — the greenfield baseline has no inverse; recover
    # by restoring the dump or dropping and replaying migrations.
    raise RuntimeError(
        "0001_baseline is the greenfield baseline and is not reversible. "
        "Drop & recreate the database, or add a forward-only corrective migration."
    )


# Verbatim bodies for the two large bus functions. Kept as module constants so the
# upgrade() flow stays readable. Source: supabase/migrations/20260620_bus_timetable_weekday_support.sql
_REBUILD_BUS_TIMETABLE_SQL = r"""
CREATE OR REPLACE FUNCTION public.rebuild_bus_timetable_from_documents(
  p_project_slug text default 'vfic',
  p_company_name text default 'LG Display',
  p_source_name text default 'LGDisplay.txt',
  p_source_ref text default null,
  p_version text default '',
  p_source_type text default 'text'
)
returns table(routes_rebuilt integer, stops_rebuilt integer)
language plpgsql
set search_path = public, extensions
as $function$
declare
  v_project_id uuid;
  v_company_id uuid;
  v_source_id uuid;
  rec record;
  line_text text;
  stop_part text;
  stop_idx integer;
  header_match text[];
  route_match text[];
  day_match text[];
  weekly_route_match text[];
  flag text;
  flag_match text[];
  current_route_no text := null;
  current_route_name text := null;
  current_area text := null;
  current_mode text := null;
  current_page text := null;
  current_shift text := null;
  current_section text := null;
  current_weekly_route_name text := null;
  current_weekly_route_key text := null;
  pending_notes text := null;
  current_admin_block text := null;
  v_route_id uuid;
  stop_name_value text;
  stop_time_value time;
  v_day_group text;
begin
  insert into public.projects (slug, name)
  values (p_project_slug, upper(p_project_slug))
  on conflict (slug) do update set name = excluded.name
  returning id into v_project_id;

  insert into public.companies (project_id, name, aliases)
  values (
    v_project_id,
    p_company_name,
    case
      when lower(p_company_name) = lower('LG Display')
        then array['LGD', 'LG Display Việt Nam', 'LG Display Vietnam']
      else array[p_company_name]
    end
  )
  on conflict (project_id, name) do update
    set aliases = excluded.aliases
  returning id into v_company_id;

  insert into public.knowledge_sources (
    project_id,
    company_id,
    source_name,
    source_type,
    document_type,
    source_ref,
    version,
    status,
    metadata
  )
  values (
    v_project_id,
    v_company_id,
    p_source_name,
    p_source_type,
    'bus_schedule',
    p_source_ref,
    coalesce(p_version, ''),
    'published',
    jsonb_build_object('file_name', p_source_name, 'rebuilt_at', now())
  )
  on conflict (project_id, company_id, source_name, document_type, version) do update
  set source_ref = excluded.source_ref,
      source_type = excluded.source_type,
      status = excluded.status,
      metadata = excluded.metadata,
      updated_at = now()
  returning id into v_source_id;

  delete from public.bus_stops
  where route_id in (
    select br.id
    from public.bus_routes br
    join public.knowledge_sources ks on ks.id = br.knowledge_source_id
    where ks.company_id = v_company_id
      and ks.source_name = p_source_name
      and ks.document_type = 'bus_schedule'
  );

  delete from public.bus_routes br
  using public.knowledge_sources ks
  where ks.id = br.knowledge_source_id
    and ks.company_id = v_company_id
    and ks.source_name = p_source_name
    and ks.document_type = 'bus_schedule';

  delete from public.bus_route_service_days bsd
  using public.knowledge_sources ks
  where ks.id = bsd.knowledge_source_id
    and ks.company_id = v_company_id
    and ks.source_name = p_source_name
    and ks.document_type = 'bus_schedule';

  for rec in
    select d.id as document_id, line.line_no, line.text as line_text
    from public.documents d
    cross join lateral regexp_split_to_table(d.content, E'\n') with ordinality as line(text, line_no)
    where d.metadata ->> 'file_name' = p_source_name
    order by coalesce((d.metadata #>> '{loc,lines,from}')::int, 0), d.id, line.line_no
  loop
    line_text := btrim(rec.line_text);

    if line_text = '' then
      continue;
    end if;

    if line_text like '## 1. Bảng hoạt động theo tuần%' then
      current_section := 'weekly';
      current_weekly_route_name := null;
      current_weekly_route_key := null;
      continue;
    end if;

    if line_text like '## 2. Ca ngày%' then
      current_section := 'routes';
      current_shift := 'day';
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 3. Ca hành chính%' then
      current_section := 'admin';
      current_shift := 'admin';
      current_admin_block := null;
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 4. Ca đêm%' then
      current_section := 'routes';
      current_shift := 'night';
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 5. Mục cần giữ nguyên%' then
      current_section := 'done';
      continue;
    end if;

    if current_section = 'weekly' then
      weekly_route_match := regexp_match(line_text, '^\d+\.\s+(.+)$');
      if weekly_route_match is not null then
        current_weekly_route_name := trim(weekly_route_match[1]);
        current_weekly_route_key := public.normalize_bus_route_key(current_weekly_route_name);
        continue;
      end if;

      day_match := regexp_match(
        line_text,
        '^-?\s*(Thứ Hai đến Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật):\s+(.+)$'
      );

      if day_match is not null and current_weekly_route_key is not null then
        v_day_group := case day_match[1]
          when 'Thứ Hai đến Thứ Năm' then 'mon_thu'
          when 'Thứ Sáu' then 'fri'
          when 'Thứ Bảy' then 'sat'
          when 'Chủ Nhật' then 'sun'
          else null
        end;

        foreach flag in array regexp_split_to_array(day_match[2], '\s*,\s*')
        loop
          flag_match := regexp_match(flag, '^\s*([a-z_]+)\s*=\s*([AMX])\s*$');
          if flag_match is null then
            continue;
          end if;

          insert into public.bus_route_service_days (
            project_id,
            company_id,
            knowledge_source_id,
            route_group_key,
            route_group_name,
            day_group,
            day_label,
            service_type,
            availability_code,
            metadata
          )
          values (
            v_project_id,
            v_company_id,
            v_source_id,
            current_weekly_route_key,
            current_weekly_route_name,
            v_day_group,
            day_match[1],
            flag_match[1],
            flag_match[2],
            jsonb_build_object('parsed_from', 'weekly_matrix')
          )
          on conflict (company_id, route_group_key, day_group, service_type) do update
          set project_id = excluded.project_id,
              knowledge_source_id = excluded.knowledge_source_id,
              route_group_name = excluded.route_group_name,
              day_label = excluded.day_label,
              availability_code = excluded.availability_code,
              metadata = excluded.metadata;
        end loop;
      end if;

      continue;
    end if;

    if current_section = 'routes' then
      header_match := regexp_match(
        line_text,
        '^### Tuyến\s+([^:]+):\s+([^|\n]+)\s+\|\s+Khu vực:\s+([^|\n]+)\s+\|\s+Chế độ:\s+([^|\n]+)\s+\|\s+Trang\s+(\d+)'
      );

      if header_match is not null then
        current_route_no := trim(header_match[1]);
        current_route_name := trim(header_match[2]);
        current_area := trim(header_match[3]);
        current_mode := trim(header_match[4]);
        current_page := trim(header_match[5]);
        pending_notes := null;
        continue;
      end if;

      if line_text ~ '^(Ghi chú|Điều kiện):' then
        pending_notes := concat_ws(E'\n', pending_notes, line_text);
        continue;
      end if;

      route_match := regexp_match(line_text, '^- Lộ trình\s+([^:]+):\s+(.+)$');

      if route_match is not null and current_route_name is not null then
        insert into public.bus_routes (
          project_id,
          company_id,
          knowledge_source_id,
          route_name,
          route_no,
          route_variant,
          route_group_key,
          shift,
          direction,
          area,
          mode,
          source_page,
          notes,
          metadata
        )
        values (
          v_project_id,
          v_company_id,
          v_source_id,
          current_route_name,
          current_route_no,
          trim(route_match[1]),
          public.normalize_bus_route_key(current_route_name),
          current_shift,
          'outbound',
          current_area,
          current_mode,
          current_page,
          pending_notes,
          jsonb_build_object('route_text', trim(route_match[2]))
        )
        on conflict (company_id, route_name, route_variant, shift, direction, source_page, mode) do update
        set route_no = excluded.route_no,
            route_group_key = excluded.route_group_key,
            area = excluded.area,
            notes = excluded.notes,
            metadata = excluded.metadata,
            knowledge_source_id = excluded.knowledge_source_id
        returning id into v_route_id;

        stop_idx := 0;
        foreach stop_part in array regexp_split_to_array(trim(route_match[2]), '\s*->\s*')
        loop
          stop_idx := stop_idx + 1;
          stop_name_value := trim(regexp_replace(stop_part, '@\d{2}:\d{2}$', ''));
          stop_time_value := null;

          if stop_part ~ '@\d{2}:\d{2}$' then
            stop_time_value := substring(stop_part from '@(\d{2}:\d{2})$')::time;
          end if;

          insert into public.bus_stops (
            route_id,
            stop_order,
            stop_name,
            stop_aliases,
            scheduled_time,
            raw_stop_text
          )
          values (
            v_route_id,
            stop_idx,
            stop_name_value,
            array_remove(array[
              stop_name_value,
              case when stop_name_value ilike '%Kiến An%' then 'Kiến An' end,
              case when stop_name_value ilike '%Quán Toan%' then 'Quán Toan' end,
              case when stop_name_value ilike '%An Dương%' then 'An Dương' end,
              case when stop_name_value ilike '%Đồ Sơn%' then 'Đồ Sơn' end,
              case when stop_name_value ilike '%An Lão%' then 'An Lão' end,
              case when stop_name_value ilike '%Kiến Thụy%' then 'Kiến Thụy' end,
              case when stop_name_value ilike '%Vĩnh Bảo%' then 'Vĩnh Bảo' end,
              case when stop_name_value ilike '%Thái Bình%' then 'Thái Bình' end,
              case when stop_name_value ilike '%Hải Dương%' then 'Hải Dương' end,
              case when stop_name_value ilike '%Quảng Yên%' then 'Quảng Yên' end
            ], null),
            stop_time_value,
            trim(stop_part)
          )
          on conflict (route_id, stop_order) do update
          set stop_name = excluded.stop_name,
              stop_aliases = excluded.stop_aliases,
              scheduled_time = excluded.scheduled_time,
              raw_stop_text = excluded.raw_stop_text;
        end loop;

        pending_notes := null;
      end if;

      continue;
    end if;

    if current_section = 'admin' then
      if line_text like '### Lượt đi tuyến Hà Nội%' then
        current_admin_block := 'hanoi_outbound';
        pending_notes := null;
        continue;
      end if;

      if line_text ~ '^- Ghi chú' then
        pending_notes := concat_ws(E'\n', pending_notes, regexp_replace(line_text, '^- ', ''));
        continue;
      end if;

      if current_admin_block = 'hanoi_outbound' and line_text ~ '^- .*@\d{2}:\d{2}.*LGD' then
        insert into public.bus_routes (
          project_id,
          company_id,
          knowledge_source_id,
          route_name,
          route_no,
          route_variant,
          route_group_key,
          shift,
          direction,
          area,
          mode,
          source_page,
          notes,
          metadata
        )
        values (
          v_project_id,
          v_company_id,
          v_source_id,
          'Hà Nội',
          '18',
          '1',
          public.normalize_bus_route_key('Hà Nội'),
          'admin',
          'outbound',
          'Hà Nội',
          'standard',
          '6',
          pending_notes,
          jsonb_build_object('route_text', regexp_replace(line_text, '^- ', ''))
        )
        on conflict (company_id, route_name, route_variant, shift, direction, source_page, mode) do update
        set route_group_key = excluded.route_group_key,
            notes = excluded.notes,
            metadata = excluded.metadata,
            knowledge_source_id = excluded.knowledge_source_id
        returning id into v_route_id;

        stop_idx := 0;
        foreach stop_part in array regexp_split_to_array(regexp_replace(line_text, '^- ', ''), '\s*->\s*')
        loop
          stop_idx := stop_idx + 1;
          stop_name_value := trim(regexp_replace(stop_part, '@\d{2}:\d{2}$', ''));
          stop_time_value := null;

          if stop_part ~ '@\d{2}:\d{2}$' then
            stop_time_value := substring(stop_part from '@(\d{2}:\d{2})$')::time;
          end if;

          insert into public.bus_stops (
            route_id,
            stop_order,
            stop_name,
            stop_aliases,
            scheduled_time,
            raw_stop_text
          )
          values (
            v_route_id,
            stop_idx,
            stop_name_value,
            array_remove(array[
              stop_name_value,
              case when stop_name_value ilike '%Hà Nội%' then 'Hà Nội' end,
              case when stop_name_value ilike '%Gia Lâm%' then 'Gia Lâm' end
            ], null),
            stop_time_value,
            trim(stop_part)
          )
          on conflict (route_id, stop_order) do update
          set stop_name = excluded.stop_name,
              stop_aliases = excluded.stop_aliases,
              scheduled_time = excluded.scheduled_time,
              raw_stop_text = excluded.raw_stop_text;
        end loop;

        pending_notes := null;
      end if;
    end if;
  end loop;

  update public.bus_routes
  set route_group_key = public.normalize_bus_route_key(route_name)
  where company_id = v_company_id
    and (route_group_key is null or route_group_key = '');

  return query
  select
    (
      select count(*)::integer
      from public.bus_routes
      where knowledge_source_id = v_source_id
    ),
    (
      select count(*)::integer
      from public.bus_stops bs
      join public.bus_routes br on br.id = bs.route_id
      where br.knowledge_source_id = v_source_id
    );
end;
$function$;
"""

_SEARCH_BUS_TIMETABLE_SQL = r"""
CREATE OR REPLACE FUNCTION public.search_bus_timetable(
  p_project_slug text default 'vfic',
  p_company_query text default 'LG Display',
  p_question text default '',
  p_shift text default null,
  p_location text default null,
  p_limit integer default 20
)
returns table(
  company_name text,
  route_name text,
  route_variant text,
  shift text,
  direction text,
  stop_order integer,
  stop_name text,
  scheduled_time text,
  area text,
  mode text,
  source_name text,
  source_page text,
  match_reason text,
  requested_day_group text,
  requested_day_label text,
  availability_code text
)
language sql
stable
set search_path = public, extensions
as $function$
  with params as (
    select
      public.normalize_search_text(coalesce(p_question, '')) as q,
      public.normalize_search_text(coalesce(p_location, '')) as loc,
      case
        when p_shift in ('day', 'night', 'admin') then p_shift
        when public.normalize_search_text(coalesce(p_question, '')) like '%ca dem%' then 'night'
        when public.normalize_search_text(coalesce(p_question, '')) like '%ca ngay%' then 'day'
        when public.normalize_search_text(coalesce(p_question, '')) like '%hanh chinh%' then 'admin'
        else null
      end as wanted_shift,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 6|t6|friday) ' then 'fri'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 7|t7|saturday) ' then 'sat'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (chu nhat|cn|sunday) ' then 'sun'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 2|t2|thu 3|t3|thu 4|t4|thu 5|t5|monday|tuesday|wednesday|thursday) ' then 'mon_thu'
        else null
      end as wanted_day_group,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 6|t6|friday) ' then 'Thứ Sáu'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 7|t7|saturday) ' then 'Thứ Bảy'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (chu nhat|cn|sunday) ' then 'Chủ Nhật'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 2|t2|monday) ' then 'Thứ Hai'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 3|t3|tuesday) ' then 'Thứ Ba'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 4|t4|wednesday) ' then 'Thứ Tư'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 5|t5|thursday) ' then 'Thứ Năm'
        else null
      end as wanted_day_label,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (ve|ve nha|roi lgd|tu lgd|sau ca) ' then 'return'
        else 'outbound'
      end as wanted_direction
  ),
  base as (
    select
      c.name as company_name,
      br.route_name,
      br.route_variant,
      br.shift,
      br.direction,
      bs.stop_order,
      bs.stop_name,
      bs.stop_aliases,
      to_char(bs.scheduled_time, 'HH24:MI') as scheduled_time,
      br.area,
      br.mode,
      ks.source_name,
      br.source_page,
      br.route_group_key,
      case
        when br.direction = 'outbound' and br.shift in ('day', 'admin') then 'outbound_admin_and_day'
        when br.direction = 'outbound' and br.shift = 'night' then 'outbound_night'
        when br.direction = 'return' and br.shift = 'night' then 'return_night'
        when br.direction = 'return' and br.shift = 'admin' then 'return_admin'
        when br.direction = 'return' and br.shift = 'day' then 'return_day'
        else null
      end as route_service_type,
      cal.availability_code,
      cal.day_group as requested_day_group,
      coalesce(params.wanted_day_label, cal.day_label) as requested_day_label,
      params.q,
      params.loc,
      params.wanted_shift,
      params.wanted_day_group as param_day_group
    from public.projects p
    join public.companies c on c.project_id = p.id
    join public.bus_routes br on br.company_id = c.id
    join public.bus_stops bs on bs.route_id = br.id
    left join public.knowledge_sources ks on ks.id = br.knowledge_source_id
    cross join params
    left join public.bus_route_service_days cal
      on cal.company_id = c.id
     and cal.route_group_key = br.route_group_key
     and cal.day_group = params.wanted_day_group
     and cal.service_type = case
       when br.direction = 'outbound' and br.shift in ('day', 'admin') then 'outbound_admin_and_day'
       when br.direction = 'outbound' and br.shift = 'night' then 'outbound_night'
       when br.direction = 'return' and br.shift = 'night' then 'return_night'
       when br.direction = 'return' and br.shift = 'admin' then 'return_admin'
       when br.direction = 'return' and br.shift = 'day' then 'return_day'
       else null
     end
    where p.slug = p_project_slug
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and br.direction = params.wanted_direction
      and (
        params.wanted_shift is null
        or br.shift = params.wanted_shift
        or (params.wanted_shift = 'admin' and br.direction = 'outbound' and br.shift = 'day')
      )
      and bs.scheduled_time is not null
  ),
  scored as (
    select
      *,
      exists (
        select 1
        from unnest(coalesce(base.stop_aliases, '{}'::text[])) a
        where base.q like '%' || public.normalize_search_text(a) || '%'
           or (base.loc <> '' and public.normalize_search_text(a) like '%' || base.loc || '%')
      ) as stop_alias_match,
      (
        base.q like '%' || public.normalize_search_text(base.route_name) || '%'
        or base.q like '%' || base.route_group_key || '%'
        or (base.loc <> '' and base.route_group_key like '%' || base.loc || '%')
      ) as route_match,
      greatest(
        similarity(public.normalize_search_text(base.stop_name), base.q),
        similarity(public.normalize_search_text(base.route_name), base.q),
        similarity(base.route_group_key, base.q)
      ) as sim_score
    from base
  ),
  available_scored as (
    select
      *,
      bool_or(stop_alias_match or route_match) over () as has_direct_match
    from scored
    where
      param_day_group is null
      or (
        coalesce(availability_code, 'A') <> 'X'
        and (
          availability_code is null
          or (availability_code = 'M' and coalesce(mode, '') ilike 'merged%')
          or (availability_code = 'A' and coalesce(mode, '') not ilike 'merged%')
        )
      )
  ),
  unavailable_candidates as (
    select
      c.name as company_name,
      rsd.route_group_name as route_name,
      null::text as route_variant,
      case
        when rsd.service_type in ('outbound_night', 'return_night') then 'night'
        when rsd.service_type = 'return_admin' then 'admin'
        else 'day'
      end as shift,
      case
        when rsd.service_type like 'return_%' then 'return'
        else 'outbound'
      end as direction,
      null::integer as stop_order,
      null::text as stop_name,
      null::text as scheduled_time,
      null::text as area,
      null::text as mode,
      ks.source_name,
      null::text as source_page,
      'route unavailable on requested day' as match_reason,
      params.wanted_day_group as requested_day_group,
      params.wanted_day_label as requested_day_label,
      rsd.availability_code
    from params
    join public.projects p on p.slug = p_project_slug
    join public.companies c on c.project_id = p.id
    join public.bus_route_service_days rsd on rsd.company_id = c.id
    left join public.knowledge_sources ks on ks.id = rsd.knowledge_source_id
    where params.wanted_day_group is not null
      and rsd.day_group = params.wanted_day_group
      and rsd.availability_code = 'X'
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and params.q like '%' || public.normalize_search_text(rsd.route_group_name) || '%'
      and (
        params.wanted_shift is null
        or (
          params.wanted_shift = 'night'
          and rsd.service_type in ('outbound_night', 'return_night')
        )
        or (
          params.wanted_shift = 'day'
          and rsd.service_type in ('outbound_admin_and_day', 'return_day')
        )
        or (
          params.wanted_shift = 'admin'
          and rsd.service_type in ('outbound_admin_and_day', 'return_admin')
        )
      )
      and (
        params.wanted_direction = 'outbound'
        and rsd.service_type in ('outbound_admin_and_day', 'outbound_night')
        or params.wanted_direction = 'return'
        and rsd.service_type in ('return_night', 'return_admin', 'return_day')
      )
  ),
  missing_detail_candidates as (
    select
      c.name as company_name,
      rsd.route_group_name as route_name,
      null::text as route_variant,
      case
        when rsd.service_type in ('outbound_night', 'return_night') then 'night'
        when rsd.service_type = 'return_admin' then 'admin'
        else 'day'
      end as shift,
      case
        when rsd.service_type like 'return_%' then 'return'
        else 'outbound'
      end as direction,
      null::integer as stop_order,
      null::text as stop_name,
      null::text as scheduled_time,
      null::text as area,
      null::text as mode,
      ks.source_name,
      null::text as source_page,
      'route has no detailed timing in source' as match_reason,
      params.wanted_day_group as requested_day_group,
      params.wanted_day_label as requested_day_label,
      rsd.availability_code
    from params
    join public.projects p on p.slug = p_project_slug
    join public.companies c on c.project_id = p.id
    join public.bus_route_service_days rsd on rsd.company_id = c.id
    left join public.knowledge_sources ks on ks.id = rsd.knowledge_source_id
    where params.q like '%' || public.normalize_search_text(rsd.route_group_name) || '%'
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and (
        params.wanted_day_group is null
        or rsd.day_group = params.wanted_day_group
      )
      and rsd.availability_code <> 'X'
      and (
        params.wanted_shift is null
        or (
          params.wanted_shift = 'night'
          and rsd.service_type in ('outbound_night', 'return_night')
        )
        or (
          params.wanted_shift = 'day'
          and rsd.service_type in ('outbound_admin_and_day', 'return_day')
        )
        or (
          params.wanted_shift = 'admin'
          and rsd.service_type in ('outbound_admin_and_day', 'return_admin')
        )
      )
      and (
        params.wanted_direction = 'outbound'
        and rsd.service_type in ('outbound_admin_and_day', 'outbound_night')
        or params.wanted_direction = 'return'
        and rsd.service_type in ('return_night', 'return_admin', 'return_day')
      )
      and not exists (
        select 1
        from public.bus_routes br
        where br.company_id = c.id
          and br.route_group_key = rsd.route_group_key
          and br.direction = params.wanted_direction
          and (
            params.wanted_shift is null
            or br.shift = params.wanted_shift
            or (params.wanted_shift = 'admin' and params.wanted_direction = 'outbound' and br.shift = 'day')
          )
      )
  ),
  filtered as (
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      case
        when stop_alias_match then 'matched stop/location alias'
        when route_match then 'matched route name'
        else 'broad timetable match'
      end as match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      sim_score,
      stop_alias_match,
      route_match
    from available_scored
    where case
      when has_direct_match then stop_alias_match or route_match
      when exists (select 1 from unavailable_candidates) then false
      when exists (select 1 from missing_detail_candidates) then false
      else sim_score > 0.16
    end
  ),
  unavailable as (
    select *
    from unavailable_candidates
    where not exists (select 1 from filtered)
  ),
  missing_detail as (
    select *
    from missing_detail_candidates
    where not exists (select 1 from filtered)
      and not exists (select 1 from unavailable)
  )
  select
    company_name,
    route_name,
    route_variant,
    shift,
    direction,
    stop_order,
    stop_name,
    scheduled_time,
    area,
    mode,
    source_name,
    source_page,
    match_reason,
    requested_day_group,
    requested_day_label,
    availability_code
  from (
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      (case when stop_alias_match then 100 else 0 end
       + case when route_match then 60 else 0 end
       + sim_score * 30) as rank_score
    from filtered
    union all
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      -1::numeric as rank_score
    from unavailable
    union all
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      -2::numeric as rank_score
    from missing_detail
  ) ranked
  order by rank_score desc, route_name nulls last, stop_order nulls last
  limit least(greatest(coalesce(p_limit, 20), 1), 50);
$function$;
"""
