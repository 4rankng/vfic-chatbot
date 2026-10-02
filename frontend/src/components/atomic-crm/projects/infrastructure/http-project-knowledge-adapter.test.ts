import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  apiRequest: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public readonly status: number,
      message: string,
    ) {
      super(message);
    }
  },
  apiJson: mocks.apiJson,
  apiRequest: mocks.apiRequest,
}));

import { httpProjectKnowledgeAdapter } from "./http-project-knowledge-adapter";

beforeEach(() => {
  mocks.apiJson.mockReset();
  mocks.apiRequest.mockReset();
});

describe("HTTP project-knowledge adapter", () => {
  it("downloads the full template as text rather than parsing its Markdown as JSON", async () => {
    const content = "# Mẫu KB\n## salary_income\n## recruitment_contact";
    mocks.apiRequest.mockResolvedValue(
      new Response(content, {
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Content-Disposition": 'attachment; filename="mau-kb-du-an.md"',
        },
      }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getFullTemplate("project / 1"),
    ).resolves.toEqual({ filename: "mau-kb-du-an.md", content });
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project%20%2F%201/knowledge-template",
      { headers: { Accept: "text/plain" }, signal: undefined },
    );
    expect(mocks.apiJson).not.toHaveBeenCalled();
  });

  it("preserves the template filename when its attachment header is unavailable", async () => {
    mocks.apiRequest.mockResolvedValue(
      new Response("Template content", {
        headers: { "Content-Type": "text/plain" },
      }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getFullTemplate("project-1"),
    ).resolves.toEqual({
      filename: "mau-kb-du-an.md",
      content: "Template content",
    });
  });

  it("rejects a failed, empty or non-text template response", async () => {
    mocks.apiRequest.mockResolvedValueOnce(
      new Response("Server details", { status: 500 }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getFullTemplate("project-1"),
    ).rejects.toMatchObject({
      message: "Chưa tải được mẫu KB. Vui lòng thử lại.",
    });
    mocks.apiRequest.mockResolvedValueOnce(
      new Response(" \n", { headers: { "Content-Type": "text/plain" } }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getFullTemplate("project-1"),
    ).rejects.toMatchObject({
      message: "Mẫu KB chưa có nội dung. Vui lòng thử lại.",
    });
    mocks.apiRequest.mockResolvedValueOnce(
      new Response("<html>Error</html>", {
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getFullTemplate("project-1"),
    ).rejects.toMatchObject({
      message: "Mẫu KB không đúng định dạng. Vui lòng thử lại.",
    });
  });

  it("exports the UTF-8 Markdown attachment through the authenticated client", async () => {
    mocks.apiRequest.mockResolvedValue(
      new Response("# Dự án\nKiến thức đã lưu", {
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Disposition":
            "attachment; filename*=UTF-8''kb-d%E1%BB%B1-%C3%A1n.md",
        },
      }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getKnowledgeExport("project / 1"),
    ).resolves.toEqual({
      filename: "kb-dự-án.md",
      content: "# Dự án\nKiến thức đã lưu",
    });
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project%20%2F%201/knowledge-export",
      { headers: { Accept: "text/markdown" }, signal: undefined },
    );
    expect(mocks.apiJson).not.toHaveBeenCalled();
  });

  it.each([
    ['attachment; filename="kb-project.md"', "kb-project.md"],
    [
      "attachment; filename*=UTF-8''%ZZ; filename=kb-project.md",
      "kb-project.md",
    ],
    ['attachment; filename="../../unsafe.md"', "project-knowledge.md"],
    ['attachment; filename="unsafe.html"', "project-knowledge.md"],
    [null, "project-knowledge.md"],
  ])(
    "keeps an attachment filename safe when its header is %s",
    async (header, filename) => {
      const headers: Record<string, string> = {
        "Content-Type": "text/markdown",
      };
      if (header) headers["Content-Disposition"] = header;
      mocks.apiRequest.mockResolvedValue(
        new Response("Saved knowledge", { headers }),
      );
      await expect(
        httpProjectKnowledgeAdapter.getKnowledgeExport("project-1"),
      ).resolves.toEqual({ filename, content: "Saved knowledge" });
    },
  );

  it("rejects an empty or non-Markdown success without returning a fake export", async () => {
    mocks.apiRequest.mockResolvedValueOnce(
      new Response(" \n", { headers: { "Content-Type": "text/markdown" } }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getKnowledgeExport("project-1"),
    ).rejects.toMatchObject({
      status: 409,
      message: "Dự án chưa có kiến thức đã lưu để xuất.",
    });
    mocks.apiRequest.mockResolvedValueOnce(
      new Response("<html>Error</html>", {
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(
      httpProjectKnowledgeAdapter.getKnowledgeExport("project-1"),
    ).rejects.toMatchObject({
      status: 502,
      message: "Tệp KB không đúng định dạng. Vui lòng thử lại.",
    });
  });

  it.each([
    [401, "Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại."],
    [403, "Bạn không có quyền xuất KB của dự án này."],
    [404, "Không tìm thấy dự án. Vui lòng làm mới danh sách."],
    [409, "Dự án chưa có kiến thức đã lưu để xuất."],
    [500, "Chưa xuất được KB. Vui lòng thử lại."],
  ])(
    "reports export HTTP %i without exposing the response body",
    async (status, message) => {
      mocks.apiRequest.mockResolvedValue(
        new Response("Internal server details", { status: status as number }),
      );
      await expect(
        httpProjectKnowledgeAdapter.getKnowledgeExport("project-1"),
      ).rejects.toMatchObject({ status, message });
    },
  );

  it("forwards cancellation to export and disposes its subscription", async () => {
    const listeners = new Set<() => void>();
    mocks.apiRequest.mockImplementation(async (_path, options) => {
      listeners.forEach((abort) => abort());
      expect(options.signal.aborted).toBe(true);
      return new Response("Saved knowledge", {
        headers: { "Content-Type": "text/markdown" },
      });
    });
    await httpProjectKnowledgeAdapter.getKnowledgeExport("project-1", {
      aborted: false,
      onAbort: (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    });
    expect(listeners.size).toBe(0);
  });

  it("uploads the intact source for full backend extraction without a browser category plan", async () => {
    const receipt = {
      id: "document-1",
      project_training: { status: "QUEUED" },
    };
    mocks.apiRequest.mockResolvedValue({ ok: true, json: async () => receipt });

    const result = await httpProjectKnowledgeAdapter.uploadDocument(
      "project-1",
      {
        name: "brief.txt",
        type: "text/plain",
        bytes: new TextEncoder().encode("brief").buffer,
      },
    );

    expect(result).toEqual(receipt);
    const [path, options] = mocks.apiRequest.mock.calls[0];
    expect(path).toBe("/api/v1/knowledge/documents/upload-file");
    expect(options.body.get("project_id")).toBe("project-1");
    expect(options.body.get("auto_extract")).toBe("true");
    expect(options.body.has("category_plan")).toBe(false);
    expect(options.body.get("file").name).toBe("brief.txt");
    expect(await options.body.get("file").text()).toBe("brief");
  });

  it("reads actual training checkpoints from the retained document receipt", async () => {
    await httpProjectKnowledgeAdapter.getTrainingDocument("document / 1");
    expect(mocks.apiJson).toHaveBeenCalledWith(
      "/api/v1/knowledge/documents/document%20%2F%201",
    );
  });

  it("guards migration empty initialization while preserving ordinary clear requests", async () => {
    mocks.apiJson.mockResolvedValue({});
    await httpProjectKnowledgeAdapter.clearCategory(
      "project / 1",
      "benefits",
      0,
    );
    await httpProjectKnowledgeAdapter.clearCategory("project / 1", "benefits");
    expect(mocks.apiJson.mock.calls).toEqual([
      [
        "/api/v1/knowledge/projects/project%20%2F%201/categories/benefits/clear?expected_revision_no=0",
        { method: "POST", body: { confirmation: "CLEAR" } },
      ],
      [
        "/api/v1/knowledge/projects/project%20%2F%201/categories/benefits/clear",
        { method: "POST", body: { confirmation: "CLEAR" } },
      ],
    ]);
  });

  it("preserves category, feature, FAQ and bus endpoint contracts", async () => {
    mocks.apiJson.mockResolvedValue({});

    await httpProjectKnowledgeAdapter.getCategories("project / 1");
    await httpProjectKnowledgeAdapter.extractFeatures("project-1");
    await httpProjectKnowledgeAdapter.updateFeature("project-1", "feature/1", {
      value_text: "Có xe",
    });
    await httpProjectKnowledgeAdapter.getFaq("project-1", 50);
    await httpProjectKnowledgeAdapter.getBusTimetable("project-1", 2, 6);

    expect(mocks.apiJson.mock.calls).toEqual([
      ["/api/v1/knowledge/projects/project%20%2F%201/categories"],
      [
        "/api/v1/knowledge/projects/project-1/features/extract",
        { method: "POST" },
      ],
      [
        "/api/v1/knowledge/projects/project-1/features/feature%2F1",
        { method: "PATCH", body: { value_text: "Có xe" } },
      ],
      ["/api/v1/knowledge/projects/project-1/faq?limit=50"],
      ["/api/v1/knowledge/projects/project-1/bus-timetable?page=2&per_page=6"],
    ]);
  });

  it("keeps external-source abort and route behavior in infrastructure", async () => {
    mocks.apiJson.mockResolvedValue([]);
    const listeners = new Set<() => void>();

    await httpProjectKnowledgeAdapter.listSinglePageExternalSources(
      "project-1",
      {
        aborted: false,
        onAbort: (listener) => {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
      },
    );

    expect(mocks.apiJson).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project-1/single-page/external-sources",
      { signal: expect.any(AbortSignal) },
    );
    expect(listeners.size).toBe(0);
  });

  it("replaces manually edited category content through the JSON endpoint", async () => {
    mocks.apiJson.mockResolvedValue({});

    await httpProjectKnowledgeAdapter.replaceCategory(
      "project-1",
      "jobs",
      "jobs.yaml",
      "jobs:\n  - id: operator",
    );

    expect(mocks.apiJson).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project-1/categories/jobs",
      {
        method: "PUT",
        body: {
          filename: "jobs.yaml",
          content: "jobs:\n  - id: operator",
        },
      },
    );
  });
});
