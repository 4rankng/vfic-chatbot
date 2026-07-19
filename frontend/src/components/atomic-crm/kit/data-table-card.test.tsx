import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

import { DataTableCard } from "./data-table-card";

// DataTableCard renders its own <tbody>, so children must be <tr> rows.
// These tests exercise the chrome (header, search, columns, actions, footer),
// not row content, so a single placeholder row is enough.
const sampleRows = (
  <tr>
    <td>Placeholder row</td>
  </tr>
);

describe("DataTableCard", () => {
  it("renders a header title and description", async () => {
    const screen = await render(
      <DataTableCard title="Ứng viên nóng" description="Tuần này">
        {sampleRows}
      </DataTableCard>,
    );
    expect(screen.getByText("Ứng viên nóng")).toBeTruthy();
    expect(screen.getByText("Tuần này")).toBeTruthy();
  });

  it("renders column headers in a thead", async () => {
    const screen = await render(
      <DataTableCard columns={["Tên", "Vị trí", "Trạng thái"]}>
        {sampleRows}
      </DataTableCard>,
    );
    expect(screen.getByRole("columnheader", { name: "Tên" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Vị trí" })).toBeTruthy();
    expect(
      screen.getByRole("columnheader", { name: "Trạng thái" }),
    ).toBeTruthy();
  });

  it("does not render a thead when no columns are passed", async () => {
    const screen = await render(<DataTableCard>{sampleRows}</DataTableCard>);
    expect(screen.container.querySelector("thead")).toBeNull();
  });

  it("shows a search input only when onSearchChange is provided", async () => {
    const onSearch = vi.fn();
    const screen = await render(
      <DataTableCard title="Bảng" onSearchChange={onSearch}>
        {sampleRows}
      </DataTableCard>,
    );
    const input = screen.getByRole("searchbox");
    expect(input).toBeTruthy();
  });

  it("hides the search input when onSearchChange is omitted", async () => {
    const screen = await render(
      <DataTableCard title="Bảng">{sampleRows}</DataTableCard>,
    );
    expect(screen.container.querySelector("input[type='search']")).toBeNull();
  });

  it("forwards search box changes to onSearchChange", async () => {
    const onSearch = vi.fn();
    const screen = await render(
      <DataTableCard title="Bảng" onSearchChange={onSearch}>
        {sampleRows}
      </DataTableCard>,
    );
    const input = screen.getByRole("searchbox");
    await input.fill("nguyen");
    expect(onSearch).toHaveBeenCalledWith("nguyen");
  });

  it("renders action buttons in the actions slot", async () => {
    const screen = await render(
      <DataTableCard
        title="Bảng"
        actions={<button type="button">Xuất CSV</button>}
      >
        {sampleRows}
      </DataTableCard>,
    );
    expect(screen.getByRole("button", { name: "Xuất CSV" })).toBeTruthy();
  });

  it("renders a footer slot when provided", async () => {
    const screen = await render(
      <DataTableCard title="Bảng" footer={<div data-testid="pager">1 / 5</div>}>
        {sampleRows}
      </DataTableCard>,
    );
    expect(screen.getByTestId("pager")).toBeTruthy();
  });
});
