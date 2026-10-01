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
  // Canonical channel identity. Messenger leads have no zalo_id, so this is the
  // only key the inbox can match them on.
  contact_id?: string | null;
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
  avatar_url?: string | null;
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

export type LeadTag = {
  key: string;
  label: string;
  tone: "good" | "warn" | "danger" | "info";
  system: boolean;
};

export type LeadAssistMessage = {
  sender: "candidate" | "recruiter" | "bot" | "system" | string;
  body: string;
  created_at: string;
};

export type LeadSignal = {
  key: string;
  name: string;
  status: string;
  active: boolean;
  action?: string | null;
};

export type LeadAssist = {
  summary: string;
  missing: string[];
  reply: string;
  next_action: string;
  mode_label: string;
  signals: LeadSignal[];
  recent_messages: LeadAssistMessage[];
};

export type LeadChatOpsActionResult = {
  lead: Lead;
  tags: LeadTag[];
  assist: LeadAssist;
};

export type Conversation = {
  id: string;
  // Zalo compatibility aliases — nullable for non-Zalo (Messenger) conversations.
  zalo_chat_id?: string | null;
  zalo_channel?: "bot" | "oa" | string;
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
  contact_id?: string | null;
  channel_identity_id?: string | null;
  contact?: {
    id: string;
    display_name?: string | null;
    primary_phone?: string | null;
    primary_email?: string | null;
    avatar_url?: string | null;
    locale?: string | null;
  } | null;
  channel_identity?: {
    id: string;
    provider: string;
    account_key: string;
    external_id: string;
    /** Server-derived badge channel — the TingTing support OA narrowed
     *  inside zalo_oa (backend schemas/conversation.py `channel_display`). */
    display_channel?: string | null;
  } | null;
} & Pick<RaRecord, "id">;

export type Message = {
  id: string;
  // Zalo compatibility alias — nullable for non-Zalo (Messenger) messages.
  zalo_message_id?: string | null;
  conversation_id: string;
  type: "inbound" | "outbound" | "system";
  content: string;
  delivery_status?:
    | "pending"
    | "sending"
    | "sent"
    | "failed"
    | "send_unknown"
    | "suppressed";
  /** Number of delivery attempts made for this outbound message. */
  delivery_attempts?: number;
  /** Backend failure reason for a failed/unknown send (maps to
   * messages.external_error). Surfaced in the bubble so a "Gửi lỗi" row is
   * diagnosable instead of blank. */
  external_error?: string | null;
  // Backend `data` jsonb. Carries recruiter_id on recruiter-sent messages
  // (the direction discriminator read in ChatThread). Narrowed from `any`.
  data: { recruiter_id?: string | null } | null;
  created_at: string;
} & Pick<RaRecord, "id">;

// A single bot execution against a conversation. `outcome` is the takeover
// race-guard verdict: sent (delivered to Zalo), suppressed (a recruiter took
// over mid-run — version mismatch), or error. Read-only ops data.
export type BotRunOutcome = "sent" | "suppressed" | "error";

export type BotRun = {
  id: number;
  conversation_id: string;
  started_at: string;
  ended_at: string | null;
  version_at_start: number;
  proposed_reply: string | null;
  outcome: BotRunOutcome;
} & Pick<RaRecord, "id">;

export type DecisionTraceDecisionEvent = {
  seq: number;
  kind: "decision";
  code: string;
  summary_code: string;
};

export type DecisionTraceToolEvent = {
  seq: number;
  kind: "tool";
  name: string;
  selected_by: "model" | "policy" | "prefetch";
};

export type DecisionTraceModelTurnEvent = {
  seq: number;
  kind: "model_turn";
  turn: number;
  phase: "tool_request" | "final" | "retry" | "direct";
  provider: "minimax" | "openrouter" | "unknown";
  model: string;
  reasoning_status: "returned" | "not_returned" | "truncated";
  reasoning: string | null;
  tool_names: string[];
};

export type DecisionTraceEvent =
  | DecisionTraceDecisionEvent
  | DecisionTraceToolEvent
  | DecisionTraceModelTurnEvent;

export type DecisionTrace = {
  version: number;
  events: DecisionTraceEvent[];
  truncated: boolean;
};

export type BotRunTraceSummary = {
  id: number;
  conversation_id: string;
  started_at: string;
  ended_at: string | null;
  outcome: BotRunOutcome;
  trace_available: boolean;
};

export type BotRunTraceDetail = BotRunTraceSummary & {
  decision_trace: DecisionTrace | null;
};

export type BotRunTraceSummaryList = {
  data: BotRunTraceSummary[];
  total: number;
};

// Knowledge document (per-project RAG doc). Mirrors the backend
// KnowledgeDocumentOut shape served at /api/v1/knowledge/documents. `stage` is the
// fine-grained training-pipeline progress (UPLOADED -> ... -> PUBLISHED/APPROVED);
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
  roles?: string[];
  key_roles?: string[];
  location?: string;
  eligibility?: string[];
  highlights?: string[];
}
export type Project = {
  id: string;
  slug: string;
  name: string;
  aliases?: string[];
  is_active: boolean;
  ingest_state?: "ingesting" | "ready" | "error" | null;
  knowledge_mode?: "RAG" | "DIRECT_CONTEXT" | null;
  category_authority_started?: boolean;
  summary?: string | null;
  index_card?: ProjectIndexCard;
  discovery_revision?: number;
  knowledge_base_id?: string | null;
  knowledge_document_count?: number;
  feature_readiness?: { ready: number; total: number };
  created_at: string;
  updated_at: string;
} & Pick<RaRecord, "id">;

