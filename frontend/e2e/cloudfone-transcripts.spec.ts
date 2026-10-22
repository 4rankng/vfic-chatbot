import { expect, test } from "./fixtures";

test("opens the stored-transcripts viewer from the Cloudfone settings section", async ({
  page,
  loginAsAdmin,
}) => {
  await loginAsAdmin();
  await page.goto("/#/settings");
  await page
    // Row name carries the toggle status suffix ("Đang tắt"/"Đã bật") —
    // anchor to the label instead of the full composed string.
    .getByRole("button", { name: /^Cloudfone/ })
    .click();
  await expect(
    page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }),
  ).toBeVisible();

  const transcriptsLoaded = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes("/api/v1/admin/integrations/cloudfone/transcripts") &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await transcriptsLoaded;

  // The full chain — console switch, admin route, API, render.
  await expect(
    page.getByRole("heading", { name: "Cloudfone · Bản ghi cuộc gọi" }),
  ).toBeVisible();
  // The transcripts viewer renders inside the settings sub-page chrome, whose
  // appbar back goes one level up the drill-down.
  await expect(page.getByRole("button", { name: "Quay lại", exact: true }));

  // Fresh harness database: the storage empty state is the expected render.
  await expect(page.getByText("Chưa có bản ghi cuộc gọi")).toBeVisible();

  await page.getByRole("button", { name: "Quay lại", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "CloudFone ServiceName" }),
  ).toBeVisible();
});
