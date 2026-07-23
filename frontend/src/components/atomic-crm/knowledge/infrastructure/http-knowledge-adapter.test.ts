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

import { httpKnowledgeAdapter } from "./http-knowledge-adapter";

beforeEach(() => {
  mocks.apiJson.mockReset();
  mocks.apiRequest.mockReset();
});

describe("HTTP knowledge adapter", () => {
  it("preserves the versioned upload and publish routes", async () => {
    mocks.apiJson.mockResolvedValue({});
    mocks.apiRequest.mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });

    await httpKnowledgeAdapter.createVersion("project/1");
    await httpKnowledgeAdapter.uploadVersionFile("project/1", "version/1", {
      name: "source.md",
      type: "text/markdown",
      bytes: new ArrayBuffer(1),
    });
    await httpKnowledgeAdapter.ingestVersion("project/1", "version/1");
    await httpKnowledgeAdapter.publishVersion("project/1", "version/1");

    expect(mocks.apiJson.mock.calls).toEqual([
      [
        "/api/v1/knowledge/projects/project%2F1/kb/versions",
        { method: "POST" },
      ],
      [
        "/api/v1/knowledge/projects/project%2F1/kb/versions/version%2F1/ingest",
        { method: "POST" },
      ],
      [
        "/api/v1/knowledge/projects/project%2F1/kb/versions/version%2F1/publish",
        { method: "POST" },
      ],
    ]);
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project%2F1/kb/versions/version%2F1/files",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
  });
});
