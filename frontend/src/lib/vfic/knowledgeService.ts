// Knowledge-base / project / persona action routes (VFIC FastAPI backend).
//
// These target the dedicated action endpoints (not the react-admin CRUD verbs),
// re-using the authenticated REST client. The knowledge upload is multipart.

import {
  ApiError,
  apiJson,
  apiRequest,
} from "@/components/atomic-crm/providers/rest/api";
import type {
  AdapterPersonaAssignment,
  AdapterProvider,
  BusTimetableList,
  PersonaFollowupRules,
  ProductFeature,
  ProductFeatureList,
} from "@/components/atomic-crm/types";

const BASE = "/api/v1";

export type ApiRecord = Record<string, unknown>;
const doc = (id: string) =>
  `${BASE}/knowledge/documents/${encodeURIComponent(id)}`;
const proj = (id: string) =>
  `${BASE}/knowledge/projects/${encodeURIComponent(id)}`;

export type KnowledgeUnit = {
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
};

export type KnowledgeUnitList = {
  data: KnowledgeUnit[];
  total: number;
};

export type ProjectFaq = {
  id: string;
  question: string;
  answer: string;
  /** Extra phrasings + the deterministic FAQ-bypass rule terms (all optional). */
  question_variants?: string[];
  required_terms?: string[];
  forbidden_terms?: string[];
  source_name?: string | null;
  source_anchor?: string | null;
};

export type ProjectFaqList = {
  data: ProjectFaq[];
  total: number;
};

export type KnowledgeBaseVersion = {
  id: string;
  project_id: string;
  status: string;
  version_no: number;
};

export const createKnowledgeBaseVersion = (projectId: string) =>
  apiJson<KnowledgeBaseVersion>(
    `${proj(projectId)}/kb/versions`,
    { method: "POST" },
  );

export const uploadKnowledgeBaseVersionFile = async (
  projectId: string,
  versionId: string,
  file: File,
) => {
  const form = new FormData();
  form.append("file", file);
  const response = await apiRequest(
    `${proj(projectId)}/kb/versions/${encodeURIComponent(versionId)}/files`,
    { method: "POST", body: form },
  );
  if (!response.ok) {
    throw new ApiError(response.status, "Không tải được tệp vào phiên bản KB.");
  }
  return response.json() as Promise<ApiRecord>;
};

export const ingestKnowledgeBaseVersion = (projectId: string, versionId: string) =>
  apiJson<{ job_id: string; status: string; kb_version_id: string }>(
    `${proj(projectId)}/kb/versions/${encodeURIComponent(versionId)}/ingest`,
    { method: "POST" },
  );

export const createAndIngestKnowledgeBaseVersion = async (
  projectId: string,
  file: File,
) => {
  const version = await createKnowledgeBaseVersion(projectId);
  await uploadKnowledgeBaseVersionFile(projectId, version.id, file);
  return ingestKnowledgeBaseVersion(projectId, version.id);
};

export const listKnowledgeBaseVersions = (projectId: string) =>
  apiJson<{ data: KnowledgeBaseVersion[]; total: number }>(
    `${proj(projectId)}/kb/versions`,
  );

export const publishKnowledgeBaseVersion = (projectId: string, versionId: string) =>
  apiJson<KnowledgeBaseVersion>(
    `${proj(projectId)}/kb/versions/${encodeURIComponent(versionId)}/publish`,
    { method: "POST" },
  );

export const downloadKnowledgeTemplate = async (
  kind: "knowledge" | "faq" = "knowledge",
): Promise<string> => {
  const response = await apiRequest(
    `${BASE}/knowledge/format/template?kind=${kind}`,
  );
  if (!response.ok) {
    throw new ApiError(response.status, "Không tải được mẫu định dạng.");
  }
  return response.text();
};

