// Knowledge-base / project / persona action routes (VFIC FastAPI backend).
//
// These target the dedicated action endpoints (not the react-admin CRUD verbs),
// re-using the authenticated REST client. The knowledge upload is multipart.

import { apiJson } from "@/components/atomic-crm/providers/rest/api";

const BASE = "/api/v1";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ApiRecord = Record<string, any>;
const doc = (id: string) => `${BASE}/knowledge/documents/${encodeURIComponent(id)}`;

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

export const approveKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/approve`, { method: "POST" });

export const rejectKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/reject`, { method: "POST" });

export const reindexKnowledge = (id: string) =>
  apiJson<ApiRecord>(`${doc(id)}/reindex`, { method: "POST" });

export const activatePersona = (id: string) =>
  apiJson<ApiRecord>(`${BASE}/knowledge/personas/${encodeURIComponent(id)}/activate`, {
    method: "POST",
  });

export const reindexProject = (id: string) =>
  apiJson<ApiRecord>(`${BASE}/knowledge/projects/${encodeURIComponent(id)}/reindex`, {
    method: "POST",
  });
