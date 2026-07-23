import { ApiError, apiJson, apiRequest } from "@/lib/apiClient";

import type {
  CancellationSignal,
  ProjectKnowledgePort,
} from "../application/project-knowledge-port";

const BASE = "/api/v1/knowledge/projects";
const projectPath = (projectId: string) =>
  `${BASE}/${encodeURIComponent(projectId)}`;
const singlePageSourcesPath = (projectId: string) =>
  `${projectPath(projectId)}/single-page/external-sources`;

const nativeSignal = (
  signal?: CancellationSignal,
): Readonly<{ signal?: AbortSignal; dispose: () => void }> => {
  if (!signal) return { dispose: () => undefined };
  const controller = new AbortController();
  if (signal.aborted) controller.abort();
  const dispose = signal.onAbort(() => controller.abort());
  return { signal: controller.signal, dispose };
};

const deleteRequest = async (path: string, message: string): Promise<void> => {
  const response = await apiRequest(path, { method: "DELETE" });
  if (!response.ok) throw new ApiError(response.status, message);
};

export const httpProjectKnowledgeAdapter: ProjectKnowledgePort = Object.freeze({
  getCategories: (projectId) =>
    apiJson(`${projectPath(projectId)}/categories`),

  getCategoryTemplate: (projectId, key) =>
    apiJson(
      `${projectPath(projectId)}/categories/${encodeURIComponent(key)}/template`,
    ),

  getCategorySource: (projectId, key) =>
    apiJson(`${projectPath(projectId)}/categories/${encodeURIComponent(key)}`),

  uploadCategory: (projectId, key, file) => {
    const form = new FormData();
    form.append("file", new Blob([file.bytes], { type: file.type }), file.name);
    return apiJson(
      `${projectPath(projectId)}/categories/${encodeURIComponent(key)}/upload`,
      { method: "POST", body: form },
    );
  },

  getSinglePage: (projectId) =>
    apiJson(`${projectPath(projectId)}/single-page`),

  replaceSinglePage: (projectId, filename, text) =>
    apiJson(`${projectPath(projectId)}/single-page`, {
      method: "PUT",
      body: { filename, text },
    }),

  getFeatures: (projectId) =>
    apiJson(`${projectPath(projectId)}/features`),

  extractFeatures: (projectId) =>
    apiJson(`${projectPath(projectId)}/features/extract`, { method: "POST" }),

  updateFeature: (projectId, featureId, patch) =>
    apiJson(
      `${projectPath(projectId)}/features/${encodeURIComponent(featureId)}`,
      { method: "PATCH", body: patch },
    ),

  getBusTimetable: (projectId, page, perPage) =>
    apiJson(
      `${projectPath(projectId)}/bus-timetable?page=${page}&per_page=${perPage}`,
    ),

  getFaq: (projectId, limit) =>
    apiJson(`${projectPath(projectId)}/faq?limit=${limit}`),

  createFaq: (projectId, payload) =>
    apiJson(`${projectPath(projectId)}/faq`, {
      method: "POST",
      body: payload,
    }),

  updateFaq: (projectId, faqId, payload) =>
    apiJson(`${projectPath(projectId)}/faq/${encodeURIComponent(faqId)}`, {
      method: "PATCH",
      body: payload,
    }),

  deleteFaq: (projectId, faqId) =>
    deleteRequest(
      `${projectPath(projectId)}/faq/${encodeURIComponent(faqId)}`,
      "Không xóa được FAQ.",
    ),

  listExternalSources: async (projectId, signal) => {
    const native = nativeSignal(signal);
    try {
      return await apiJson(`${projectPath(projectId)}/external-sources`, {
        signal: native.signal,
      });
    } finally {
      native.dispose();
    }
  },

  createExternalSource: (projectId, payload) =>
    apiJson(`${projectPath(projectId)}/external-sources`, {
      method: "POST",
      body: payload,
    }),

  runExternalSourceNow: (projectId, sourceId) =>
    apiJson(
      `${projectPath(projectId)}/external-sources/${encodeURIComponent(sourceId)}/run-now`,
      { method: "POST" },
    ),

  deleteExternalSource: (projectId, sourceId) =>
    deleteRequest(
      `${projectPath(projectId)}/external-sources/${encodeURIComponent(sourceId)}`,
      "Không xóa được nguồn đồng bộ.",
    ),

  listSinglePageExternalSources: async (projectId, signal) => {
    const native = nativeSignal(signal);
    try {
      return await apiJson(singlePageSourcesPath(projectId), {
        signal: native.signal,
      });
    } finally {
      native.dispose();
    }
  },

  createSinglePageExternalSource: (projectId, payload) =>
    apiJson(singlePageSourcesPath(projectId), {
      method: "POST",
      body: payload,
    }),

  runSinglePageExternalSourceNow: (projectId, sourceId) =>
    apiJson(
      `${singlePageSourcesPath(projectId)}/${encodeURIComponent(sourceId)}/run-now`,
      { method: "POST" },
    ),

  deleteSinglePageExternalSource: (projectId, sourceId) =>
    deleteRequest(
      `${singlePageSourcesPath(projectId)}/${encodeURIComponent(sourceId)}`,
      "Không xóa được nguồn đồng bộ.",
    ),
});
