import { expect, test } from "./fixtures";

test.describe("knowledge ingestion journey", () => {
  test("uploads a document through the console into the real backend", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/knowledge_sources");

    await expect(
      page.getByRole("heading", { name: "Quản lý kiến thức" }),
    ).toBeVisible({ timeout: 15_000 });

    // Step 1 of the inline uploader: pick the seeded project. Two "Chọn dự án"
    // comboboxes render (toolbar filter first, uploader second), and neither
    // exposes an accessible name, so target the uploader's by position.
    await page.getByRole("combobox").last().click();
    await page.getByRole("option", { name: "E2E Project" }).click();

    // Step 2: attach a .txt source through the dropzone's file input; the
    // selected-file chip proves the dropzone registered it.
    await page.locator('input[type="file"]').setInputFiles([
      {
        name: "e2e-knowledge.txt",
        mimeType: "text/plain",
        buffer: Buffer.from(
          "LG Display tuyển operator lương 15 triệu. Có xe đưa đón Hải Phòng.",
        ),
      },
    ]);
    await expect(
      page.getByRole("button", { name: "Xóa tệp đã chọn" }),
    ).toBeVisible();

    // The uploader enables its button once project + file are present; exact
    // name so the dropzone's "…để tải lên" label doesn't also match.
    await page.getByRole("button", { name: "Tải lên", exact: true }).click();

    await expect(
      page.getByText("Đã tạo phiên bản KB", { exact: false }),
    ).toBeVisible({ timeout: 15_000 });
  });
});
