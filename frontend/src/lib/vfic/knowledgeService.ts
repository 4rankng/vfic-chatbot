// Knowledge-base / project / persona action routes (VFIC FastAPI backend).
//
// These target the dedicated action endpoints (not the react-admin CRUD verbs),
// re-using the authenticated REST client. The knowledge upload is multipart.

import { apiJson } from "@/components/atomic-crm/providers/rest/api";
import type { ProductFeature, ProductFeatureList } from "@/components/atomic-crm/types";

const BASE = "/api/v1";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ApiRecord = Record<string, any>;
const doc = (id: string) => `${BASE}/knowledge/documents/${encodeURIComponent(id)}`;
const proj = (id: string) => `${BASE}/knowledge/projects/${encodeURIComponent(id)}`;

export const uploadKnowledgeFile = async (
  file: File,
  projectId?: string | null,
): Promise<ApiRecord> => {
  const form = new FormData();
  form.append("file", file);
  if (projectId) form.append("project_id", projectId);
  return apiJson<ApiRecord>(`${BASE}/knowledge/documents/upload-file`, {
    method: "POST",
    body: form,
  });
};

export const processKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/process`, { method: "POST" });

export const archiveKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/archive`, { method: "POST" });

export const reindexKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/reindex`, { method: "POST" });

export const activatePersona = (id: string) =>
  apiJson<ApiRecord>(`${BASE}/knowledge/personas/${encodeURIComponent(id)}/activate`, {
    method: "POST",
  });

/**
 * Expand a short description into a full 7-part persona body via the
 * rule-expander LLM. Admin-only; the caller previews/edits before saving.
 */
export const generatePersona = (description: string) =>
  apiJson<{ body_md: string }>(`${BASE}/knowledge/personas/generate`, {
    method: "POST",
    body: { description },
  });

export const reindexProject = (id: string) =>
  apiJson<ApiRecord>(`${BASE}/knowledge/projects/${encodeURIComponent(id)}/reindex`, {
    method: "POST",
  });

// --- Worker product features (the 16 per-project feature values) ---

export const getProjectFeatures = (id: string) =>
  apiJson<ProductFeatureList>(`${proj(id)}/features`);

/** Synchronously re-extract the 16 features from the project's latest posting (~5-10s). */
export const extractProjectFeatures = (id: string) =>
  apiJson<ProductFeatureList>(`${proj(id)}/features/extract`, { method: "POST" });

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

export const updateProjectFeature = (projectId: string, featureId: string, patch: FeaturePatch) =>
  apiJson<ProductFeature>(
    `${proj(projectId)}/features/${encodeURIComponent(featureId)}`,
    { method: "PATCH", body: patch },
  );
