import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  createExternalSource: vi.fn(),
  createSinglePageExternalSource: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("./project-knowledge-service", async (importOriginal) => ({
  ...(await importOriginal()),
  createExternalSource: mocks.createExternalSource,
  createSinglePageExternalSource: mocks.createSinglePageExternalSource,
  // isValidGoogleSheetUrl stays real — it is the contract under test.
}));

import { ExternalSourceLinkForm } from "./ExternalSourceLinkForm";

describe("ExternalSourceLinkForm", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.createExternalSource.mockResolvedValue({ id: "src-1" });
    mocks.createSinglePageExternalSource.mockResolvedValue({ id: "src-sp-1" });
  });

  it("rejects a non-Google URL before submit", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    const urlInput = screen.getByLabelText("Link Google Sheet");
    await urlInput.fill("https://evil.example/sheet.csv");

    await expect
      .element(screen.getByText(/Chỉ nhận link https:\/\/docs\.google\.com/))
      .toBeVisible();
  });

  it("drops a completed source creation after the editor switches projects", async () => {
    let finish!: (value: { id: string }) => void;
    mocks.createSinglePageExternalSource.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const onCreated = vi.fn();
    const screen = await render(
      <ExternalSourceLinkForm
        projectId="project-1"
        variant="single-page"
        onCreated={onCreated}
      />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen
      .getByLabelText("Link Google Sheet")
      .fill("https://docs.google.com/spreadsheets/d/demo/edit#gid=0");
    await screen.getByRole("button", { name: "Nhập một lần" }).click();
    await screen.rerender(
      <ExternalSourceLinkForm
        projectId="project-2"
        variant="single-page"
        onCreated={onCreated}
      />,
    );
    finish({ id: "old-source" });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await expect
      .element(screen.getByRole("button", { name: "Liên kết Google Sheet" }))
      .toBeEnabled();
    expect(onCreated).not.toHaveBeenCalled();
    expect(mocks.notify).not.toHaveBeenCalled();
  });

  it("submits a valid URL with the selected category", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" defaultCategory="faq" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen
      .getByLabelText("Link Google Sheet")
      .fill(
        "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit#gid=123456789",
      );
    await screen.getByRole("button", { name: /Nhập một lần/ }).click();

    await vi.waitFor(() =>
      expect(mocks.createExternalSource).toHaveBeenCalledTimes(1),
    );
    const [, payload] = mocks.createExternalSource.mock.calls[0];
    expect(payload).toMatchObject({
      category_key: "faq",
      sheet_gid: 123456789,
      auto_sync_enabled: false,
    });
    expect(payload.sheet_url).toContain("docs.google.com");
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("Đã thêm nguồn"),
      { type: "success" },
    );
  });

  it("blocks category submission when the Google Sheet link has no explicit gid", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" defaultCategory="faq" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen
      .getByLabelText("Link Google Sheet")
      .fill("https://docs.google.com/spreadsheets/d/demo/edit");

    await expect
      .element(
        screen.getByText(
          /Link phải có gid rõ ràng trong `\?gid=` hoặc `#gid=`/,
        ),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Nhập một lần" }))
      .toBeDisabled();
  });

  it("blocks single-page submission when the Google Sheet link has no explicit gid", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" variant="single-page" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen
      .getByLabelText("Link Google Sheet")
      .fill("https://docs.google.com/spreadsheets/d/demo/edit");

    await expect
      .element(
        screen.getByText(
          /Link phải có gid rõ ràng trong `\?gid=` hoặc `#gid=`/,
        ),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Nhập một lần" }))
      .toBeDisabled();
  });

  it("submits the original single-page URL and lets the backend own gid persistence", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" variant="single-page" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    const originalUrl =
      "https://docs.google.com/spreadsheets/d/demo/edit?usp=sharing#gid=987654321";
    await screen.getByLabelText("Link Google Sheet").fill(originalUrl);
    await screen.getByRole("button", { name: "Nhập một lần" }).click();

    await vi.waitFor(() =>
      expect(mocks.createSinglePageExternalSource).toHaveBeenCalledTimes(1),
    );
    const [, payload] = mocks.createSinglePageExternalSource.mock.calls[0];
    expect(payload).toEqual({
      sheet_url: originalUrl,
      auto_sync_enabled: false,
    });
  });

  it("shows the overwrite warning when single-page auto-sync is enabled", async () => {
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" variant="single-page" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen.getByLabelText("Bật đồng bộ tự động hàng ngày").click();

    await expect
      .element(screen.getByText("Đồng bộ tự động có thể ghi đè chỉnh sửa tay"))
      .toBeVisible();
  });

  it("maps backend create codes to recovery copy", async () => {
    mocks.createSinglePageExternalSource.mockRejectedValue(
      new Error("single_page_external_source_already_exists"),
    );
    const screen = await render(
      <ExternalSourceLinkForm projectId="project-1" variant="single-page" />,
    );
    await screen.getByRole("button", { name: "Liên kết Google Sheet" }).click();
    await screen
      .getByLabelText("Link Google Sheet")
      .fill("https://docs.google.com/spreadsheets/d/demo/edit#gid=42");
    await screen.getByRole("button", { name: "Nhập một lần" }).click();

    await vi.waitFor(() =>
      expect(mocks.notify).toHaveBeenCalledWith(
        "Dự án đã có một nguồn Google Sheet. Hãy xóa nguồn cũ trước.",
        { type: "error" },
      ),
    );
    expect(mocks.notify).not.toHaveBeenCalledWith(
      expect.stringContaining("single_page_external_source"),
      expect.anything(),
    );
  });
});
