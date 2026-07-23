import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  permissions: "admin",
  notify: vi.fn(),
  refresh: vi.fn(),
  reindexAllKnowledge: vi.fn(),
}));

vi.mock("ra-core", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useNotify: () => mocks.notify,
    usePermissions: () => ({
      permissions: mocks.permissions,
      isPending: false,
    }),
    useRefresh: () => mocks.refresh,
  };
});

vi.mock("@/lib/vfic/knowledgeService", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    reindexAllKnowledge: mocks.reindexAllKnowledge,
  };
});

import { KnowledgeRelearnAction } from "./KnowledgeSourceList";

describe("KnowledgeRelearnAction", () => {
  beforeEach(() => {
    mocks.permissions = "admin";
    mocks.notify.mockReset();
    mocks.refresh.mockReset();
    mocks.reindexAllKnowledge.mockReset();
  });

  it("requires confirmation and reports how many sources were queued", async () => {
    mocks.reindexAllKnowledge.mockResolvedValue({ status: "ok", queued: 7 });
    const screen = await render(<KnowledgeRelearnAction />);

    await screen.getByRole("button", { name: "Học lại", exact: true }).click();
    expect(mocks.reindexAllKnowledge).not.toHaveBeenCalled();
    await expect
      .element(
        screen.getByRole("heading", { name: "Học lại toàn bộ dữ liệu?" }),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: "Học lại", exact: true }).click();

    await vi.waitFor(() => {
      expect(mocks.reindexAllKnowledge).toHaveBeenCalledTimes(1);
    });
    expect(mocks.notify).toHaveBeenCalledWith(
      "Đã xếp hàng học lại 7 nguồn kiến thức.",
      { type: "success" },
    );
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it("disables the pending action to prevent duplicate requests", async () => {
    let resolveRequest:
      | ((value: { status: string; queued: number }) => void)
      | undefined;
    mocks.reindexAllKnowledge.mockImplementation(
      () =>
        new Promise<{ status: string; queued: number }>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    const screen = await render(<KnowledgeRelearnAction />);

    await screen.getByRole("button", { name: "Học lại", exact: true }).click();
    await screen.getByRole("button", { name: "Học lại", exact: true }).click();

    const pendingButton = screen.getByRole("button", {
      name: "Đang xếp hàng…",
      exact: true,
    });
    await expect.element(pendingButton).toBeDisabled();
    expect(mocks.reindexAllKnowledge).toHaveBeenCalledTimes(1);

    resolveRequest?.({ status: "ok", queued: 3 });
    await vi.waitFor(() => {
      expect(mocks.notify).toHaveBeenCalledWith(
        "Đã xếp hàng học lại 3 nguồn kiến thức.",
        { type: "success" },
      );
    });
  });

  it("shows a recoverable Vietnamese error and remains available", async () => {
    mocks.reindexAllKnowledge.mockRejectedValue(new Error("Máy chủ đang bận."));
    const screen = await render(<KnowledgeRelearnAction />);

    await screen.getByRole("button", { name: "Học lại", exact: true }).click();
    await screen.getByRole("button", { name: "Học lại", exact: true }).click();

    await vi.waitFor(() => {
      expect(mocks.notify).toHaveBeenCalledWith(
        "Không thể xếp hàng học lại dữ liệu. Máy chủ đang bận. Vui lòng thử lại.",
        { type: "error" },
      );
    });
    await expect
      .element(screen.getByRole("button", { name: "Học lại", exact: true }))
      .toBeEnabled();
  });

  it("does not expose the admin-only action to other roles", async () => {
    mocks.permissions = "recruiter";
    const screen = await render(<KnowledgeRelearnAction />);

    await expect
      .element(screen.getByRole("button", { name: "Học lại" }))
      .not.toBeInTheDocument();
  });
});
