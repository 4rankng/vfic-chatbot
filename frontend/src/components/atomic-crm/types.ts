import type { Identifier, RaRecord } from "ra-core";

export type UserAccount = {
  id: string;
  full_name: string;
  email: string;
  role: "admin" | "recruiter";
  disabled: boolean;
  created_at: string;
  updated_at: string;
};

export type Profile = UserAccount;

// Legacy Contact model — still referenced by partially-migrated components in
// conversations/ and notes/. Kept as an alias of the Lead shape so existing code
// keeps type-checking until the migration is finished.
export type ContactGender = "male" | "female" | "nonbinary" | "unknown";

export interface ContactPhoneJsonb {
  number: string | null;
  type: string | null;
}

export interface ContactEmailJsonb {
  email: string | null;
  type: string | null;
}

export type Contact = {
  id: Identifier;
  first_name: string;
  last_name: string;
  gender: ContactGender;
  title?: string | null;
  company_id?: Identifier | null;
  company_name?: string | null;
  email_jsonb?: ContactEmailJsonb[] | null;
  phone_jsonb?: ContactPhoneJsonb[] | null;
  linkedin_url?: string | null;
  background?: string | null;
  has_newsletter?: boolean;
  status?: "cold" | "warm" | "hot";
  tags?: number[];
  first_seen?: string;
  last_seen?: string;
  sales_id?: Identifier;
  nb_tasks?: number;
  avatar?: { src?: string };
} & Pick<RaRecord, "id">;

export type Lead = {
  id: number;
  zalo_id: string;
  name: string;
  phone: string;
  birth_year?: number | null;
  age?: number | null;
  living_area?: string | null;
  address?: string | null;
  gender?: string | null;
  region?: string | null;
  desired_job: string;
  years_experience?: string | null;
  expected_salary: string;
  qualification_reasons?: string[];
  lead_score: LeadScoreValue | null;
  lead_stage: string;
  next_action_at?: string | null;
  created_at: string;
  updated_at: string;
  // Extra live columns surfaced for derived tags / timeline.
  notes?: string | null;
  version?: number;
} & Pick<RaRecord, "id">;

export type Conversation = {
  id: string;
  zalo_chat_id: string;
  // Backend ConversationMode is BOT/HUMAN/SEMI_AUTO/CLOSED; the REST dataProvider
  // lower-cases it so render checks keep working.
  mode: "bot" | "human" | "semi_auto" | "closed";
  needs_human?: boolean;
  last_inbound_at: string | null;
  last_outbound_at?: string | null;
  assigned_recruiter_id: string | null;
  created_at: string;
  updated_at: string;
  // Denormalized unread inbound counter, kept in sync by the
  // vfic_chat_histories_unread trigger. Reset to 0 by vfic_mark_read on open.
  // Optional: partial selects may omit it; use sites default to 0 via `?? 0`.
  unread_count?: number;
} & Pick<RaRecord, "id">;

export type Message = {
  id: string;
  zalo_message_id: string;
  conversation_id: string;
  type: "inbound" | "outbound" | "system";
  content: string;
  delivery_status?: "pending" | "sent" | "failed" | "suppressed";
  // Backend `data` jsonb. Carries recruiter_id on recruiter-sent messages
  // (the direction discriminator read in ChatThread). Narrowed from `any`.
  data: { recruiter_id?: string | null } | null;
  created_at: string;
} & Pick<RaRecord, "id">;

// A single bot execution against a conversation. `outcome` is the takeover
// race-guard verdict: sent (delivered to Zalo), suppressed (a recruiter took
// over mid-run — version mismatch), or error. Read-only ops data.
export type BotRun = {
  id: number;
  conversation_id: string;
  started_at: string;
  ended_at: string | null;
  version_at_start: number;
  proposed_reply: string | null;
  outcome: "sent" | "suppressed" | "error";
} & Pick<RaRecord, "id">;

