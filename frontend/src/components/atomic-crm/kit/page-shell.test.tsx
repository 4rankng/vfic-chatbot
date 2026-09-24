import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { EmptyState, PageShell } from "./page-shell";

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

  it("owns vertical scrolling when content exceeds the workspace", async () => {
    const screen = await render(
      <div style={{ height: 160 }}>
        <PageShell>
          <div style={{ height: 480 }}>Nội dung dài</div>
        </PageShell>
      </div>,
    );
    const shell = screen.container.querySelector<HTMLElement>(".tt-page-shell");

    expect(shell).not.toBeNull();
    expect(shell).toHaveClass("h-full", "min-h-0", "overflow-y-auto");
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
