import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { EmptyState, PageShell } from "./page-shell";
import "@/index.css";

describe("PageShell", () => {
  it("renders children inside the requested column width", async () => {
    const screen = await render(
      <PageShell size="narrow">
        <p>Nội dung</p>
      </PageShell>,
    );

    expect(screen.getByText("Nội dung")).toBeTruthy();
    expect(screen.container.querySelector(".max-w-3xl")).not.toBeNull();
  });

  it("leaves scrolling to the app shell", async () => {
    const screen = await render(
      <PageShell>
        <div style={{ height: 480 }}>Nội dung dài</div>
      </PageShell>,
    );
    const shell = screen.container.firstElementChild as HTMLElement;

    expect(shell.style.overflowY).not.toBe("auto");
  });
});

describe("EmptyState", () => {
  it("renders the status copy, the icon and the optional action", async () => {
    const screen = await render(
      <EmptyState
        icon={<span data-testid="empty-icon">i</span>}
        title="Chưa có dữ liệu"
        description="Tạo mục đầu tiên để bắt đầu."
        action={<button type="button">Tạo mới</button>}
      />,
    );

    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("Chưa có dữ liệu")).toBeTruthy();
    expect(screen.getByText("Tạo mục đầu tiên để bắt đầu.")).toBeTruthy();
    expect(screen.getByTestId("empty-icon")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Tạo mới" })).toBeTruthy();
    const icon = screen.getByTestId("empty-icon").element().parentElement!;
    const style = getComputedStyle(icon);
    expect(style.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(style.borderTopWidth).toBe("0px");
    expect(style.boxShadow).toBe("none");
  });

  it("renders no action region when the caller passes none", async () => {
    const screen = await render(
      <EmptyState
        icon={<span>i</span>}
        title="Chưa có dữ liệu"
        description="Tạo mục đầu tiên để bắt đầu."
      />,
    );

    expect(screen.container.querySelectorAll("button")).toHaveLength(0);
    expect(screen.container.querySelectorAll("main, h1")).toHaveLength(0);
    await expect
      .element(
        screen.getByRole("heading", { level: 2, name: "Chưa có dữ liệu" }),
      )
      .toBeVisible();
  });
});