export type KnowledgeBase = {
  id: string;
  name: string;
  slug: string;
  mode: "RAG" | "DIRECT_CONTEXT";
  description?: string | null;
  attached_agent_count: number;
  project_count: number;
} & Pick<RaRecord, "id">;

export type KnowledgeBaseProject = {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  knowledge_document_count: number;
  active_job_count: number;
  factories: { name: string; aliases: string[] }[];
};

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

export const ADAPTER_PROVIDERS = [
  "zalo_bot",
  "zalo_oa",
  "facebook_messenger",
] as const;

export type AdapterProvider = (typeof ADAPTER_PROVIDERS)[number];

export const ADAPTER_PROVIDER_LABELS: Record<AdapterProvider, string> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
};

export type AdapterPersonaAssignment = {
  provider: AdapterProvider;
  label: string;
  persona_id: string | null;
  effective_persona_id: string | null;
  is_default: boolean;
};

// An agent persona (free-form markdown). Several stored; one global persona active.
export type Persona = {
  id: string;
  knowledge_base_id?: string | null;
  name: string;
  slug: string;
  body_md: string;
  followup_rules: PersonaFollowupRules;
  is_active: boolean;
  notes?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  effective_adapter_providers?: AdapterProvider[];
} & Pick<RaRecord, "id">;

export type PersonaFollowupRule = {
  enabled: boolean;
  cadence_hours: number[];
  eligible_stages: LeadStageValue[];
};

export type PersonaFollowupRules = Record<LeadScoreValue, PersonaFollowupRule>;

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
// Order = recruitment funnel. Consumed by PersonaForm and useDashboardStats.
export const LEAD_STAGES = [
  { value: "NEW", label: "Mới", color: "bg-slate-500" },
  { value: "CONTACTING", label: "Đang liên hệ", color: "bg-info" },
  { value: "REGISTERED", label: "Đã đăng ký", color: "bg-warning" },
  { value: "SKIPPED", label: "Bỏ qua", color: "bg-zinc-500" },
] as const;

export type LeadStageValue = (typeof LEAD_STAGES)[number]["value"];

// Lead scores — DB-CHECK canonical values (leads.lead_score CHECK constraint).
// Categorical (hot / warm / not_interested), NOT a 0-100 numeric despite the
// legacy column name. Drives the LeadScoreValue type, used by PersonaForm.
export const LEAD_SCORES = [
  { value: "hot", label: "Ưu tiên cao", color: "bg-destructive" },
  { value: "warm", label: "Ưu tiên", color: "bg-warning" },
  { value: "not_interested", label: "Không quan tâm", color: "bg-zinc-500" },
] as const;

export type LeadScoreValue = (typeof LEAD_SCORES)[number]["value"];

// Conversation-channel vocabulary — the provider ids the API puts on a
// conversation row and the one Vietnamese label per channel. Every surface
// that names a channel — the inbox adapter selector, the notification rows,
// the performance adapter matrix and the persona assignment rows — reads this
// map, so a channel is never labelled two different ways. It lives here (the
// shared module feature `domain` layers may import) because the persona domain
// needs it and the architecture test keeps feature domains inward-only.
export const CONVERSATION_CHANNEL_PROVIDERS = [
  "zalo_bot",
  "zalo_oa",
  "facebook_messenger",
  // The employee-support OA: provider zalo_oa, narrowed to the linked account.
  // Only admins can read those threads (server-side scope).
  "tingting_oa",
] as const;

export type ConversationChannelProvider =
  (typeof CONVERSATION_CHANNEL_PROVIDERS)[number];

export const isConversationChannelProvider = (
  value: string | null,
): value is ConversationChannelProvider =>
  value !== null &&
  CONVERSATION_CHANNEL_PROVIDERS.some((provider) => provider === value);

export const CONVERSATION_CHANNEL_LABELS: Record<
  ConversationChannelProvider,
  string
> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
  // The employee-support OA: display channel for zalo_oa rows whose
  // account_key is "tingting" (resolveConversationDisplayChannel).
  tingting_oa: "TingTing OA",
};

/**
 * Row-sized form of the same vocabulary: a conversation row has one line for
 * the candidate and the channel chip sits beside the name, where the full
 * support-OA label cannot fit. Kept beside the full map so the two cannot drift.
 */
export const CONVERSATION_CHANNEL_SHORT_LABELS: Record<
  ConversationChannelProvider,
  string
> = {
  zalo_bot: "Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
  tingting_oa: "TingTing OA",
};

/**
 * Label for a raw provider string from the API. Unknown or absent providers
 * read as a neutral channel rather than as an empty cell.
 */
export const conversationChannelLabel = (
  provider: string | null | undefined,
): string =>
  isConversationChannelProvider(provider ?? null)
    ? CONVERSATION_CHANNEL_LABELS[provider as ConversationChannelProvider]
    : "Kênh khác";

/** Row-sized label; falls back to the full label's neutral wording. */
export const conversationChannelShortLabel = (
  provider: string | null | undefined,
): string =>
  isConversationChannelProvider(provider ?? null)
    ? CONVERSATION_CHANNEL_SHORT_LABELS[provider as ConversationChannelProvider]
    : "Kênh khác";
