import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

type TestKnowledgeBase = { id: string; name: string; mode: string };

const mocks = vi.hoisted(() => ({
  knowledgeBases: [] as TestKnowledgeBase[],
  notify: vi.fn(),
  submit: vi.fn<(values: PersonaValues) => Promise<void>>(),
}));

vi.mock("ra-core", () => {
  return {
    // The form reads its labels from the shipped Vietnamese catalog, so these
    // tests assert the same wording the app renders.
    useTranslate: () => testI18nProvider.translate,
    useNotify: () => mocks.notify,
    useGetList: () => ({ data: mocks.knowledgeBases, isPending: false }),
  };
});

import { PersonaForm, type PersonaValues } from "./PersonaForm";
import { testI18nProvider } from "../providers/commons/i18nProvider";
import {
  composePersonaMarkdown,
  parsePersonaMarkdown,
} from "./domain/personaMarkdown";
import { normalizePersonaFollowupRules } from "./domain/followupRules";

const TWO_KNOWLEDGE_BASES: TestKnowledgeBase[] = [
  { id: "kb-1", name: "KB tuyển dụng", mode: "RAG" },
  { id: "kb-2", name: "KB trực tiếp", mode: "DIRECT_CONTEXT" },
];

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

const initialPersonaValues = {
  name: "",
  body_md: "",
  notes: "",
  knowledge_base_id: "",
  followup_rules: undefined,
};

const renderForm = async (initial: PersonaValues) =>
  render(
    <PersonaForm
      initial={initial}
      submitLabel="Lưu thay đổi"
      onSubmit={mocks.submit}
    />,
  );

const saveButton = (screen: Awaited<ReturnType<typeof renderForm>>) =>
  screen.getByRole("button", { name: "Lưu thay đổi" });

