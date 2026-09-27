import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  submit: vi.fn<(values: PersonaValues) => Promise<void>>(),
}));

vi.mock("ra-core", () => {
  const knowledgeBases = [
    { id: "kb-1", name: "KB tuyển dụng", mode: "RAG" },
    { id: "kb-2", name: "KB trực tiếp", mode: "DIRECT_CONTEXT" },
  ];
  return {
    // The form reads its labels from the Vietnamese catalog.
    useTranslate: () => testI18nProvider.translate,
    useNotify: () => mocks.notify,
    useGetList: () => ({ data: knowledgeBases, isPending: false }),
  };
});

import { PersonaForm, type PersonaValues } from "./PersonaForm";
import { testI18nProvider } from "../providers/commons/i18nProvider";
import {
  composePersonaMarkdown,
  parsePersonaMarkdown,
} from "./domain/personaMarkdown";
import { normalizePersonaFollowupRules } from "./domain/followupRules";

const initialPersonaValues = {
  name: "",
  body_md: "",
  notes: "",
  knowledge_base_id: "",
  followup_rules: undefined,
};

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
};

describe("PersonaForm", () => {
  beforeEach(() => {
    mocks.submit.mockReset();
    mocks.notify.mockReset();
  });

  it("blocks the save and renders the required-field errors", async () => {
    const screen = await render(
      <PersonaForm
        initial={initialPersonaValues}
        submitLabel="Lưu thay đổi"
        onSubmit={mocks.submit}
      />,
    );

    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    const nameError = screen.getByText("Vui lòng nhập tên Agent.");
    await expect.element(nameError).toBeVisible();
    expect(document.activeElement?.id).toBe("persona-name");
    expect(mocks.submit).not.toHaveBeenCalled();

    await screen.getByLabelText("Tên Agent").fill("Agent tuyển dụng");

    // Typing a name clears the error and moves the gate to the Knowledge Base.
    await expect.element(nameError).not.toBeInTheDocument();
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();
    await expect
      .element(screen.getByText("Vui lòng chọn Knowledge Base cho Agent."))
      .toBeVisible();
    expect(mocks.submit).not.toHaveBeenCalled();
  });

  it("keeps the save gated while a save is in flight", async () => {
    const pending = deferred<void>();
    mocks.submit.mockImplementation(() => pending.promise);
    const screen = await render(
      <PersonaForm
        initial={{
          ...initialPersonaValues,
          name: "Agent chính",
          knowledge_base_id: "kb-1",
        }}
        submitLabel="Lưu thay đổi"
        onSubmit={mocks.submit}
      />,
    );

    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();
    await vi.waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));

    const savingButton = screen.getByRole("button", { name: "Đang lưu…" });
    await expect.element(savingButton).toBeDisabled();
    expect(savingButton.element().getAttribute("aria-busy")).toBe("true");

    pending.resolve(undefined);
    await vi.waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Lưu thay đổi" }).elements(),
      ).toHaveLength(1),
    );
    await expect
      .element(screen.getByRole("button", { name: "Lưu thay đổi" }))
      .toBeEnabled();
  });

  it("sends the composed persona payload on save", async () => {
    // Resolve on a macrotask so the disabled save gate stays up for the whole
    // click, matching how the form behaves against the real backend.
    mocks.submit.mockImplementation(
      () => new Promise<void>((resolve) => setTimeout(resolve, 50)),
    );
    const screen = await render(
      <PersonaForm
        initial={{
          ...initialPersonaValues,
          knowledge_base_id: "kb-1",
        }}
        submitLabel="Lưu thay đổi"
        onSubmit={mocks.submit}
      />,
    );

    await screen.getByLabelText("Tên Agent").fill("Agent tuyển dụng");
    // Section textareas live inside closed disclosures; open section 1 first.
    await screen.getByText("Phần 1").click();
    await screen
      .getByLabelText("Vai trò của tôi")
      .fill("Tư vấn ứng viên 24/7.");
    await screen.getByLabelText("Ghi chú nội bộ").fill("Pipeline nội bộ.");

    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    await vi.waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
    const sections = parsePersonaMarkdown("").sections;
    sections[0] = "Tư vấn ứng viên 24/7.";
    expect(mocks.submit).toHaveBeenCalledWith({
      name: "Agent tuyển dụng",
      body_md: composePersonaMarkdown(sections, ""),
      notes: "Pipeline nội bộ.",
      knowledge_base_id: "kb-1",
      followup_rules: normalizePersonaFollowupRules(undefined),
    });
  });

  it("re-enables the save action after a failed save", async () => {
    // PersonaForm deliberately does not catch: PersonaCreate/PersonaEdit own
    // the error notify, so the rejection escapes the form via `void submit()`.
    // Tame that expected unhandled rejection for this test.
    const escapedErrors: unknown[] = [];
    const tameEscapedRejection = (event: PromiseRejectionEvent) => {
      escapedErrors.push(event.reason);
      event.preventDefault();
    };
    window.addEventListener("unhandledrejection", tameEscapedRejection);

    try {
      mocks.submit.mockRejectedValue(new Error("Không lưu được Agent."));
      const screen = await render(
        <PersonaForm
          initial={{
            ...initialPersonaValues,
            name: "Agent chính",
            knowledge_base_id: "kb-1",
          }}
          submitLabel="Lưu thay đổi"
          onSubmit={mocks.submit}
        />,
      );

      await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

      await vi.waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Lưu thay đổi" }).elements(),
        ).toHaveLength(1),
      );
      await expect
        .element(screen.getByRole("button", { name: "Lưu thay đổi" }))
        .toBeEnabled();
      expect(escapedErrors).toEqual([new Error("Không lưu được Agent.")]);
    } finally {
      window.removeEventListener("unhandledrejection", tameEscapedRejection);
    }
  });
});
