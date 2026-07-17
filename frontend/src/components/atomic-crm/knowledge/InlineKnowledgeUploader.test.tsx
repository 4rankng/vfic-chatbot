import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createAndIngestKnowledgeBaseVersion: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
  onDrop: undefined as
    | undefined
    | ((acceptedFiles: File[], rejectedFiles: unknown[]) => void),
}));

vi.mock("@/lib/vfic/knowledgeService", () => ({
  createAndIngestKnowledgeBaseVersion: mocks.createAndIngestKnowledgeBaseVersion,
  saveKnowledgeTemplate: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

vi.mock("react-dropzone", () => ({
  useDropzone: (options: {
    onDrop: (acceptedFiles: File[], rejectedFiles: unknown[]) => void;
  }) => {
    mocks.onDrop = options.onDrop;
    return {
      getRootProps: () => ({}),
      getInputProps: () => ({}),
      isDragActive: false,
      isDragReject: false,
      open: () => undefined,
    };
  },
}));

vi.mock("./ProjectPicker", () => ({
  ProjectPicker: ({ onChange }: { onChange: (projectId: string) => void }) => (
    <button type="button" onClick={() => onChange("project-1")}>
      Chọn dự án mẫu
    </button>
  ),
}));

import { InlineKnowledgeUploader } from "./InlineKnowledgeUploader";

describe("InlineKnowledgeUploader", () => {
  it("stages a selected file in a KB release", async () => {
    mocks.createAndIngestKnowledgeBaseVersion.mockResolvedValue({
      job_id: "job-1",
      kb_version_id: "version-1",
      status: "PENDING",
    });
    const screen = await render(<InlineKnowledgeUploader />);

    await screen.getByRole("button", { name: "Chọn dự án mẫu" }).click();
    mocks.onDrop?.(
      [new File(["Thông tin tuyển dụng"], "tuyen-dung.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })],
      [],
    );
    await expect.element(screen.getByText("tuyen-dung.docx")).toBeVisible();
    await screen.getByRole("button", { name: "Tải lên" }).click();

    await vi.waitFor(() => {
      expect(mocks.createAndIngestKnowledgeBaseVersion).toHaveBeenCalledTimes(1);
    });
    expect(mocks.createAndIngestKnowledgeBaseVersion).toHaveBeenCalledWith(
      "project-1",
      expect.objectContaining({ name: "tuyen-dung.docx" }),
    );
  });
});