describe("PersonaForm", () => {
  beforeEach(() => {
    mocks.knowledgeBases = [...TWO_KNOWLEDGE_BASES];
    mocks.submit.mockReset();
    mocks.notify.mockReset();
  });

  it("blocks the save and renders the required-field errors in order", async () => {
    const screen = await renderForm(initialPersonaValues);

    await saveButton(screen).click();

    // The name gate comes first: it renders its error and takes focus.
    const nameError = screen.getByText("Vui lòng nhập tên Agent.");
    await expect.element(nameError).toBeVisible();
    expect(document.activeElement?.id).toBe("persona-name");
    expect(
      screen.container
        .querySelector("#persona-name")
        ?.getAttribute("aria-invalid"),
    ).toBe("true");
    expect(mocks.submit).not.toHaveBeenCalled();

    // Typing clears the name error and moves the gate to the Knowledge Base.
    await screen.getByLabelText("Tên Agent").fill("Agent tuyển dụng");
    await expect.element(nameError).not.toBeInTheDocument();
    await saveButton(screen).click();
    await expect
      .element(screen.getByText("Vui lòng chọn Knowledge Base cho Agent."))
      .toBeVisible();
    expect(mocks.submit).not.toHaveBeenCalled();

    // Whitespace alone is not a name.
    await screen.getByLabelText("Tên Agent").fill("   ");
    await saveButton(screen).click();
    await expect
      .element(screen.getByText("Vui lòng nhập tên Agent."))
      .toBeVisible();
    expect(mocks.submit).not.toHaveBeenCalled();
  });

  it("clears the Knowledge Base error and submits the chosen Knowledge Base", async () => {
    mocks.submit.mockResolvedValue(undefined);
    const screen = await renderForm({
      ...initialPersonaValues,
      name: "Agent tuyển dụng",
    });

    await saveButton(screen).click();
    const knowledgeBaseError = screen.getByText(
      "Vui lòng chọn Knowledge Base cho Agent.",
    );
    await expect.element(knowledgeBaseError).toBeVisible();

    await screen.getByRole("combobox", { name: "Knowledge Base" }).click();
    await screen
      .getByRole("option", { name: "KB trực tiếp · Ngữ cảnh trực tiếp" })
      .click();

    await expect.element(knowledgeBaseError).not.toBeInTheDocument();
    await saveButton(screen).click();

    await vi.waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
    expect(mocks.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Agent tuyển dụng",
        knowledge_base_id: "kb-2",
      }),
    );
  });

  it("tells the editor to create a Knowledge Base before saving one", async () => {
    mocks.knowledgeBases = [];
    const screen = await renderForm(initialPersonaValues);

    await expect
      .element(screen.getByText("Tạo Knowledge Base trước khi tạo Agent."))
      .toBeVisible();
    await expect
      .element(screen.getByRole("combobox", { name: "Knowledge Base" }))
      .toBeDisabled();
  });

  it("gates the save action for the whole in-flight window", async () => {
    // Held open by hand so the gate window is fully under the test's control
    // rather than racing a timer.
    const inFlight = deferred<void>();
    mocks.submit.mockImplementation(() => inFlight.promise);
    const screen = await renderForm({
      ...initialPersonaValues,
      name: "Agent chính",
      knowledge_base_id: "kb-1",
    });

    // Untouched form: the action is live, not busy.
    await expect.element(saveButton(screen)).toBeEnabled();
    expect(saveButton(screen).element().getAttribute("aria-busy")).toBe(
      "false",
    );

    await saveButton(screen).click();
    await vi.waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));

    // While the save is in flight the action is disabled, announces itself
    // busy, and swaps its Vietnamese label to the saving copy.
    const savingButton = screen.getByRole("button", { name: "Đang lưu…" });
    await expect.element(savingButton).toBeDisabled();
    expect(savingButton.element().getAttribute("aria-busy")).toBe("true");
    await expect
      .element(screen.getByText("Lưu thay đổi"))
      .not.toBeInTheDocument();

    // The form stays readable and editable while the save is in flight.
    await expect
      .element(screen.getByLabelText("Tên Agent"))
      .toHaveValue("Agent chính");

    inFlight.resolve(undefined);
    await vi.waitFor(() =>
      expect(saveButton(screen).elements()).toHaveLength(1),
    );
    await expect.element(saveButton(screen)).toBeEnabled();
    expect(saveButton(screen).element().getAttribute("aria-busy")).toBe(
      "false",
    );
  });

  it("sends the composed persona payload on save", async () => {
    // Held open by hand so the click is not racing the save's own resolution.
    const saved = deferred<void>();
    mocks.submit.mockImplementation(() => saved.promise);
    const screen = await renderForm({
      ...initialPersonaValues,
      knowledge_base_id: "kb-1",
    });

    await screen.getByLabelText("Tên Agent").fill("Agent tuyển dụng");
    // Section textareas live inside closed disclosures; open section 1 first.
    await screen.getByText("Phần 1").click();
    await screen
      .getByLabelText("Vai trò của tôi")
      .fill("Tư vấn ứng viên 24/7.");
    await screen.getByLabelText("Ghi chú nội bộ").fill("Pipeline nội bộ.");

    await saveButton(screen).click();

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
    saved.resolve(undefined);
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
      const screen = await renderForm({
        ...initialPersonaValues,
        name: "Agent chính",
        knowledge_base_id: "kb-1",
      });

      await saveButton(screen).click();

      await vi.waitFor(() =>
        expect(saveButton(screen).elements()).toHaveLength(1),
      );
      // The failed save is retryable: the action comes back with the same
      // label, not stuck on the saving copy.
      await expect.element(saveButton(screen)).toBeEnabled();
      expect(saveButton(screen).element().getAttribute("aria-busy")).toBe(
        "false",
      );
      expect(escapedErrors).toEqual([new Error("Không lưu được Agent.")]);

      // Retrying goes through, so the form is not wedged after a failure.
      mocks.submit.mockResolvedValue(undefined);
      await saveButton(screen).click();
      await vi.waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    } finally {
      window.removeEventListener("unhandledrejection", tameEscapedRejection);
    }
  });
});
