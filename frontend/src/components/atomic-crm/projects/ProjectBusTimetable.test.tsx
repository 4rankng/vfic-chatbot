import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock("./project-knowledge-service", () => ({
  getProjectBusTimetable: mocks.load,
}));

import { BusTimetableSection } from "./ProjectBusTimetable";

const response = (total = 0) => ({
  data: [],
  total,
  page: 1,
  per_page: 6,
});

beforeEach(() => {
  mocks.load.mockReset();
});
afterEach(async () => {
  await cleanup();
});

describe("project bus timetable", () => {
  it("distinguishes a failed read from an empty timetable and retries it", async () => {
    mocks.load.mockRejectedValueOnce(new Error("Unavailable"));
    mocks.load.mockResolvedValueOnce(response());
    const screen = await render(<BusTimetableSection projectId="project-a" />);
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Chưa tải được lịch xe đưa đón.");
    expect(screen.container.textContent).not.toContain("Chưa có lịch xe");
    await screen.getByRole("button", { name: "Thử lại" }).click();
    await expect
      .element(
        screen.getByText(
          "Chưa có lịch xe đưa đón được trích xuất cho dự án này.",
        ),
      )
      .toBeVisible();
    expect(mocks.load).toHaveBeenCalledTimes(2);
  });

  it("starts another project's timetable on page one", async () => {
    mocks.load.mockResolvedValue(response(12));
    const screen = await render(<BusTimetableSection projectId="project-a" />);
    await expect.element(screen.getByText("12 tuyến")).toBeVisible();
    await screen.getByRole("button", { name: "Trang sau" }).click();
    await expect.poll(() => mocks.load.mock.calls.length).toBe(2);
    await screen.rerender(<BusTimetableSection projectId="project-b" />);
    await expect.poll(() => mocks.load.mock.calls.length).toBe(3);
    expect(mocks.load.mock.calls[2]).toEqual([
      "project-b",
      { page: 1, perPage: 6 },
    ]);
  });
});
