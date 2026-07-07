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
  BusTimetableList,
  PersonaFollowupRules,
  ProductFeature,
  ProductFeatureList,
} from "@/components/atomic-crm/types";

const BASE = "/api/v1";

export type ApiRecord = Record<string, any>;
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
  source_name?: string | null;
  source_anchor?: string | null;
};

export type ProjectFaqList = {
  data: ProjectFaq[];
  total: number;
};

export const uploadKnowledgeFile = async (
  file: File,
  projectId?: string | null,
): Promise<ApiRecord> => {
  const form = new FormData();
  form.append("file", file);
  if (projectId) form.append("project_id", projectId);
  const response = await apiRequest(`${BASE}/knowledge/documents/upload-file`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      /* fall through to generic upload error */
    }
    const errors =
      typeof detail === "object" &&
      detail !== null &&
      "errors" in detail &&
      Array.isArray((detail as { errors?: unknown }).errors)
        ? ((detail as { errors: unknown[] }).errors
            .map((item) => String(item))
            .filter(Boolean) as string[])
        : [];
    const message =
      errors.length > 0
        ? `Tệp chưa ingest được:\n${errors.join("\n")}`
        : "Tải lên thất bại.";
    const error = new ApiError(response.status, message) as ApiError & {
      validationErrors?: string[];
    };
    error.validationErrors = errors;
    throw error;
  }
  return (await response.json()) as ApiRecord;
};

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

export const archiveKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/archive`, { method: "POST" });

export const reindexKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/reindex`, { method: "POST" });

export const getKnowledgeUnits = (id: string, limit = 50) =>
  apiJson<KnowledgeUnitList>(`${doc(id)}/chunks?limit=${limit}`);

export const activatePersona = (id: string) =>
  apiJson<ApiRecord>(
    `${BASE}/knowledge/personas/${encodeURIComponent(id)}/activate`,
    {
      method: "POST",
    },
  );

export const assignPersonaToAllProjects = (id: string) =>
  apiJson<{ updated: number }>(
    `${BASE}/knowledge/personas/${encodeURIComponent(id)}/assign-all-projects`,
    { method: "POST" },
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
export const importPersona = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiJson<ImportedPersona>(`${BASE}/knowledge/personas/import`, {
    method: "POST",
    body: form,
  });
};

export const reindexProject = (id: string) =>
  apiJson<ApiRecord>(
    `${BASE}/knowledge/projects/${encodeURIComponent(id)}/reindex`,
    {
      method: "POST",
    },
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

export type ProjectFaqPayload = Pick<ProjectFaq, "question" | "answer">;

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
