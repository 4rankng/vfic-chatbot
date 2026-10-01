import { readFile } from "node:fs/promises";

import { expect, test } from "./fixtures";

const API = "http://127.0.0.1:8000/api/v1/knowledge/projects";
const SAVED = `# Kiến thức tuyển dụng đã lưu

Lương cơ bản: 6.200.000 đồng/tháng.
Ứng tuyển: để lại số điện thoại để được tư vấn.
`;
const LEGACY_UPLOAD = SAVED.replace(
  "Lương cơ bản:",
  'job_ids: ["old-role"]\njobs_ids: []\nvacancies: null\nemployment_type: null\nLương cơ bản:',
);
const UNSAVED = "Bản sửa chưa lưu, không đưa vào tệp xuất.";

test("downloads saved project knowledge without replacing an open draft at phone, tablet, and desktop widths", async ({
  page,
  loginAsAdmin,
}, testInfo) => {
  test.setTimeout(120_000);
  await loginAsAdmin();
  const token = await page.evaluate(() =>
    localStorage.getItem("RaStore.auth.access_token"),
  );
  const headers = { Authorization: `Bearer ${token}` };
  const created = await page.request.post(API, {
    headers,
    data: {
      slug: "e2e-saved-knowledge",
      name: "Kiến thức tuyển dụng E2E",
      knowledge_mode: "DIRECT_CONTEXT",
      discovery_card: { summary: "Tuyển công nhân tại Hải Phòng" },
    },
  });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const saved = await page.request.put(`${API}/${project.id}/single-page`, {
    headers,
    data: { filename: "original-source.txt", text: LEGACY_UPLOAD },
  });
  expect(saved.status()).toBe(200);

  await page.setViewportSize({ width: 390, height: 650 });
  await page.goto(`/#/projects/${project.id}`);
  await expect(
    page.getByRole("heading", { name: project.name, exact: true }),
  ).toBeVisible();
  const draft = page.getByRole("textbox", {
    name: "Nội dung trang kiến thức",
    exact: true,
  });
  await expect(draft).toHaveValue(SAVED);
  await draft.fill(UNSAVED);

  for (const width of [390, 900, 1440]) {
    await page.setViewportSize({ width, height: 650 });
    await expect(draft).toHaveValue(UNSAVED);
    const exportButton = page.getByRole("button", {
      name: "Xuất KB",
      exact: true,
    });
    await expect(exportButton).toBeVisible();
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url() === `${API}/${project.id}/knowledge-export` &&
        response.request().method() === "GET",
    );
    const downloadPromise = page.waitForEvent("download");
    await exportButton.click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("no-store");
    expect(response.headers()["access-control-expose-headers"]).toContain(
      "Content-Disposition",
    );
    const download = await downloadPromise;
    expect(await download.failure()).toBeNull();
    expect(download.suggestedFilename()).toBe("kb-e2e-saved-knowledge.md");
    const destination = testInfo.outputPath(`kb-${width}.md`);
    await download.saveAs(destination);
    const content = await readFile(destination, "utf8");
    expect(content).toContain(SAVED);
    expect(content).not.toContain(UNSAVED);
    expect(content).not.toMatch(
      /^\s*(?:jobs?_ids|vacancies|employment_type)\s*:/m,
    );
    await expect(draft).toHaveValue(UNSAVED);
    await expect(exportButton).toBeEnabled();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
    await page.screenshot({
      path: testInfo.outputPath(`project-kb-export-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
  }
});

test("reports an empty RAG knowledge base without downloading a blank file", async ({
  page,
  loginAsAdmin,
}) => {
  await loginAsAdmin();
  const token = await page.evaluate(() =>
    localStorage.getItem("RaStore.auth.access_token"),
  );
  const listed = await page.request.get(API, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(listed.status()).toBe(200);
  const project = (await listed.json()).data.find(
    (record: { slug: string }) => record.slug === "e2e-project",
  );
  expect(project).toBeTruthy();
  await page.goto(`/#/projects/${project.id}`);
  await expect(
    page.getByRole("heading", { name: "E2E Project", exact: true }),
  ).toBeVisible();
  const downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  const exportButton = page.getByRole("button", {
    name: "Xuất KB",
    exact: true,
  });
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${API}/${project.id}/knowledge-export`,
  );
  await exportButton.focus();
  await page.keyboard.press("Enter");
  expect((await responsePromise).status()).toBe(409);
  await expect(
    page.getByText("Dự án chưa có kiến thức đã lưu để xuất.", { exact: true }),
  ).toBeVisible();
  await expect(exportButton).toBeEnabled();
  expect(downloads).toEqual([]);
});

test("downloads the KB template with mouse, keyboard, and touch at phone, tablet, and desktop widths", async ({
  page,
  loginAsAdmin,
}, testInfo) => {
  test.setTimeout(120_000);
  await loginAsAdmin();
  const token = await page.evaluate(() =>
    localStorage.getItem("RaStore.auth.access_token"),
  );
  const listed = await page.request.get(API, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(listed.status()).toBe(200);
  const project = (await listed.json()).data.find(
    (record: { slug: string }) => record.slug === "e2e-project",
  );
  expect(project).toBeTruthy();
  await page.goto(`/#/projects/${project.id}`);
  const button = page.getByRole("button", { name: "Tải mẫu KB", exact: true });
  await expect(button).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Tải mẫu KB đầy đủ", exact: true }),
  ).toHaveCount(0);

  for (const width of [390, 900, 1440]) {
    await page.setViewportSize({ width, height: 650 });
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url() === `${API}/${project.id}/knowledge-template`,
    );
    const downloadPromise = page.waitForEvent("download");
    if (width === 900) {
      await button.focus();
      await page.keyboard.press("Enter");
    } else if (testInfo.project.use.hasTouch) {
      await button.tap();
    } else {
      await button.click();
    }
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toMatch(
      /^text\/(?:plain|markdown)/,
    );
    const template = await downloadPromise;
    expect(template.suggestedFilename()).toBe("mau-kb-du-an.md");
    expect(await template.failure()).toBeNull();
    const destination = testInfo.outputPath(`mau-kb-${width}.md`);
    await template.saveAs(destination);
    const content = await readFile(destination, "utf8");
    for (const category of [
      "jobs",
      "compensation",
      "requirements",
      "work_schedules",
      "benefits",
      "accommodation",
      "meals",
      "transportation",
      "insurance",
      "application",
      "contacts",
      "faq",
    ])
      expect(content).toContain(`category: ${category}`);
    expect(content).not.toMatch(
      /^\s*(?:jobs?_ids|vacancies|employment_type)\s*:/m,
    );
    await expect(button).toBeEnabled();
  }
});
