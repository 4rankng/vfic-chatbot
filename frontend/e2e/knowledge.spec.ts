import { expect, test } from "./fixtures";

const BRIEF = `Tên dự án: E2E Text Import
Vị trí tuyển dụng: Công nhân sản xuất

## Lương và thu nhập
Lương cơ bản: 6.200.000 đồng/tháng.
`;

test.describe("project training source upload", () => {
  test("retains one text file and a durable category plan before leaving the page", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/projects/create");
    await expect(
      page.getByRole("heading", { name: "Tạo dự án", exact: true }),
    ).toBeVisible();

    const uploaded = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/knowledge/documents/upload-file") &&
        response.request().method() === "POST",
    );
    await page.locator('input[type="file"]').setInputFiles({
      name: "e2e-project-brief.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(BRIEF),
    });
    const response = await uploaded;
    expect(response.status()).toBe(201);
    const receipt = await response.json();
    expect(receipt.file_name).toBe("e2e-project-brief.txt");
    expect(receipt.project_id).toBeTruthy();
    expect(receipt.project_training).toMatchObject({
      status: "QUEUED",
      completed: [],
    });
    await expect(
      page.getByRole("button", { name: "Tạo dự án", exact: true }),
    ).toBeDisabled();

    // The test harness has no provider-backed worker. It proves persistence
    // and queue acceptance; worker integration tests prove training completion.
    await page
      .getByRole("button", { name: "Đóng và quay lại danh sách dự án" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Dự án tuyển dụng" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "E2E Text Import", exact: true }),
    ).toBeVisible();
    const token = await page.evaluate(() =>
      localStorage.getItem("RaStore.auth.access_token"),
    );
    const document = await page.request.get(
      response.url().replace("/upload-file", `/${receipt.id}`),
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(document.status()).toBe(200);
    const retained = await document.json();
    expect(retained.project_id).toBe(receipt.project_id);
    expect(retained.project_training.status).toBe("QUEUED");
    expect(retained.project_training).not.toHaveProperty("writes");
  });
});
