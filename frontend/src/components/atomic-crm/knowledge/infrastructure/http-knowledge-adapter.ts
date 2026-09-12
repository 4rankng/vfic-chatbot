import { ApiError, apiJson, apiRequest } from "@/lib/apiClient";

import type { KnowledgePort } from "../application/knowledge-port";

const BASE = "/api/v1/knowledge";
const documentPath = (documentId: string) =>
  `${BASE}/documents/${encodeURIComponent(documentId)}`;
const projectPath = (projectId: string) =>
  `${BASE}/projects/${encodeURIComponent(projectId)}`;

export const httpKnowledgeAdapter = Object.freeze<KnowledgePort>({
  createVersion: (projectId) =>
    apiJson(`${projectPath(projectId)}/kb/versions`, { method: "POST" }),

  uploadVersionFile: async (projectId, versionId, file) => {
    const form = new FormData();
    form.append("file", new Blob([file.bytes], { type: file.type }), file.name);
    const response = await apiRequest(
      `${projectPath(projectId)}/kb/versions/${encodeURIComponent(versionId)}/files`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      throw new ApiError(
        response.status,
        "Không tải được tệp vào phiên bản KB.",
      );
    }
    return response.json() as Promise<Record<string, unknown>>;
  },

  ingestVersion: (projectId, versionId) =>
    apiJson(
      `${projectPath(projectId)}/kb/versions/${encodeURIComponent(versionId)}/ingest`,
      { method: "POST" },
    ),

  listVersions: (projectId) => apiJson(`${projectPath(projectId)}/kb/versions`),

  publishVersion: (projectId, versionId) =>
    apiJson(
      `${projectPath(projectId)}/kb/versions/${encodeURIComponent(versionId)}/publish`,
      { method: "POST" },
    ),

  downloadTemplate: async (kind) => {
    const response = await apiRequest(`${BASE}/format/template?kind=${kind}`);
    if (!response.ok) {
      throw new ApiError(response.status, "Không tải được mẫu định dạng.");
    }
    return response.text();
  },

  downloadRaw: async (documentId) => {
    const response = await apiRequest(`${documentPath(documentId)}/raw`);
    if (!response.ok) {
      throw new ApiError(response.status, "Không tải được tệp gốc.");
    }
    return {
      bytes: await response.arrayBuffer(),
      mediaType:
        response.headers.get("content-type") ?? "application/octet-stream",
    };
  },

  process: (documentId) =>
    apiJson(`${documentPath(documentId)}/process`, { method: "POST" }),
  archive: (documentId) =>
    apiJson(`${documentPath(documentId)}/archive`, { method: "POST" }),
  reindex: (documentId) =>
    apiJson(`${documentPath(documentId)}/reindex`, { method: "POST" }),
  reindexAll: () => apiJson(`${BASE}/reindex-all`, { method: "POST" }),
  getUnits: (documentId, limit) =>
    apiJson(`${documentPath(documentId)}/chunks?limit=${limit}`),
});