export const saveKnowledgeTemplate = async (
  kind: "knowledge" | "faq" = "knowledge",
): Promise<void> => {
  const template = await downloadKnowledgeTemplate(kind);
  const url = URL.createObjectURL(
    new Blob([template], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download =
    kind === "faq"
      ? "vfic-faq-v1-template.md"
      : "vfic-knowledge-v1-template.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export const downloadKnowledgeRawFile = async (
  id: string,
  fileName = "knowledge-source.md",
): Promise<void> => {
  const response = await apiRequest(`${doc(id)}/raw`);
  if (!response.ok) {
    throw new ApiError(response.status, "Không tải được tệp gốc.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName || "knowledge-source.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export const processKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/process`, { method: "POST" });

export const archiveKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/archive`, { method: "POST" });

export const reindexKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/reindex`, { method: "POST" });

export type ReindexAllKnowledgeResult = {
  status: string;
  queued: number;
};

export const reindexAllKnowledge = () =>
  apiJson<ReindexAllKnowledgeResult>(`${BASE}/knowledge/reindex-all`, {
    method: "POST",
  });

export const getKnowledgeUnits = (id: string, limit = 50) =>
  apiJson<KnowledgeUnitList>(`${doc(id)}/chunks?limit=${limit}`);

export const activatePersona = (id: string) =>
  apiJson<ApiRecord>(
    `${BASE}/knowledge/personas/${encodeURIComponent(id)}/activate`,
    {
      method: "POST",
    },
  );

export const listPersonaAssignments = () =>
  apiJson<{ data: AdapterPersonaAssignment[] }>(
    `${BASE}/knowledge/persona-assignments`,
  );

export const updatePersonaAssignment = (
  provider: AdapterProvider,
  personaId: string | null,
) =>
  apiJson<AdapterPersonaAssignment>(
    `${BASE}/knowledge/persona-assignments/${encodeURIComponent(provider)}`,
    {
      method: "PUT",
      body: JSON.stringify({ persona_id: personaId }),
      headers: { "Content-Type": "application/json" },
    },
  );

/** Download the persona template markdown file. */
export const downloadPersonaTemplate = () =>
  apiRequest(`${BASE}/knowledge/personas/format/template`);

export type ImportedPersona = {
  name: string;
  body_md: string;
  notes?: string | null;
  followup_rules?: PersonaFollowupRules;
};

/** Import (upload) a persona from a markdown file. Creates or overwrites by slug. */
export const importPersona = (file: File, knowledgeBaseId: string) => {
  const form = new FormData();
  form.append("file", file);
  return apiJson<ImportedPersona>(
    `${BASE}/knowledge/personas/import?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
    {
    method: "POST",
    body: form,
    },
  );
};

export const reindexProject = (id: string) =>
  apiJson<ApiRecord>(
    `${BASE}/knowledge/projects/${encodeURIComponent(id)}/reindex`,
    {
      method: "POST",
    },
  );

// --- Project-owned exclusive knowledge modes ---

export type KnowledgeCategoryKey =
  | "jobs"
  | "compensation"
  | "requirements"
  | "work_schedules"
  | "benefits"
  | "accommodation"
  | "meals"
  | "transportation"
  | "insurance"
  | "application"
  | "contacts"
  | "faq";

export type KnowledgeCategoryStatus = {
  key: KnowledgeCategoryKey;
  label_vi: string;
  active_revision_id?: string | null;
  active_revision_no?: number | null;
  active_checksum?: string | null;
  latest_revision_id?: string | null;
  latest_revision_no?: number | null;
  status?: "STAGED" | "PROCESSING" | "ACTIVE" | "ARCHIVED" | "FAILED" | "CLEARED" | null;
  updated_at?: string | null;
  error_message?: string | null;
};

export type KnowledgeCategoryCatalog = {
  data: KnowledgeCategoryStatus[];
  total: number;
};

export type KnowledgeCategoryTemplate = {
  key: KnowledgeCategoryKey;
  label_vi: string;
  filename: string;
  content: string;
};

export type KnowledgeCategorySource = {
  key: KnowledgeCategoryKey;
  label_vi: string;
  revision_id: string;
  revision_no: number;
  filename: string;
  content: string;
  checksum: string;
  updated_at: string;
};

export type KnowledgeCategoryRevision = {
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
};

export type SinglePageKnowledge = {
  id: string;
  knowledge_base_id: string;
  filename: string;
  text: string;
  char_count: number;
  line_count: number;
  content_sha256: string;
  updated_at: string;
};

export const getProjectKnowledgeCategories = (projectId: string) =>
  apiJson<KnowledgeCategoryCatalog>(`${proj(projectId)}/categories`);

export const getProjectKnowledgeCategoryTemplate = (
  projectId: string,
  key: KnowledgeCategoryKey,
) =>
  apiJson<KnowledgeCategoryTemplate>(
    `${proj(projectId)}/categories/${encodeURIComponent(key)}/template`,
  );

export const getProjectKnowledgeCategorySource = (
  projectId: string,
  key: KnowledgeCategoryKey,
) =>
  apiJson<KnowledgeCategorySource>(
    `${proj(projectId)}/categories/${encodeURIComponent(key)}`,
  );

export const replaceProjectKnowledgeCategory = (
  projectId: string,
  key: KnowledgeCategoryKey,
  filename: string,
  content: string,
) =>
  apiJson<{ revision: KnowledgeCategoryRevision; job_id: string }>(
    `${proj(projectId)}/categories/${encodeURIComponent(key)}`,
    { method: "PUT", body: { filename, content } },
  );

export const uploadProjectKnowledgeCategory = (
  projectId: string,
  key: KnowledgeCategoryKey,
  file: File,
) => {
  const form = new FormData();
  form.append("file", file);
  return apiJson<{ revision: KnowledgeCategoryRevision; job_id: string }>(
    `${proj(projectId)}/categories/${encodeURIComponent(key)}/upload`,
    { method: "POST", body: form },
  );
};

export const clearProjectKnowledgeCategory = (
  projectId: string,
  key: KnowledgeCategoryKey,
) =>
  apiJson<KnowledgeCategoryRevision>(
    `${proj(projectId)}/categories/${encodeURIComponent(key)}/clear`,
    { method: "POST", body: { confirmation: "CLEAR" } },
  );

export const getProjectSinglePage = (projectId: string) =>
  apiJson<SinglePageKnowledge>(`${proj(projectId)}/single-page`);

export const replaceProjectSinglePage = (
  projectId: string,
  filename: string,
  text: string,
) =>
  apiJson<Omit<SinglePageKnowledge, "text"> & { text?: string }>(
    `${proj(projectId)}/single-page`,
    { method: "PUT", body: { filename, text } },
  );

// --- Worker product features (active per-project feature values) ---

export const getProjectFeatures = (id: string) =>
  apiJson<ProductFeatureList>(`${proj(id)}/features`);

export const getProjectBusTimetable = (
  id: string,
  { page = 1, perPage = 6 }: { page?: number; perPage?: number } = {},
) =>
  apiJson<BusTimetableList>(
    `${proj(id)}/bus-timetable?page=${page}&per_page=${perPage}`,
  );

export const getProjectFaq = (id: string, limit = 12) =>
  apiJson<ProjectFaqList>(`${proj(id)}/faq?limit=${limit}`);

export type ProjectFaqPayload = Pick<
  ProjectFaq,
  | "question"
  | "answer"
  | "question_variants"
  | "required_terms"
  | "forbidden_terms"
>;

export const createProjectFaq = (
  projectId: string,
  payload: ProjectFaqPayload,
) =>
  apiJson<ProjectFaq>(`${proj(projectId)}/faq`, {
    method: "POST",
    body: payload,
  });

export const updateProjectFaq = (
  projectId: string,
  faqId: string,
  payload: Partial<ProjectFaqPayload>,
) =>
  apiJson<ProjectFaq>(`${proj(projectId)}/faq/${encodeURIComponent(faqId)}`, {
    method: "PATCH",
    body: payload,
  });

export const deleteProjectFaq = (projectId: string, faqId: string) =>
  apiRequest(`${proj(projectId)}/faq/${encodeURIComponent(faqId)}`, {
    method: "DELETE",
  }).then((response) => {
    if (!response.ok) {
      throw new ApiError(response.status, "Không xóa được FAQ.");
    }
  });

/** Synchronously re-extract active features from the project's latest posting (~5-10s). */
export const extractProjectFeatures = (id: string) =>
  apiJson<ProductFeatureList>(`${proj(id)}/features/extract`, {
    method: "POST",
  });

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

export const updateProjectFeature = (
  projectId: string,
  featureId: string,
  patch: FeaturePatch,
) =>
  apiJson<ProductFeature>(
    `${proj(projectId)}/features/${encodeURIComponent(featureId)}`,
    { method: "PATCH", body: patch },
  );

// --- External knowledge-source sync (public Google Sheet → category revision) ---
//
// Public link is a sibling of file upload. The admin pastes a Google Sheet URL,
// picks a target category, and either imports once or enables daily auto-sync.

const GOOGLE_SHEET_HOSTS = new Set([
  "docs.google.com",
  "sheets.googleapis.com",
  "googleusercontent.com",
]);

const SINGLE_PAGE_EXTERNAL_SOURCES_PATH = (projectId: string) =>
  `${proj(projectId)}/single-page/external-sources`;

/** Client-side mirror of the backend SSRF allow-list (defense-in-depth). */
export const isValidGoogleSheetUrl = (url: string): boolean => {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  if (!host) return false;
  // Reject IP literals.
  if (/^\d+(\.\d+){3}$/.test(host) || host.includes(":")) return false;
  return (
    GOOGLE_SHEET_HOSTS.has(host) ||
    [...GOOGLE_SHEET_HOSTS].some((allowed) => host.endsWith(`.${allowed}`))
  );
};

export type GoogleSheetGidSource = "query" | "fragment";

export type GoogleSheetGidResolution =
  | {
      ok: true;
      gid: number;
      source: GoogleSheetGidSource;
    }
  | {
      ok: false;
      reason: "missing" | "invalid" | "conflict";
      message: string;
    };

const extractSheetGidValues = (
  raw: string,
  source: GoogleSheetGidSource,
): string[] => {
  const value =
    source === "fragment" ? raw.trim().replace(/^#/, "") : raw.trim();
  if (!value) return [];
  return new URLSearchParams(value).getAll("gid").map((entry) => entry.trim());
};

const normalizeSingleGidValue = (
  values: string[],
): { ok: true; value: string | null } | { ok: false } => {
  if (values.length === 0) {
    return { ok: true, value: null };
  }
  const uniqueValues = [...new Set(values)];
  if (uniqueValues.length !== 1) {
    return { ok: false };
  }
  return { ok: true, value: uniqueValues[0] ?? null };
};

const parseGoogleSheetGidValue = (value: string): number | null => {
  if (!/^\d+$/.test(value)) return null;
  try {
    const asBigInt = BigInt(value);
    if (asBigInt > BigInt(Number.MAX_SAFE_INTEGER)) return null;
    return Number(value);
  } catch {
    return null;
  }
};

/**
 * Validate that the URL contains exactly one explicit gid in either the query
 * string or fragment. `#gid=` takes precedence, but conflicting values are
 * rejected so the preview matches what the backend will persist.
 */
export const resolveGoogleSheetGid = (
  url: string,
): GoogleSheetGidResolution => {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return {
      ok: false,
      reason: "invalid",
      message: "Link không hợp lệ.",
    };
  }

  const queryResult = normalizeSingleGidValue(
    extractSheetGidValues(parsed.search, "query"),
  );
  const fragmentResult = normalizeSingleGidValue(
    extractSheetGidValues(parsed.hash, "fragment"),
  );

  if (!queryResult.ok || !fragmentResult.ok) {
    return {
      ok: false,
      reason: "conflict",
      message:
        "Link có nhiều giá trị gid khác nhau. Hãy giữ lại đúng một gid.",
    };
  }

  const queryValue = queryResult.value;
  const fragmentValue = fragmentResult.value;

  if (queryValue && fragmentValue && queryValue !== fragmentValue) {
    return {
      ok: false,
      reason: "conflict",
      message:
        "gid ở query và fragment đang khác nhau. Hãy giữ lại một giá trị duy nhất.",
    };
  }

  const chosenValue = fragmentValue ?? queryValue;
  const source: GoogleSheetGidSource = fragmentValue ? "fragment" : "query";

  if (!chosenValue) {
    return {
      ok: false,
      reason: "missing",
      message:
        "Link phải có gid rõ ràng trong `?gid=` hoặc `#gid=` để chọn đúng trang tính.",
    };
  }

  const gid = parseGoogleSheetGidValue(chosenValue);
  if (gid === null) {
    return {
      ok: false,
      reason: "invalid",
      message:
        "gid phải là số nguyên không âm và nằm trong phạm vi an toàn của JavaScript.",
    };
  }

  return {
    ok: true,
    gid,
    source,
  };
};

export type ExternalSourceSyncState = {
  id: string;
  project_id: string;
  category_key: KnowledgeCategoryKey;
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
};

export type SinglePageExternalSourceSyncState = {
  id: string;
  project_id: string;
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
};

export type ExternalSourceCreatePayload = {
  source_kind?: string;
  category_key: KnowledgeCategoryKey;
  sheet_url: string;
  sheet_gid?: number;
  auto_sync_enabled?: boolean;
};

export type SinglePageExternalSourceCreatePayload = {
  sheet_url: string;
  auto_sync_enabled?: boolean;
};

export const listExternalSources = (projectId: string) =>
  apiJson<ExternalSourceSyncState[]>(
    `${proj(projectId)}/external-sources`,
  );

export const createExternalSource = (
  projectId: string,
  payload: ExternalSourceCreatePayload,
) =>
  apiJson<ExternalSourceSyncState>(
    `${proj(projectId)}/external-sources`,
    { method: "POST", body: payload },
  );

export const runExternalSourceNow = (projectId: string, id: string) =>
  apiJson<{ job_id: string }>(
    `${proj(projectId)}/external-sources/${encodeURIComponent(id)}/run-now`,
    { method: "POST" },
  );

export const deleteExternalSource = (projectId: string, id: string) =>
  apiRequest(
    `${proj(projectId)}/external-sources/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  ).then((response) => {
    if (!response.ok) {
      throw new ApiError(response.status, "Không xóa được nguồn đồng bộ.");
    }
  });

export const listSinglePageExternalSources = (projectId: string) =>
  apiJson<SinglePageExternalSourceSyncState[]>(
    SINGLE_PAGE_EXTERNAL_SOURCES_PATH(projectId),
  );

export const createSinglePageExternalSource = (
  projectId: string,
  payload: SinglePageExternalSourceCreatePayload,
) =>
  apiJson<SinglePageExternalSourceSyncState>(
    SINGLE_PAGE_EXTERNAL_SOURCES_PATH(projectId),
    { method: "POST", body: payload },
  );

export const runSinglePageExternalSourceNow = (
  projectId: string,
  id: string,
) =>
  apiJson<{ job_id: string }>(
    `${SINGLE_PAGE_EXTERNAL_SOURCES_PATH(projectId)}/${encodeURIComponent(id)}/run-now`,
    { method: "POST" },
  );

export const deleteSinglePageExternalSource = (projectId: string, id: string) =>
  apiRequest(
    `${SINGLE_PAGE_EXTERNAL_SOURCES_PATH(projectId)}/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  ).then((response) => {
    if (!response.ok) {
      throw new ApiError(response.status, "Không xóa được nguồn đồng bộ.");
    }
  });
