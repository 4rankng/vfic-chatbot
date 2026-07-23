import type { FormEvent, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "vitest-browser-react";

import type { KnowledgeBase } from "../types";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  notify: vi.fn(),
  redirect: vi.fn(),
  list: {
    data: [] as KnowledgeBase[],
    isPending: false,
  },
}));

vi.mock("ra-core", () => ({
  CreateBase: ({ children }: { children: ReactNode }) => children,
  Form: ({
    children,
    onSubmit,
  }: {
    children: ReactNode;
    onSubmit: (data: Record<string, unknown>) => void;
  }) => (
    <form
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        onSubmit({
          name: "Kho dùng chung",
          slug: "shared",
          mode: "RAG",
        });
      }}
    >
      {children}
    </form>
  ),
  ListBase: ({ children }: { children: ReactNode }) => children,
  useDataProvider: () => ({ create: mocks.create }),
  useListContext: () => mocks.list,
  useNotify: () => mocks.notify,
  useRedirect: () => mocks.redirect,
}));

vi.mock("@/components/admin/text-input", () => ({
  TextInput: ({ label, multiline }: { label: string; multiline?: boolean }) =>
    multiline ? <textarea aria-label={label} /> : <input aria-label={label} />,
}));

vi.mock("@/components/admin/select-input", () => ({
  SelectInput: ({
    label,
    choices,
  }: {
    label: string;
    choices: { id: string; name: string }[];
  }) => (
    <select aria-label={label}>
      {choices.map((choice) => (
        <option key={choice.id} value={choice.id}>
          {choice.name}
        </option>
      ))}
    </select>
  ),
}));

vi.mock("react-router", () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

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

describe("Knowledge Base pages", () => {
  beforeEach(() => {
    mocks.create.mockReset();
    mocks.notify.mockReset();
    mocks.redirect.mockReset();
    mocks.list = { data: [knowledgeBase], isPending: false };
  });

  it("makes the whole flat list row open its detail", async () => {
    const screen = await render(<KnowledgeBaseListContent />);
    const row = screen.getByRole("button", {
      name: "Mở kho VFIC tuyển dụng: RAG, 3 Agent, 2 dự án",
    });

    await expect.element(row).toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Kho hiện có" }))
      .toBeVisible();
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();

    await row.click();
    expect(mocks.redirect).toHaveBeenCalledWith(
      "show",
      "knowledge_bases",
      "kb-vfic",
    );
  });

  it("keeps create fields in one section with concise choices", async () => {
    const screen = await render(<KnowledgeBaseCreate />);

    await expect
      .element(screen.getByRole("heading", { name: "Thông tin kho" }))
      .toBeVisible();
    expect(
      screen
        .getByRole("option", { name: "RAG — nhiều dự án" })
        .element(),
    ).toBeInstanceOf(HTMLOptionElement);
    expect(
      screen
        .getByRole("option", { name: "Trực tiếp — một tệp" })
        .element(),
    ).toBeInstanceOf(HTMLOptionElement);
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();

    await screen.getByRole("button", { name: "Hủy" }).click();
    expect(mocks.redirect).toHaveBeenCalledWith("list", "knowledge_bases");
  });
});
