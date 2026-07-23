import type { ProductFeature } from "../../types";
import type { ProjectKnowledgeCategory } from "./project-knowledge-policy";

export type KnowledgeCategoryStatus = Readonly<{
  key: ProjectKnowledgeCategory;
  label_vi: string;
  active_revision_id?: string | null;
  active_revision_no?: number | null;
  active_checksum?: string | null;
  latest_revision_id?: string | null;
  latest_revision_no?: number | null;
  status?:
    | "STAGED"
    | "PROCESSING"
    | "ACTIVE"
    | "ARCHIVED"
    | "FAILED"
    | "CLEARED"
    | null;
  updated_at?: string | null;
  error_message?: string | null;
}>;

export type KnowledgeCategoryCatalog = Readonly<{
  data: KnowledgeCategoryStatus[];
  total: number;
}>;

export type KnowledgeCategoryTemplate = Readonly<{
  key: ProjectKnowledgeCategory;
  label_vi: string;
  filename: string;
  content: string;
}>;

export type KnowledgeCategorySource = Readonly<{
  key: ProjectKnowledgeCategory;
  label_vi: string;
  revision_id: string;
  revision_no: number;
  filename: string;
  content: string;
  checksum: string;
  updated_at: string;
}>;

export type KnowledgeCategoryRevision = Readonly<{
  id: string;
  category_id: string;
  revision_no: number;
  status: string;
  source_filename: string;
  content_sha256: string;
  normalized_payload: Record<string, unknown>;
  created_at: string;
  activated_at?: string | null;
  error_message?: string | null;
}>;

export type SinglePageKnowledge = Readonly<{
  id: string;
  knowledge_base_id: string;
  filename: string;
  text: string;
  char_count: number;
  line_count: number;
  content_sha256: string;
  updated_at: string;
}>;

export type ProjectFaq = Readonly<{
  id: string;
  question: string;
  answer: string;
  question_variants?: string[];
  required_terms?: string[];
  forbidden_terms?: string[];
  source_name?: string | null;
  source_anchor?: string | null;
}>;

export type ProjectFaqList = Readonly<{
  data: ProjectFaq[];
  total: number;
}>;

export type ProjectFaqPayload = Pick<
  ProjectFaq,
  | "question"
  | "answer"
  | "question_variants"
  | "required_terms"
  | "forbidden_terms"
>;

export type FeaturePatch = Partial<
  Pick<
    ProductFeature,
    | "value_text"
    | "value_json"
    | "is_highlight"
    | "is_missing"
    | "needs_clarification"
    | "evidence_text"
  >
>;

export type ExternalSourceSyncState = Readonly<{
  id: string;
  project_id: string;
  category_key: ProjectKnowledgeCategory;
  source_kind: string;
  sheet_url: string;
  sheet_gid: number;
  auto_sync_enabled: boolean;
  consecutive_failures: number;
  last_content_hash?: string | null;
  last_synced_at?: string | null;
  last_status: string;
  last_error?: string | null;
  last_row_count?: number | null;
  last_revision_id?: string | null;
  created_at: string;
  updated_at: string;
}>;

export type SinglePageExternalSourceSyncState = Omit<
  ExternalSourceSyncState,
  "category_key"
>;

export type ExternalSourceCreatePayload = Readonly<{
  source_kind?: string;
  category_key: ProjectKnowledgeCategory;
  sheet_url: string;
  sheet_gid?: number;
  auto_sync_enabled?: boolean;
}>;

export type SinglePageExternalSourceCreatePayload = Readonly<{
  sheet_url: string;
  auto_sync_enabled?: boolean;
}>;
