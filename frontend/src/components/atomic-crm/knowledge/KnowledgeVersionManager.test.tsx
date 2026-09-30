import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listKnowledgeBaseVersions: vi.fn(),
  publishKnowledgeBaseVersion: vi.fn(),
}));

vi.mock("./knowledge-service", () => ({
  listKnowledgeBaseVersions: mocks.listKnowledgeBaseVersions,
  publishKnowledgeBaseVersion: mocks.publishKnowledgeBaseVersion,
}));

import { KnowledgeVersionManager } from "./KnowledgeVersionManager";

describe("KnowledgeVersionManager", () => {
  beforeEach(() => {
    mocks.listKnowledgeBaseVersions.mockReset();
    mocks.publishKnowledgeBaseVersion.mockReset();
  });

  it("opens a named modal and publishes a READY version", async () => {
    mocks.listKnowledgeBaseVersions.mockResolvedValue({
      data: [{ id: "v1", version_no: 3, status: "READY" }],
    });
    mocks.publishKnowledgeBaseVersion.mockResolvedValue(undefined);

    const screen = await render(<KnowledgeVersionManager projectId="p1" />);

    await screen.getByRole("button", { name: "Phiên bản KB" }).click();

    await expect
      .element(screen.getByRole("dialog", { name: "Phiên bản kiến thức" }))
      .toBeVisible();
    await expect.element(screen.getByText("Phiên bản 3")).toBeVisible();

    await screen.getByRole("button", { name: "Xuất bản" }).click();

    await vi.waitFor(() =>
      expect(mocks.publishKnowledgeBaseVersion).toHaveBeenCalledWith(
        "p1",
        "v1",
      ),
    );
  });
});
