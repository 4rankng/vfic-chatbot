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

  it("uses the Tailkit empty-state anatomy inside a dashed frame", async () => {
    const screen = await render(
      <EmptyState
        icon={<span>i</span>}
        title="Chưa có dữ liệu"
        description="Tạo mục đầu tiên để bắt đầu."
      />,
    );
    const status =
      screen.container.querySelector<HTMLElement>('[role="status"]');

    expect(status).not.toBeNull();
    expect(status).toHaveClass("rounded-xl", "border-2", "border-dashed");
    expect(status).toHaveClass("min-h-64", "gap-5");
  });

  it("stays at console density and omits the action slot when unused", async () => {
    const screen = await render(
      <EmptyState
        icon={<span>i</span>}
        title="Chưa có dữ liệu"
        description="Tạo mục đầu tiên để bắt đầu."
      />,
    );
    const status =
      screen.container.querySelector<HTMLElement>('[role="status"]');
    const markup = status?.outerHTML ?? "";

    // Marketing density from the Tailkit catalog must never reach the console.
    expect(markup).not.toContain("py-20");
    expect(markup).not.toContain("py-40");
    expect(markup).not.toContain("text-2xl");
    // Heading and description keep the console's role tokens.
    expect(markup).toContain("--text-section-title");
    expect(markup).toContain("--text-body-sm");
    // No empty action container is rendered.
    expect(status?.querySelector("button")).toBeNull();
  });
});
