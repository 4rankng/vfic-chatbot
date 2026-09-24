import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "vitest-browser-react";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
  knowledgeBase: {
    id: "kb-rorze",
    name: "Rorze Knowledge",
    slug: "rorze-kb",
    mode: "DIRECT_CONTEXT" as const,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  },
}));

vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  ShowBase: ({ children }: { children: ReactNode }) => children,
  useGetList: () => ({ data: [] }),
  useNotify: () => mocks.notify,
  useRecordContext: () => mocks.knowledgeBase,
  useRefresh: () => mocks.refresh,
}));

vi.mock("@/lib/apiClient", () => ({
  apiJson: mocks.apiJson,
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));
vi.mock("react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));
vi.mock("../kit", () => ({
  PageHeading: ({ title }: { title: string }) => <h1>{title}</h1>,
  PageShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import { KnowledgeBaseShow } from "./KnowledgeBaseShow";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

const owner = {
  id: "project-rorze",
  slug: "rorze",
  name: "Rorze",
  is_active: false,
  knowledge_document_count: 1,
  active_job_count: 0,
  factories: [],
};

const currentFile = {
  filename: "rorze.md",
  text: "Rorze tuyển nhân viên vận hành máy CNC.",
  char_count: 42,
  line_count: 1,
};

const capacity = {
  model: "MiniMax-M2.7-highspeed",
  available_input_tokens: 100_000,
  estimated_input_tokens: 1_000,
  fits: true,
};

describe("KnowledgeBaseShow direct file", () => {
  beforeEach(() => {
    mocks.apiJson.mockReset();
    mocks.notify.mockReset();
    mocks.refresh.mockReset();
  });

  it("waits for authoritative project ownership before enabling save", async () => {
    let resolveProjects!: (value: (typeof owner)[]) => void;
    const projects = new Promise<(typeof owner)[]>((resolve) => {
      resolveProjects = resolve;
    });
    mocks.apiJson.mockImplementation((path: string) => {
      if (path.endsWith("/projects")) return projects;
      if (path.endsWith("/direct-file")) return Promise.resolve(currentFile);
      if (path.endsWith("/direct-context-capacity"))
        return Promise.resolve(capacity);
      throw new Error(`Unexpected request: ${path}`);
    });

    const screen = await render(<KnowledgeBaseShow />);
    const editor = screen.getByRole("textbox", {
      name: "Nội dung tệp ngữ cảnh",
    });
    await expect.element(editor).toBeDisabled();
    await expect
      .element(screen.getByRole("button", { name: "Lưu tệp" }))
      .toBeDisabled();

    resolveProjects([owner]);

    await expect.element(editor).toBeEnabled();
    await editor.fill("Nội dung mới");
    await expect
      .element(screen.getByRole("button", { name: "Lưu tệp" }))
      .toBeEnabled();
  });

  it("warns before a replacement reactivates an inactive owning project", async () => {
    mocks.apiJson.mockImplementation(
      (path: string, options?: { method?: string }) => {
        if (options?.method === "PUT") return Promise.resolve({});
        if (path.endsWith("/projects")) return Promise.resolve([owner]);
        if (path.endsWith("/direct-file")) return Promise.resolve(currentFile);
        if (path.endsWith("/direct-context-capacity"))
          return Promise.resolve(capacity);
        throw new Error(`Unexpected request: ${path}`);
      },
    );
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const screen = await render(<KnowledgeBaseShow />);
    const save = screen.getByRole("button", { name: "Lưu tệp" });
    await expect.element(save).toBeEnabled();

    await save.click();

    expect(confirm).toHaveBeenCalledWith(
      "Lưu tệp mới sẽ bật dự án để Agent sử dụng. Tiếp tục?",
    );
    expect(
      mocks.apiJson.mock.calls.some(([, options]) => options?.method === "PUT"),
    ).toBe(false);
    confirm.mockRestore();
  });

  it("blocks saving when authoritative ownership fails to load", async () => {
    mocks.apiJson.mockImplementation((path: string) => {
      if (path.endsWith("/projects"))
        return Promise.reject(new Error("load failed"));
      if (path.endsWith("/direct-file")) return Promise.resolve(currentFile);
      if (path.endsWith("/direct-context-capacity"))
        return Promise.resolve(capacity);
      throw new Error(`Unexpected request: ${path}`);
    });

    const screen = await render(<KnowledgeBaseShow />);

    await expect
      .element(screen.getByText("Chưa tải được dữ liệu kho."))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Lưu tệp" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("button", { name: "Thử lại" }))
      .toBeVisible();
    expect(
      mocks.apiJson.mock.calls.some(([, options]) => options?.method === "PUT"),
    ).toBe(false);
  });

  it("uses real sections without nested cards", async () => {
    mocks.apiJson.mockImplementation((path: string) => {
      if (path.endsWith("/projects")) return Promise.resolve([owner]);
      if (path.endsWith("/direct-file")) return Promise.resolve(currentFile);
      if (path.endsWith("/direct-context-capacity"))
        return Promise.resolve(capacity);
      throw new Error(`Unexpected request: ${path}`);
    });

    const screen = await render(<KnowledgeBaseShow />);

    await expect
      .element(screen.getByRole("heading", { name: "Agent được gắn" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Tệp ngữ cảnh" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Nội dung tệp ngữ cảnh" }))
      .toBeEnabled();
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();
  });
});
