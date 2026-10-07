import { ApiError, apiJson, apiRequest } from "@/lib/apiClient";

import type {
  CancellationSignal,
  ProjectKnowledgePort,
} from "../application/project-knowledge-port";

const BASE = "/api/v1/knowledge/projects";
const projectPath = (projectId: string) =>
  `${BASE}/${encodeURIComponent(projectId)}`;
const DOCUMENT_UPLOAD_PATH = "/api/v1/knowledge/documents/upload-file";
const DOCUMENT_EXTRACT_PATH = "/api/v1/knowledge/documents/extract-text";

/** Multipart body for one source-file upload to the knowledge API. */
const fileForm = (file: { name: string; type: string; bytes: ArrayBuffer }) => {
  const form = new FormData();
  form.append("file", new Blob([file.bytes], { type: file.type }), file.name);
  return form;
};

/** The server's own Vietnamese rejection reason, when it gave one. */
const rejectionDetail = async (
  response: Response,
  fallback: string,
): Promise<string> => {
  let detail = "";
  try {
    const body = await response.json();
    detail =
      typeof body?.detail === "string"
        ? body.detail
        : JSON.stringify(body?.detail ?? body?.errors ?? body ?? "");
  } catch {
    detail = "";
  }
  return detail && detail !== "{}" ? `${fallback}: ${detail}` : fallback;
};

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

const exportFilename = (
  disposition: string | null,
  fallback = "project-knowledge.md",
): string => {
  const encoded = /(?:^|;)\s*filename\*\s*=\s*UTF-8'[^']*'([^;]+)/i.exec(
    disposition ?? "",
  )?.[1];
  const plain = /(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(
    disposition ?? "",
  );
  let decoded: string | undefined;
  try {
    if (encoded) decoded = decodeURIComponent(encoded.trim());
  } catch {
    // A malformed extended filename can still have a valid ASCII fallback.
  }
  for (const candidate of [decoded, plain?.[1], plain?.[2]]) {
    const filename = candidate?.trim();
    if (
      filename &&
      !filename.startsWith(".") &&
      filename.length <= 180 &&
      !/[<>:"/\\|?*]/.test(filename) &&
      ![...filename].some((character) => character.charCodeAt(0) < 32) &&
      /\.md$/i.test(filename)
    )
      return filename;
  }
  return fallback;
};

export const httpProjectKnowledgeAdapter: ProjectKnowledgePort = Object.freeze({
  getCategories: (projectId) => apiJson(`${projectPath(projectId)}/categories`),

  getCategoryTemplate: (projectId, key) =>
    apiJson(
      `${projectPath(projectId)}/categories/${encodeURIComponent(key)}/template`,
    ),

  getFullTemplate: async (projectId, signal) => {
    const native = nativeSignal(signal);
    try {
      const response = await apiRequest(
        `${projectPath(projectId)}/knowledge-template`,
        { headers: { Accept: "text/plain" }, signal: native.signal },
      );
      if (!response.ok)
        throw new ApiError(
          response.status,
          "Chưa tải được mẫu KB. Vui lòng thử lại.",
        );
      if (
        !/^text\/(?:plain|markdown)(?:\s*;|$)/i.test(
          response.headers.get("Content-Type") ?? "",
        )
      )
        throw new ApiError(
          502,
          "Mẫu KB không đúng định dạng. Vui lòng thử lại.",
        );
      const content = await response.text();
      if (!content.trim())
        throw new ApiError(502, "Mẫu KB chưa có nội dung. Vui lòng thử lại.");
      return {
        filename: exportFilename(
          response.headers.get("Content-Disposition"),
          "mau-kb-du-an.md",
        ),
        content,
      };
    } finally {
      native.dispose();
    }
  },

  getKnowledgeExport: async (projectId, signal) => {
    const native = nativeSignal(signal);
    try {
      const response = await apiRequest(
        `${projectPath(projectId)}/knowledge-export`,
        { headers: { Accept: "text/markdown" }, signal: native.signal },
      );
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: "Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại.",
          403: "Bạn không có quyền xuất KB của dự án này.",
          404: "Không tìm thấy dự án. Vui lòng làm mới danh sách.",
          409: "Dự án chưa có kiến thức đã lưu để xuất.",
        };
        throw new ApiError(
          response.status,
          messages[response.status] ?? "Chưa xuất được KB. Vui lòng thử lại.",
        );
      }
      if (
        !/^text\/markdown(?:\s*;|$)/i.test(
          response.headers.get("Content-Type") ?? "",
        )
      )
        throw new ApiError(
          502,
          "Tệp KB không đúng định dạng. Vui lòng thử lại.",
        );
      const content = await response.text();
      if (!content.trim())
        throw new ApiError(409, "Dự án chưa có kiến thức đã lưu để xuất.");
      return {
        filename: exportFilename(response.headers.get("Content-Disposition")),
        content,
      };
    } finally {
      native.dispose();
    }
  },

  getCategorySource: (projectId, key) =>
    apiJson(`${projectPath(projectId)}/categories/${encodeURIComponent(key)}`),

  replaceCategory: (projectId, key, filename, content) =>
    apiJson(`${projectPath(projectId)}/categories/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: { filename, content },
    }),

  clearCategory: (projectId, key, expectedRevisionNo) =>
    apiJson(
      `${projectPath(projectId)}/categories/${encodeURIComponent(key)}/clear${expectedRevisionNo === undefined ? "" : `?expected_revision_no=${expectedRevisionNo}`}`,
      { method: "POST", body: { confirmation: "CLEAR" } },
    ),

  cutoverCategories: (projectId) =>
    apiJson(`${projectPath(projectId)}/categories/cutover`, {
      method: "POST",
      body: { confirmation: "CUTOVER" },
    }),

  uploadDocument: async (projectId, file) => {
    const form = fileForm(file);
    form.append("project_id", projectId);
    // A browser preview recognizes only some layouts. Always classify the
    // entire original source on the worker, even when preview found headings.
    form.append("auto_extract", "true");
    const response = await apiRequest(DOCUMENT_UPLOAD_PATH, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      // Surface the server's own rejection (plan mismatch, category contract
      // errors) instead of a generic string — the precise Vietnamese reason is
      // the only thing that makes the failure fixable from the UI.
      throw new ApiError(
        response.status,
        await rejectionDetail(
          response,
          "Không lưu được tệp vào tài liệu dự án.",
        ),
      );
    }
    return response.json();
  },

  extractDocumentText: async (file) => {
    const response = await apiRequest(DOCUMENT_EXTRACT_PATH, {
      method: "POST",
      body: fileForm(file),
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        await rejectionDetail(response, "Không đọc được nội dung tệp."),
      );
    }
    const body = (await response.json()) as { text?: unknown };
    if (typeof body?.text !== "string") {
      throw new ApiError(
        502,
        "Phản hồi đọc nội dung tệp không đúng định dạng.",
      );
    }
    return body.text;
  },

  getTrainingDocument: (documentId) =>
    apiJson(`/api/v1/knowledge/documents/${encodeURIComponent(documentId)}`),

  getSinglePage: (projectId) =>
    apiJson(`${projectPath(projectId)}/single-page`),

  replaceSinglePage: (projectId, filename, text) =>
    apiJson(`${projectPath(projectId)}/single-page`, {
      method: "PUT",
      body: { filename, text },
    }),

  updateProjectDiscoveryCard: (projectId, patch) =>
    apiJson(projectPath(projectId), { method: "PATCH", body: patch }),

  getFeatures: (projectId) => apiJson(`${projectPath(projectId)}/features`),

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
});
