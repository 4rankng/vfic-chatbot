import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  apiRequest: vi.fn(),
}));

vi.mock("@/components/atomic-crm/providers/rest/api", () => ({
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

import * as knowledgeService from "./knowledgeService";

beforeEach(() => {
  mocks.apiJson.mockReset();
  mocks.apiRequest.mockReset();
});

describe("createAndIngestKnowledgeBaseVersion", () => {
  it("stages every upload in a KB version before enqueuing ingest", async () => {
    mocks.apiJson
      .mockResolvedValueOnce({ id: "version-1", project_id: "project-1", status: "DRAFT" })
      .mockResolvedValueOnce({
        job_id: "job-1",
        kb_version_id: "version-1",
        status: "PENDING",
      });
    mocks.apiRequest.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "file-1" }),
    });
    const file = new File(["Nội dung tuyển dụng"], "tuyen-dung.md", {
      type: "text/markdown",
    });

    await expect(
      knowledgeService.createAndIngestKnowledgeBaseVersion("project-1", file),
    ).resolves.toMatchObject({ job_id: "job-1", kb_version_id: "version-1" });

    expect(mocks.apiJson).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/projects/project-1/kb/versions",
      { method: "POST" },
    );
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/knowledge/projects/project-1/kb/versions/version-1/files",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
    expect(mocks.apiJson).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge/projects/project-1/kb/versions/version-1/ingest",
      { method: "POST" },
    );
    expect(mocks.apiJson.mock.calls.flat().join(" ")).not.toContain(
      "/knowledge/documents/",
    );
  });

  it("does not expose generic-template or direct-upload client operations", () => {
    expect(knowledgeService).not.toHaveProperty("uploadKnowledgeFile");
    expect(knowledgeService).not.toHaveProperty("listIngestionTemplates");
    expect(knowledgeService).not.toHaveProperty("createIngestionTemplate");
    expect(knowledgeService).not.toHaveProperty("assignIngestionTemplate");
    expect(knowledgeService).not.toHaveProperty("listKnowledgeBaseVersionRuns");
    expect(knowledgeService).not.toHaveProperty("reviewKnowledgeIngestionRun");
  });
});

describe("reindexAllKnowledge", () => {
  it("posts once to the bulk reindex endpoint", async () => {
    mocks.apiJson.mockResolvedValue({ status: "ok", queued: 7 });

    await expect(knowledgeService.reindexAllKnowledge()).resolves.toEqual({
      status: "ok",
      queued: 7,
    });

    expect(mocks.apiJson).toHaveBeenCalledTimes(1);
    expect(mocks.apiJson).toHaveBeenCalledWith(
      "/api/v1/knowledge/reindex-all",
      { method: "POST" },
    );
  });
});
