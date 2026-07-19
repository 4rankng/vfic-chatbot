import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { AlternateCard, EmptyState, PageShell } from "./page-shell";

describe("PageShell", () => {
  it("renders the shared page canvas at the requested width", async () => {
    const screen = await render(
      <PageShell size="narrow">
        <p>Nội dung</p>
      </PageShell>,
    );

    expect(screen.getByText("Nội dung")).toBeTruthy();
    expect(
      screen.container.querySelector(".tt-page-shell.max-w-3xl"),
    ).not.toBeNull();
  });
});

describe("AlternateCard", () => {
  it("renders its header, description, action and work surface", async () => {
    const screen = await render(
      <AlternateCard
        title="Thông tin"
        description="Mô tả"
        icon={<span>i</span>}
        action={<button type="button">Sửa</button>}
      >
        <p>Biểu mẫu</p>
      </AlternateCard>,
    );

    expect(screen.getByRole("heading", { name: "Thông tin" })).toBeTruthy();
    expect(screen.getByText("Mô tả")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sửa" })).toBeTruthy();
    expect(screen.getByText("Biểu mẫu")).toBeTruthy();
  });
});

describe("EmptyState", () => {
  it("renders the status copy and optional action", async () => {
    const screen = await render(
      <EmptyState
        icon={<span>i</span>}
        title="Chưa có dữ liệu"
        description="Tạo mục đầu tiên để bắt đầu."
        action={<button type="button">Tạo mới</button>}
      />,
    );

    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("Chưa có dữ liệu")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Tạo mới" })).toBeTruthy();
  });
});
