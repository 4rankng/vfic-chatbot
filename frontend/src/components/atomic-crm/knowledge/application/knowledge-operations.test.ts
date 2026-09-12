import { describe, expect, it, vi } from "vitest";

import type { FileDownloadPort, KnowledgePort } from "./knowledge-port";
import { createKnowledgeOperations } from "./knowledge-operations";

const port = (): KnowledgePort => ({
  createVersion: vi.fn().mockResolvedValue({
    id: "version-1",
    project_id: "project-1",
    status: "DRAFT",
    version_no: 1,
  }),
  uploadVersionFile: vi.fn().mockResolvedValue({ id: "file-1" }),
  ingestVersion: vi.fn().mockResolvedValue({
    job_id: "job-1",
    status: "PENDING",
    kb_version_id: "version-1",
  }),
  listVersions: vi.fn(),
  publishVersion: vi.fn(),
  downloadTemplate: vi.fn(),
  downloadRaw: vi.fn(),
  process: vi.fn(),
  archive: vi.fn(),
  reindex: vi.fn(),
  reindexAll: vi.fn(),
  getUnits: vi.fn(),
});

const downloads: FileDownloadPort = {
  saveText: vi.fn(),
  saveBinary: vi.fn(),
};

describe("knowledge operations", () => {
  it("always creates a release before uploading and enqueuing ingest", async () => {
    const repository = port();
    const operations = createKnowledgeOperations(repository, downloads);
    const file = {
      name: "source.md",
      type: "text/markdown",
      bytes: new ArrayBuffer(1),
    };

    await expect(
      operations.createAndIngestVersion("project-1", file),
    ).resolves.toMatchObject({ job_id: "job-1", kb_version_id: "version-1" });
    expect(repository.createVersion).toHaveBeenCalledWith("project-1");
    expect(repository.uploadVersionFile).toHaveBeenCalledWith(
      "project-1",
      "version-1",
      file,
    );
    expect(repository.ingestVersion).toHaveBeenCalledWith(
      "project-1",
      "version-1",
    );
  });
});
