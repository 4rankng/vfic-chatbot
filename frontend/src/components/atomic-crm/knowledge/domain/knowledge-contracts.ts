export type KnowledgeUnit = Readonly<{
  id: string;
  chunk_index: number;
  content: string;
  source_quote?: string | null;
  summary?: string | null;
  questions: string[];
  category?: string | null;
  entities: Record<string, unknown>;
  confidence?: string | null;
  is_inference: boolean;
  source_anchor?: string | null;
  citation_label?: string | null;
  content_type?: string | null;
  route_id?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  created_at: string;
}>;

export type KnowledgeUnitList = Readonly<{
  data: KnowledgeUnit[];
  total: number;
}>;

export type KnowledgeBaseVersion = Readonly<{
  id: string;
  project_id: string;
  status: string;
  version_no: number;
}>;

export type KnowledgeIngestResult = Readonly<{
  job_id: string;
  status: string;
  kb_version_id: string;
}>;

export type ReindexAllKnowledgeResult = Readonly<{
  status: string;
  queued: number;
}>;
