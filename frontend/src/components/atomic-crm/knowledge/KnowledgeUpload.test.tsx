import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createAndIngestKnowledgeBaseVersion: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("./knowledge-service", () => ({
  createAndIngestKnowledgeBaseVersion:
    mocks.createAndIngestKnowledgeBaseVersion,
  saveKnowledgeTemplate: vi.fn(),
}));

vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

vi.mock("./ProjectPicker", () => ({
  ProjectPicker: () => null,
}));

import { KnowledgeUpload } from "./KnowledgeUpload";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

describe("KnowledgeUpload", () => {
  it("stages pasted recruitment knowledge in a KB release", async () => {
    mocks.createAndIngestKnowledgeBaseVersion.mockResolvedValue({
      job_id: "job-1",
      kb_version_id: "version-1",
      status: "PENDING",
    });
    const screen = await render(
      <KnowledgeUpload
        open
        onOpenChange={() => undefined}
        initialProjectId="project-1"
        lockProject
      />,
    );

    await screen.getByRole("tab", { name: "Dán văn bản" }).click();
    await screen
      .getByPlaceholder("Dán nội dung mà chatbot cần tham khảo vào đây...")
      .fill("Thông tin tuyển dụng");
    await screen.getByRole("button", { name: "Tải lên" }).click();

    await vi.waitFor(() => {
      expect(mocks.createAndIngestKnowledgeBaseVersion).toHaveBeenCalledTimes(
        1,
      );
    });
    const [projectId, file] = mocks.createAndIngestKnowledgeBaseVersion.mock
      .calls[0] as [string, File];
    expect(projectId).toBe("project-1");
    expect(file.name).toBe("kien-thuc.txt");
    expect(await file.text()).toBe("Thông tin tuyển dụng");
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("phiên bản KB"),
      { type: "success" },
    );
  });
});
