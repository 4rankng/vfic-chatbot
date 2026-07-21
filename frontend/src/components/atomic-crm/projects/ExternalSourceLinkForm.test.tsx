import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  createExternalSource: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("@/lib/vfic/knowledgeService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/vfic/knowledgeService")>()),
  createExternalSource: mocks.createExternalSource,
  // isValidGoogleSheetUrl stays real — it is the contract under test.
}));

import { ExternalSourceLinkForm } from "./ExternalSourceLinkForm";

describe("ExternalSourceLinkForm", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.createExternalSource.mockResolvedValue({ id: "src-1" });
  });

  it("rejects a non-Google URL before submit", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" />,
    );
    await screen
      .getByRole("button", { name: "Nhập từ link công khai" })
      .click();
    const urlInput = screen.getByLabelText("Link Google Sheet");
    await urlInput.fill("https://evil.example/sheet.csv");

    await expect
      .element(
        screen.getByText(
          /Chỉ nhận link https:\/\/docs\.google\.com/,
        ),
      )
      .toBeVisible();
  });

  it("submits a valid URL with the selected category", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" defaultCategory="faq" />,
    );
    await screen
      .getByRole("button", { name: "Nhập từ link công khai" })
      .click();
    await screen.getByLabelText("Link Google Sheet").fill(
      "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit",
    );
    await screen.getByRole("button", { name: /Nhập một lần/ }).click();

    await vi.waitFor(() => expect(mocks.createExternalSource).toHaveBeenCalledTimes(1));
    const [, payload] = mocks.createExternalSource.mock.calls[0];
    expect(payload).toMatchObject({
      category_key: "faq",
      auto_sync_enabled: false,
    });
    expect(payload.sheet_url).toContain("docs.google.com");
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("Đã thêm nguồn"),
      { type: "success" },
    );
  });
});