// Knowledge document (per-project RAG doc). Mirrors the backend
// KnowledgeDocumentOut shape served at /api/v1/knowledge/documents. `stage` is the
// fine-grained training-pipeline progress (UPLOADED -> ... -> PUBLISHED);
// `digest_meta` carries unit/flagged counts from the ingest run.
export type KnowledgeSource = {
  id: string;
  drive_file_id: string | null;
  file_name: string;
  source: string;
  version: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  project_id?: string | null;
  project_name?: string | null;
  mime_type?: string | null;
  stage?: string;
  digest_summary?: string | null;
  digest_meta?: {
    unit_count?: number;
    section_count?: number;
    flagged_unit_indexes?: number[];
  };
  is_canonical?: boolean;
  error?: string | null;
} & Pick<RaRecord, "id">;

// A "project" = a product in the agent's master index (e.g. the LG Display factory).
// index_card is the LLM-generated catalog entry (summary/roles/location/highlights).
export interface ProjectIndexCard {
  summary?: string;
  key_roles?: string[];
  location?: string;
  highlights?: string[];
}
export type Project = {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  summary?: string | null;
  index_card?: ProjectIndexCard;
  default_persona_id?: string | null;
  knowledge_document_count?: number;
  feature_readiness?: { ready: number; total: number };
  created_at: string;
  updated_at: string;
} & Pick<RaRecord, "id">;

// A worker product feature value (one row per catalog feature per project), joined with
// the catalog metadata. Populated by the LLM extraction step in the ingest pipeline and
// surfaced in the admin "Đặc điểm sản phẩm" panel + the agent's get_product_features tool.
export type ProductFeature = {
  id: string;
  project_id: string;
  feature_id: string;
  feature_key: string;
  name_vi: string;
  category: string;
  worker_question_vi: string | null;
  value_text: string;
  value_json: Record<string, unknown>;
  strength_score: number;
  display_priority: number;
  is_highlight: boolean;
  is_missing: boolean;
  needs_clarification: boolean;
  evidence_text: string | null;
  source_document_id: string | null;
  updated_at: string;
} & Pick<RaRecord, "id">;

export type ProductFeatureList = { data: ProductFeature[]; total: number };

export type BusStop = {
  id: string;
  stop_order: number;
  stop_name: string;
  scheduled_time?: string | null;
};

export type BusRoute = {
  id: string;
  route_name: string;
  route_no?: string | null;
  route_variant: string;
  shift: "day" | "night" | "admin" | string;
  direction: "outbound" | "return" | string;
  area?: string | null;
  mode?: string | null;
  source_page?: string | null;
  notes?: string | null;
  stops: BusStop[];
};

export type BusTimetableList = {
  data: BusRoute[];
  total: number;
  page: number;
  per_page: number;
};

// An agent persona (free-form markdown). Several stored; one global persona active.
export type Persona = {
  id: string;
  project_id?: string | null;
  name: string;
  slug: string;
  body_md: string;
  is_active: boolean;
  notes?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  assigned_projects?: { id: string; name: string; slug: string }[];
} & Pick<RaRecord, "id">;

export type DealStage = {
  value: string;
  label: string;
  color?: string;
};

export type NoteStatus = {
  value: string;
  label: string;
  color: string;
};

export interface LabeledValue {
  value: string;
  label: string;
}

// Lead stages — DB-CHECK canonical values (leads.lead_stage CHECK constraint).
// Order = recruitment funnel. Used across LeadShow, LeadCard, LeadColumn, Dashboard.
export const LEAD_STAGES = [
  { value: "NEW", label: "Mới", color: "bg-slate-500" },
  { value: "CONTACTING", label: "Đang liên hệ", color: "bg-blue-500" },
  { value: "REGISTERED", label: "Đã đăng ký", color: "bg-amber-500" },
  { value: "SKIPPED", label: "Bỏ qua", color: "bg-zinc-500" },
] as const;

export type LeadStageValue = (typeof LEAD_STAGES)[number]["value"];

// Lead scores — DB-CHECK canonical values (leads.lead_score CHECK constraint).
// Categorical (hot / warm / not_interested), NOT a 0-100 numeric despite the
// legacy column name. Used across LeadShow, LeadCard, LeadInfoPanel, ContactInputs.
export const LEAD_SCORES = [
  { value: "hot", label: "Ưu tiên cao", color: "bg-rose-500" },
  { value: "warm", label: "Ưu tiên", color: "bg-amber-500" },
  { value: "not_interested", label: "Không quan tâm", color: "bg-zinc-500" },
] as const;

export type LeadScoreValue = (typeof LEAD_SCORES)[number]["value"];
