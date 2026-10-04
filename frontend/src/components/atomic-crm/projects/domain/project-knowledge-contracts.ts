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

/** Authoritative saved project knowledge returned as a Markdown attachment. */
export type ProjectKnowledgeExport = Readonly<{
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

/** The authority state a cutover reports: the project's knowledge now comes
 *  from its category revisions, and the console renders the catalog. */
export type CategoryAuthorityState = Readonly<{
  project_id: string;
  category_authority_started: boolean;
  category_cutover_at: string | null;
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
