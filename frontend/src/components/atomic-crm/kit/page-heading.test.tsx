import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { PageHeading } from "./page-heading";

describe("PageHeading", () => {
  it("renders the title and subtitle", async () => {
    const screen = await render(
      <PageHeading title="Tổng quan" subtitle="Tuần này" />,
    );
    await expect
      .element(screen.getByRole("heading", { name: "Tổng quan" }))
      .toBeVisible();
    expect(screen.getByText("Tuần này")).toBeTruthy();
  });

  it("renders an eyebrow above the title", async () => {
    const screen = await render(
      <PageHeading eyebrow="Dashboard" title="Tổng quan" />,
    );
    expect(screen.getByText("Dashboard")).toBeTruthy();
  });

  it("renders action buttons in the actions slot", async () => {
    const screen = await render(
      <PageHeading
        title="Hồ sơ"
        actions={
          <>
            <button type="button">Huỷ</button>
            <button type="button">Lưu</button>
          </>
        }
      />,
    );
    expect(screen.getByRole("button", { name: "Huỷ" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lưu" })).toBeTruthy();
  });

  it("renders children into the body when provided", async () => {
    const screen = await render(
      <PageHeading title="Hồ sơ">
        <div data-testid="body">table goes here</div>
      </PageHeading>,
    );
    expect(screen.getByTestId("body")).toBeTruthy();
  });

  it("omits the actions region when no actions are passed", async () => {
    const screen = await render(<PageHeading title="Hồ sơ" />);
    expect(screen.container.querySelector(".tt-page-heading-actions")).toBeNull();
  });
});
