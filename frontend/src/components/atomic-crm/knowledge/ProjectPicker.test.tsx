import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  refresh: vi.fn(),
  create: vi.fn(),
  projects: [] as Array<{ id: string; name: string; slug: string }>,
  knowledgeBases: [] as Array<{ id: string; mode: string }>,
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
  useDataProvider: () => ({ create: mocks.create }),
  useGetOne: () => ({ data: undefined }),
  useGetList: (resource: string) => ({
    data: resource === "projects" ? mocks.projects : mocks.knowledgeBases,
  }),
}));

import { ProjectPicker } from "./ProjectPicker";

describe("ProjectPicker", () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.refresh.mockReset();
    mocks.create.mockReset();
    mocks.projects = [];
    mocks.knowledgeBases = [];
  });

  it("selects an existing project from the type-ahead list", async () => {
    mocks.projects = [
      { id: "p1", name: "Dự án Alpha", slug: "du-an-alpha" },
      { id: "p2", name: "Dự án Beta", slug: "du-an-beta" },
    ];
    const onChange = vi.fn();
    const screen = await render(<ProjectPicker value="" onChange={onChange} />);

    await screen.getByRole("combobox", { name: "Dự án" }).click();
    await screen.getByRole("option", { name: /Dự án Beta/ }).click();

    expect(onChange).toHaveBeenCalledExactlyOnceWith("p2");
  });

  it("creates a project from the unmatched search term and selects it", async () => {
    mocks.knowledgeBases = [{ id: "kb1", mode: "RAG" }];
    mocks.create.mockResolvedValue({
      data: { id: "p9", name: "Dự án Mới", slug: "du-an-moi" },
    });
    const onChange = vi.fn();
    const screen = await render(<ProjectPicker value="" onChange={onChange} />);

    await screen.getByRole("combobox", { name: "Dự án" }).fill("Dự án Mới");
    await screen.getByRole("option", { name: /Tạo dự án "Dự án Mới"/ }).click();

    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledExactlyOnceWith("p9"),
    );
    expect(mocks.create).toHaveBeenCalledWith(
      "projects",
      expect.objectContaining({
        data: expect.objectContaining({ name: "Dự án Mới" }),
      }),
    );
  });
});
