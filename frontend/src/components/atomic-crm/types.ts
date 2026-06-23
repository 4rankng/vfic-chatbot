import type { Identifier, RaRecord } from "ra-core";

export type Profile = {
  id: string;
  full_name: string;
  email: string;
  role: "admin" | "recruiter";
  created_at: string;
  updated_at: string;
};

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
  desired_job: string;
  expected_salary: string;
  lead_score: LeadScoreValue | null;
  lead_stage: string;
  created_at: string;
  updated_at: string;
  // Extra live columns (returned by select("*")); surfaced for derived tags /
  // timeline. Optional to stay backward-compatible with partial selections.
  region?: string | null;
  living_area?: string | null;
  notes?: string | null;
} & Pick<RaRecord, "id">;

export type Conversation = {
  id: string;
  zalo_chat_id: string;
  mode: "bot" | "human";
  last_inbound_at: string;
  assigned_recruiter_id: string | null;
  created_at: string;
  updated_at: string;
  // Denormalized unread inbound counter, kept in sync by the
  // vfic_chat_histories_unread trigger. Reset to 0 by vfic_mark_read on open.
  // Optional: the fakerest demo provider / story fixtures don't supply it, so
  // all use sites default to 0 via `?? 0`.
  unread_count?: number;
} & Pick<RaRecord, "id">;

export type Message = {
  id: string;
  zalo_message_id: string;
  conversation_id: string;
  type: "inbound" | "outbound" | "system";
  content: string;
  data: any;
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

// Knowledge-source row (Drive-ingested docs for RAG). `status` is free text
// (default 'published'); chunks live in `documents` (joined via documents.source
// = knowledge_sources.source_name). Read-only admin view.
export type KnowledgeSource = {
  id: string;
  project_id: string;
  company_id: string | null;
  source_name: string;
  source_type: string;
  document_type: string;
  source_ref: string | null;
  version: string;
  status: string;
  metadata: unknown;
  created_at: string;
  updated_at: string;
} & Pick<RaRecord, "id">;

export interface Company {
  id: Identifier;
  name: string;
  logo?: { src?: string; title?: string };
  sector?: string;
  size?: number;
  website?: string;
  linkedin_url?: string;
  phone_number?: string;
  address?: string;
  zipcode?: string;
  city?: string;
  state?: string;
  country?: string;
  description?: string;
  context_links?: Array<{ label: string; url: string }>;
  nb_contacts?: number;
  nb_deals?: number;
  sales_id?: Identifier;
  revenue?: string | number;
  created_at?: string;
  updated_at?: string;
}

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

export interface Deal {
  id: Identifier;
  name: string;
  stage: string;
  amount?: number;
  company_id?: Identifier | null;
  company_name?: string;
  sales_id?: Identifier;
  index?: number;
  archived_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DealNote {
  id: Identifier;
  deal_id: Identifier;
  sales_id: Identifier;
  text: string;
  status?: string;
  attachments?: RAFile[];
  date?: string;
}

export interface ContactNote {
  id: Identifier;
  contact_id: Identifier;
  sales_id: Identifier;
  text: string;
  status?: string;
  attachments?: RAFile[];
  date?: string;
}

export interface Sale {
  id: Identifier;
  user_id?: string;
  first_name: string;
  last_name: string;
  email: string;
  password?: string;
  administrator?: boolean;
  disabled?: boolean;
  avatar?: { src?: string };
}

export interface Tag {
  id: Identifier;
  name: string;
  color?: string;
}

export interface Task {
  id: Identifier;
  contact_id: Identifier;
  sales_id?: Identifier;
  type?: string;
  text: string;
  due_date?: string;
  done_date?: string;
  created_at?: string;
}

export interface SignUpData {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

export interface RAFile {
  src: string;
  title: string;
  path?: string;
  rawFile: File;
  type?: string;
}

export interface LabeledValue {
  value: string;
  label: string;
}

// Legacy Activity log type alias — referenced by the activity provider.
export type Activity = {
  id: Identifier;
  company_id?: Identifier | null;
  sales_id?: Identifier | null;
  contact_id?: Identifier | null;
  deal_id?: Identifier | null;
  type: string;
  date: string;
  text?: string;
};

// Email + type alias used by avatar helpers.
export type EmailAndType = { email: string | null; type: string | null };
export type PhoneAndType = { number: string | null; type: string | null };

// Lead stages — DB-CHECK canonical values (leads.lead_stage CHECK constraint).
// Order = recruitment funnel. Used across LeadShow, LeadCard, LeadColumn, Dashboard.
export const LEAD_STAGES = [
  { value: "NEW", label: "Mới", color: "bg-slate-500" },
  { value: "ENGAGED", label: "Đang liên hệ", color: "bg-blue-500" },
  { value: "QUALIFIED", label: "Đủ điều kiện", color: "bg-cyan-500" },
  { value: "APPLIED", label: "Đã ứng tuyển", color: "bg-amber-500" },
  { value: "HIRED", label: "Đã tuyển", color: "bg-emerald-500" },
  { value: "CLOSED", label: "Đã đóng", color: "bg-zinc-500" },
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
