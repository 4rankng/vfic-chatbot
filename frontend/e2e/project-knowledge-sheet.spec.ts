import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { expect, test } from "./fixtures";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_PYTHON =
  process.env.VFIC_BACKEND_PYTHON ??
  path.resolve(__dirname, "../../backend/.venv/bin/python");
const SEED_SCRIPT = path.resolve(__dirname, "seed_active_category.py");

/**
 * The phone knowledge sheet (ProjectList → AppModal) portals its panel to
 * document.body, outside the workspace container that scopes every panel
 * style. This spec drives the real sheet at phone size and asserts the
 * rendered contract, not just the DOM: the catalog grid replaced by the
 * sticky switcher, record cards with card chrome and stacked fields, and no
 * horizontal overflow. Artifacts land in test-results/ per the UI
 * verification contract.
 */
test("knowledge sheet renders the styled category catalog at phone size", async ({
  page,
  loginAsAdmin,
}, testInfo) => {
  test.setTimeout(180_000);
  await loginAsAdmin();

  // The harness has no provider-backed review worker, so the jobs category
  // needs the service-level activation seed to reach ACTIVE before the UI
  // run. The resetDb fixture has already truncated and re-seeded the base
  // project at this point.
  const seeded = await execFileAsync(BACKEND_PYTHON, [SEED_SCRIPT], {
    env: process.env,
    timeout: 120_000,
  });
  expect(seeded.stdout).toContain("seeded: e2e-project/jobs ACTIVE");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/projects");
  await page
    .getByRole("button", { name: "Mở kiến thức dự án E2E Project" })
    .click();
  const sheet = page.getByRole("dialog", {
    name: "Kiến thức dự án E2E Project",
  });
  await expect(sheet).toBeVisible();
  await expect(sheet.locator("#project-category-detail")).toBeVisible({
    timeout: 15_000,
  });

  // The 12-card grid stays desktop-only; the phone switcher replaces it.
  await expect(sheet.locator(".project-category-grid")).not.toBeVisible();
  const switcher = sheet.locator('[aria-label="Chọn danh mục kiến thức"]');
  await expect(switcher).toBeVisible();
  await expect(switcher).toContainText("Vị trí tuyển dụng");

  // Record cards: real card chrome, real title weight — the pre-fix sheet
  // rendered both as bare text because every panel rule is workspace-scoped.
  const firstCard = sheet.locator(
    '.project-category-record-card[aria-label="Công nhân lắp ráp"]',
  );
  await expect(firstCard).toBeVisible();
  await expect(
    sheet.locator('.project-category-record-card[aria-label="Công nhân may"]'),
  ).toBeVisible();
  const cardStyle = await firstCard.evaluate((element) => {
    const style = getComputedStyle(element);
    const title = getComputedStyle(
      element.querySelector(".project-category-record-title")!,
    );
    const field = element.querySelector(".project-category-record-field")!;
    return {
      background: style.backgroundColor,
      borderStyle: style.borderTopStyle,
      titleWeight: Number.parseInt(title.fontWeight, 10),
      fieldColumns: getComputedStyle(field).gridTemplateColumns,
    };
  });
  expect(cardStyle.background).not.toBe("rgba(0, 0, 0, 0)");
  expect(cardStyle.borderStyle).toBe("solid");
  expect(cardStyle.titleWeight).toBeGreaterThanOrEqual(600);
  // Phone fields stack label over value: one track, not the desktop pair.
  expect(cardStyle.fieldColumns.split(" ")).toHaveLength(1);

  // The switcher owns the sheet's sticky top slot; the editor header scrolls.
  // `position` is asserted on the nav itself — the select button inside it
  // carries the library button's own `position: relative`.
  const scrollBody = sheet.locator(".project-knowledge-sheet-body");
  const nav = sheet.locator(".project-category-navigation");
  expect(
    await nav.evaluate((element) => getComputedStyle(element).position),
  ).toBe("sticky");
  expect(
    await sheet
      .locator(".project-category-editor-header")
      .evaluate((element) => getComputedStyle(element).position),
  ).toBe("static");
  await scrollBody.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect
    .poll(async () => {
      const gap = await sheet.evaluate(() => {
        const body = document.querySelector(".project-knowledge-sheet-body")!;
        const nav = body.querySelector(".project-category-navigation")!;
        return (
          nav.getBoundingClientRect().top - body.getBoundingClientRect().top
        );
      });
      return gap;
    })
    .toBeLessThanOrEqual(2);
  await page.screenshot({
    path: testInfo.outputPath("knowledge-sheet-scrolled.png"),
    animations: "disabled",
  });

  // Nothing in the sheet may push the page or the sheet sideways.
  await scrollBody.evaluate((element) => {
    element.scrollTop = 0;
  });
  const overflow = await page.evaluate(() => {
    const body = document.querySelector(".project-knowledge-sheet-body")!;
    return {
      page:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      sheet: body.scrollWidth - body.clientWidth,
    };
  });
  expect(overflow.page).toBeLessThanOrEqual(1);
  expect(overflow.sheet).toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath("knowledge-sheet-top.png"),
    animations: "disabled",
  });
});
