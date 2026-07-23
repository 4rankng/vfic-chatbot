import { render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdapterPersonaAssignment, Persona } from "../types";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  refresh: vi.fn(),
  listPersonaAssignments:
    vi.fn<() => Promise<{ data: AdapterPersonaAssignment[] }>>(),
  updatePersonaAssignment:
    vi.fn<
      (
        provider: string,
        personaId: string | null,
      ) => Promise<AdapterPersonaAssignment>
    >(),
  activatePersona: vi.fn<() => Promise<unknown>>(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

vi.mock("./personaService", () => ({
  activatePersona: mocks.activatePersona,
  listPersonaAssignments: mocks.listPersonaAssignments,
  updatePersonaAssignment: mocks.updatePersonaAssignment,
}));

import { PersonaAssignments } from "./PersonaAssignments";

const persona: Persona = {
  id: "persona-1",
  knowledge_base_id: "kb-1",
  name: "Agent chính",
  slug: "agent-chinh",
  body_md: "## Vai trò\nTư vấn",
  followup_rules: {
    hot: { enabled: true, cadence_hours: [4], eligible_stages: ["NEW"] },
    warm: { enabled: false, cadence_hours: [], eligible_stages: ["NEW"] },
    not_interested: {
      enabled: false,
      cadence_hours: [],
      eligible_stages: ["SKIPPED"],
    },
  },
  is_active: false,
  notes: null,
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const defaultPersona: Persona = {
  ...persona,
  is_active: true,
};

const baseAssignments = (
  overrides: Partial<
    Record<
      AdapterPersonaAssignment["provider"],
      Partial<AdapterPersonaAssignment>
    >
  > = {},
): AdapterPersonaAssignment[] => [
  {
    provider: "zalo_bot",
    label: "Zalo Chatbot",
    persona_id: null,
    effective_persona_id: "persona-default",
    is_default: true,
    ...overrides.zalo_bot,
  },
  {
    provider: "zalo_oa",
    label: "Zalo OA",
    persona_id: null,
    effective_persona_id: "persona-default",
    is_default: true,
    ...overrides.zalo_oa,
  },
  {
    provider: "facebook_messenger",
    label: "Messenger",
    persona_id: null,
    effective_persona_id: "persona-default",
    is_default: true,
    ...overrides.facebook_messenger,
  },
];

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
};

describe("PersonaAssignments", () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.refresh.mockReset();
    mocks.listPersonaAssignments.mockReset();
    mocks.updatePersonaAssignment.mockReset();
    mocks.activatePersona.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("disables redundant assignment when the current default persona is already inherited", async () => {
    mocks.listPersonaAssignments.mockResolvedValue({
      data: baseAssignments({
        zalo_bot: {
          effective_persona_id: defaultPersona.id,
          is_default: true,
        },
      }),
    });

    const screen = await render(
      <PersonaAssignments persona={defaultPersona} />,
    );

    await expect.element(screen.getByText("Đang dùng")).toBeVisible();
    await expect
      .element(
        screen.getByRole("button", { name: "Đang mặc định cho Zalo Chatbot" }),
      )
      .toBeDisabled();
  });

  it("assigns the current persona to an adapter override", async () => {
    mocks.listPersonaAssignments
      .mockResolvedValueOnce({
        data: baseAssignments({
          zalo_oa: {
            effective_persona_id: "persona-default",
            is_default: true,
          },
        }),
      })
      .mockResolvedValueOnce({
        data: baseAssignments({
          zalo_oa: {
            persona_id: persona.id,
            effective_persona_id: persona.id,
            is_default: false,
          },
        }),
      });
    mocks.updatePersonaAssignment.mockResolvedValue({
      provider: "zalo_oa",
      label: "Zalo OA",
      persona_id: persona.id,
      effective_persona_id: persona.id,
      is_default: false,
    });

    const screen = await render(<PersonaAssignments persona={persona} />);

    await screen
      .getByRole("button", { name: "Gán Agent này cho Zalo OA" })
      .click();

    await expect
      .poll(() => mocks.updatePersonaAssignment.mock.calls[0])
      .toEqual(["zalo_oa", persona.id]);
    await expect
      .element(screen.getByText("Đã gán Agent cho adapter."))
      .toBeVisible();
  });

  it("resets an explicit adapter override back to the default persona", async () => {
    mocks.listPersonaAssignments
      .mockResolvedValueOnce({
        data: baseAssignments({
          facebook_messenger: {
            persona_id: persona.id,
            effective_persona_id: persona.id,
            is_default: false,
          },
        }),
      })
      .mockResolvedValueOnce({
        data: baseAssignments({
          facebook_messenger: {
            persona_id: null,
            effective_persona_id: "persona-default",
            is_default: true,
          },
        }),
      });
    mocks.updatePersonaAssignment.mockResolvedValue({
      provider: "facebook_messenger",
      label: "Messenger",
      persona_id: null,
      effective_persona_id: "persona-default",
      is_default: true,
    });

    const screen = await render(<PersonaAssignments persona={persona} />);

    await screen
      .getByRole("button", { name: "Trả về mặc định cho Messenger" })
      .click();

    await expect
      .poll(() => mocks.updatePersonaAssignment.mock.calls[0])
      .toEqual(["facebook_messenger", null]);
    await expect
      .element(screen.getByText("Đã trả adapter về Agent mặc định."))
      .toBeVisible();
  });

  it("ignores an older assignment response that resolves after a newer one", async () => {
    mocks.listPersonaAssignments.mockResolvedValueOnce({
      data: baseAssignments(),
    });
    const older = deferred<{ data: AdapterPersonaAssignment[] }>();
    const newer = deferred<{ data: AdapterPersonaAssignment[] }>();
    mocks.listPersonaAssignments
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise);

    const screen = await render(<PersonaAssignments persona={persona} />);
    await expect.element(screen.getByText("0/3")).toBeVisible();

    await screen
      .getByRole("button", { name: "Tải lại trạng thái Zalo Chatbot" })
      .click();
    await screen
      .getByRole("button", { name: "Tải lại trạng thái Zalo OA" })
      .click();

    newer.resolve({
      data: baseAssignments({
        zalo_bot: { effective_persona_id: persona.id },
        zalo_oa: { effective_persona_id: persona.id },
        facebook_messenger: { effective_persona_id: persona.id },
      }),
    });
    await expect.element(screen.getByText("3/3")).toBeVisible();

    older.resolve({ data: baseAssignments() });
    await new Promise((resolve) => setTimeout(resolve, 20));
    await expect.element(screen.getByText("3/3")).toBeVisible();
  });

  it("does not report success for a stale refresh after a newer refresh fails", async () => {
    mocks.listPersonaAssignments.mockResolvedValueOnce({
      data: baseAssignments(),
    });
    const older = deferred<{ data: AdapterPersonaAssignment[] }>();
    const newer = deferred<{ data: AdapterPersonaAssignment[] }>();
    mocks.listPersonaAssignments
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise);

    const screen = await render(<PersonaAssignments persona={persona} />);
    await expect.element(screen.getByText("0/3")).toBeVisible();

    await screen
      .getByRole("button", { name: "Tải lại trạng thái Zalo Chatbot" })
      .click();
    await screen
      .getByRole("button", { name: "Tải lại trạng thái Zalo OA" })
      .click();

    newer.reject(new Error("Không tải được cấu hình adapter."));
    await expect
      .element(screen.getByText("Không tải được cấu hình adapter."))
      .toBeVisible();

    older.resolve({ data: baseAssignments() });
    await new Promise((resolve) => setTimeout(resolve, 20));
    await expect
      .element(screen.getByText("Đã tải lại trạng thái adapter."))
      .not.toBeInTheDocument();
  });
});
