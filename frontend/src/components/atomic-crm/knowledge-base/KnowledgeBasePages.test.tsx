import type { ReactNode } from "react";
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

vi.mock("ra-core", async () => {
  // react-admin's `Form` is a react-hook-form `FormProvider`. The stub has to be
  // one too: a field built on `useController` (such as the Untitled UI input in
  // KnowledgeBaseCreate) joins that context, and a stub without it would either
  // throw or, worse, let this test pass against a form the app cannot have.
  const { FormProvider, useForm } = await import("react-hook-form");

  return {
    CreateBase: ({ children }: { children: ReactNode }) => children,
    Form: ({
      children,
      onSubmit,
    }: {
      children: ReactNode;
      onSubmit: (data: Record<string, unknown>) => void;
    }) => {
      const form = useForm();

      return (
        <FormProvider {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>{children}</form>
        </FormProvider>
      );
    },
    ListBase: ({ children }: { children: ReactNode }) => children,
    useDataProvider: () => ({ create: mocks.create }),
    useListContext: () => mocks.list,
    useNotify: () => mocks.notify,
    useRedirect: () => mocks.redirect,
  };
});

vi.mock("@/components/admin/text-input", async () => {
  const { useFormContext } = await import("react-hook-form");

  return {
    TextInput: ({
      source,
      label,
      multiline,
    }: {
      source: string;
      label: string;
      multiline?: boolean;
    }) => {
      const { register } = useFormContext();

      return multiline ? (
        <textarea aria-label={label} {...register(source)} />
      ) : (
        <input aria-label={label} {...register(source)} />
      );
    },
  };
});

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

    // The mode choices live in a React Aria list box inside a popover now, so
    // they are asserted the way a user reaches them: open the select, read the
    // options, then pick one. Picking also closes the popover -- an open
    // popover covers the page and would intercept the next click, which is how
    // this test first failed.
    await screen.getByRole("button", { name: /Chế độ/ }).click();
    await expect
      .element(screen.getByRole("option", { name: "RAG — nhiều dự án" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("option", { name: "Trực tiếp — một tệp" }))
      .toBeVisible();
    await screen.getByRole("option", { name: "RAG — nhiều dự án" }).click();

    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();

    await screen.getByRole("button", { name: "Hủy" }).click();
    expect(mocks.redirect).toHaveBeenCalledWith("list", "knowledge_bases");
  });

  it("submits the Untitled UI name field through the react-admin form", async () => {
    const screen = await render(<KnowledgeBaseCreate />);

    const name = screen.getByRole("textbox", { name: "Tên" });
    // Labelled by RAC, marked required (React Aria emits the native `required`
    // attribute under its default validation behaviour and `aria-required`
    // under `validationBehavior="aria"`), and inside the scope that re-binds
    // the four utility names Untitled UI shares with the console.
    const requiredSignal =
      name.element().hasAttribute("required") ||
      name.element().getAttribute("aria-required") === "true";
    expect(requiredSignal).toBe(true);
    expect(name.element().closest(".uu-scope")).not.toBeNull();

    await name.fill("Kho dùng chung");
    await screen.getByLabelText("Slug").fill("shared");
    await screen.getByRole("button", { name: /Chế độ/ }).click();
    await screen.getByRole("option", { name: "RAG — nhiều dự án" }).click();
    await screen.getByRole("button", { name: "Tạo kho kiến thức" }).click();

    await expect.poll(() => mocks.create.mock.calls.length).toBe(1);
    expect(mocks.create).toHaveBeenCalledWith("knowledge_bases", {
      data: {
        name: "Kho dùng chung",
        slug: "shared",
        mode: "RAG",
        description: "",
      },
    });
  });
});
