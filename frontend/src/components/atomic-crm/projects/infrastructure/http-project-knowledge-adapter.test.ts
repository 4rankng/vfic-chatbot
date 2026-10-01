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
  it("uploads the retained file and all category proposals in one durable request", async () => {
    const receipt = {
      id: "document-1",
      project_training: { status: "QUEUED" },
    };
    mocks.apiRequest.mockResolvedValue({ ok: true, json: async () => receipt });
    const writes = [
      {
        key: "jobs" as const,
        filename: "jobs.md",
        content: "source-derived category",
      },
    ];

    const result = await httpProjectKnowledgeAdapter.uploadDocument(
      "project-1",
      {
        name: "brief.txt",
        type: "text/plain",
        bytes: new TextEncoder().encode("brief").buffer,
      },
      writes,
    );

    expect(result).toEqual(receipt);
    const [path, options] = mocks.apiRequest.mock.calls[0];
    expect(path).toBe("/api/v1/knowledge/documents/upload-file");
    expect(options.body.get("project_id")).toBe("project-1");
    expect(JSON.parse(options.body.get("category_plan"))).toEqual({ writes });
    expect(options.body.get("file").name).toBe("brief.txt");
  });

  it("reads actual training checkpoints from the retained document receipt", async () => {
    await httpProjectKnowledgeAdapter.getTrainingDocument("document / 1");
    expect(mocks.apiJson).toHaveBeenCalledWith(
      "/api/v1/knowledge/documents/document%20%2F%201",
    );
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
