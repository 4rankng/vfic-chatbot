import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  DataProviderContext,
  TestMemoryRouter,
} from "ra-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "vitest-browser-react";

import "@/index.css";
import { TestMessages } from "../providers/commons/TestMessages";
import type { KnowledgeBase } from "../types";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  notify: vi.fn(),
  redirect: vi.fn(),
  list: {
    data: [] as KnowledgeBase[],
    isPending: false,
    total: 0,
  },
}));

// The form controls are the kit's react-admin bound Untitled UI fields, so the
// real `useInput` (and the real `Form` / `CreateBase`) must be present: a form
// stub would let this test pass against a form the app cannot have. Only the
// data, notification and navigation hooks are stubbed.
vi.mock("ra-core", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;

  return {
    ...actual,
    useDataProvider: () => ({ create: mocks.create }),
    useListContext: () => mocks.list,
    useListPaginationContext: () => mocks.list,
    useNotify: () => mocks.notify,
    useRedirect: () => mocks.redirect,
  };
});

import { KnowledgeBaseCreate } from "./KnowledgeBaseCreate";
import { KnowledgeBaseListContent } from "./KnowledgeBaseList";

const knowledgeBase: KnowledgeBase = {
  id: "kb-vfic",
  name: "VFIC tuyển dụng",
  slug: "vfic",
  mode: "RAG",
  description: null,
  attached_agent_count: 3,
  project_count: 2,
};

const dataProvider = {
  create: mocks.create,
  getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  getOne: vi.fn(() => Promise.resolve({ data: {} })),
  getMany: vi.fn(() => Promise.resolve({ data: [] })),
  getManyReference: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  update: vi.fn(() => Promise.resolve({ data: {} })),
  updateMany: vi.fn(() => Promise.resolve({ data: [] })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
  deleteMany: vi.fn(() => Promise.resolve({ data: [] })),
};

const mount = (children: ReactNode) => (
  <TestMemoryRouter>
    <TestMessages>
      <QueryClientProvider client={new QueryClient()}>
        <DataProviderContext.Provider value={dataProvider as never}>
          {children}
        </DataProviderContext.Provider>
      </QueryClientProvider>
    </TestMessages>
  </TestMemoryRouter>
);

describe("Knowledge Base pages", () => {
  beforeEach(() => {
    mocks.create.mockReset();
    mocks.notify.mockReset();
    mocks.redirect.mockReset();
    mocks.list = { data: [knowledgeBase], isPending: false, total: 1 };
  });

  it("makes the whole flat list row open its detail", async () => {
    const screen = await render(
      mount(<KnowledgeBaseListContent />),
    );
    const row = screen.getByRole("button", {
      name: "Mở kho VFIC tuyển dụng: RAG, 3 Agent, 2 dự án",
    });

    await expect.element(row).toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Kho hiện có" }))
      .toBeVisible();

    await row.click();
    expect(mocks.redirect).toHaveBeenCalledWith(
      "show",
      "knowledge_bases",
      "kb-vfic",
    );
  });

  it("keeps create fields in one section with concise choices", async () => {
    const screen = await render(mount(<KnowledgeBaseCreate />));

    await expect
      .element(screen.getByRole("heading", { name: "Thông tin kho" }))
      .toBeVisible();

    // The mode choices live in a React Aria list box inside a popover, so they
    // are asserted the way a user reaches them: open the select, read the
    // options, then pick one.
    await screen.getByRole("button", { name: /Chế độ/ }).click();
    await expect
      .element(screen.getByRole("option", { name: "RAG — nhiều dự án" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("option", { name: "Trực tiếp — một tệp" }))
      .toBeVisible();
    await screen.getByRole("option", { name: "RAG — nhiều dự án" }).click();

    await screen.getByRole("button", { name: "Hủy" }).click();
    expect(mocks.redirect).toHaveBeenCalledWith("list", "knowledge_bases");
  });

  it("submits the kit fields through the react-admin form", async () => {
    const screen = await render(mount(<KnowledgeBaseCreate />));

    const name = screen.getByRole("textbox", { name: "Tên" });
    // Labelled by React Aria and inside the scope that re-binds the four
    // utility names Untitled UI shares with the console. The required signal
    // must be `aria-required`, NOT the native `required` attribute: React
    // Aria's default `native` validation sets `required`, the browser then
    // blocks the form's submit and react-admin's Vietnamese validation never
    // runs.
    expect(name.element().getAttribute("aria-required")).toBe("true");
    expect(name.element().hasAttribute("required")).toBe(false);
    expect(name.element().closest(".uu-scope")).not.toBeNull();

    await name.fill("Kho dùng chung");
    await screen.getByRole("textbox", { name: "Slug" }).fill("shared");
    await screen.getByRole("button", { name: /Chế độ/ }).click();
    await screen.getByRole("option", { name: "RAG — nhiều dự án" }).click();
    await screen.getByRole("button", { name: "Tạo kho kiến thức" }).click();

    await expect.poll(() => mocks.create.mock.calls.length).toBe(1);
    expect(mocks.create).toHaveBeenCalledWith(
      "knowledge_bases",
      expect.objectContaining({
        data: expect.objectContaining({
          name: "Kho dùng chung",
          slug: "shared",
          mode: "RAG",
        }),
      }),
    );
    expect(mocks.redirect).toHaveBeenCalledWith("list", "knowledge_bases");
  });
});
