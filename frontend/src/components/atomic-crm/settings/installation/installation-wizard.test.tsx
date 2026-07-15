import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as InstallationClientModule from "../../installation/installation-client";

const mocks = vi.hoisted(() => ({
  getDraft: vi.fn(),
  getCatalog: vi.fn(),
  getAdminStatus: vi.fn(),
  saveDraft: vi.fn(),
  finalize: vi.fn(),
  refreshRuntime: vi.fn(),
}));

vi.mock("../../installation/installation-client", async (importOriginal) => {
  const actual = await importOriginal<typeof InstallationClientModule>();
  return {
    ...actual,
    getInstallationSetupDraft: mocks.getDraft,
    getInstallationCatalog: mocks.getCatalog,
    getInstallationAdminStatus: mocks.getAdminStatus,
    saveInstallationSetupDraft: mocks.saveDraft,
    finalizeInstallationSetupDraft: mocks.finalize,
  };
});

vi.mock("../../installation/installation-context", () => ({
  useInstallationContext: () => ({
    manifest: { lifecycle: "DRAFT" },
    refreshRuntime: mocks.refreshRuntime,
  }),
}));

vi.mock("./steps/InstallationSteps", () => ({
  KnowledgeTemplatesStep: () => <p>Kiến thức</p>,
  PersonaStep: ({ onChange }: { onChange: (value: unknown) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          persona_version_id: "00000000-0000-4000-8000-000000000003",
          checksum: "a".repeat(64),
        })
      }
    >
      Chọn Agent
    </button>
  ),
  ProvidersIntegrationsStep: () => <p>Tích hợp</p>,
}));

import { type InstallationSetupDraft } from "../../installation/installation-client";
import { InstallationWizard } from "./InstallationWizard";

const checksum = "a".repeat(64);
const sectionCompletion = {
  identity_branding: true,
  regional_terminology: true,
  pack_capabilities: true,
  workflow: true,
  knowledge_templates: true,
  persona: true,
  providers_integrations: true,
};
const completePayload = {
  identity_branding: {
    customer_identity: { display_name: "Khách hàng" },
    branding: { app_name: "Ứng dụng" },
  },
  regional_terminology: {
    locale: "vi-VN",
    timezone: "Asia/Ho_Chi_Minh",
    currency: "VND",
    terminology: { contact: "Liên hệ" },
  },
  pack_capabilities: { pack_key: "configured-pack", capability_ids: [] },
  workflow: {
    workflow_policy: {
      workflow_id: "configured-workflow",
      workflow_version_id: "00000000-0000-4000-8000-000000000021",
      workflow_version_checksum: "c".repeat(64),
      handoff_mode: "manual" as const,
      automation_enabled: false,
    },
  },
  knowledge_templates: { template_version_refs: [] },
  persona: {
    persona_version_id: "00000000-0000-4000-8000-000000000003",
    checksum,
  },
  providers_integrations: {
    provider_policy: {
      chat_integration_key: "openrouter",
      chat_model: "model/chat",
      embedding_integration_key: "openrouter",
      embedding_model: "model/embed",
      temperature: 0,
      max_output_tokens: 100,
    },
    integration_requirements: [],
    authentication_policy: { email_password_enabled: true as const },
  },
};

const draft = (
  overrides: Partial<InstallationSetupDraft> = {},
): InstallationSetupDraft => ({
  payload: completePayload,
  lock_version: 4,
  installation_lock_version: 8,
  section_completion: sectionCompletion,
  issues: [],
  ...overrides,
});

const catalog = {
  schema_version: 1 as const,
  packs: [
    {
      key: "configured-pack",
      version: "1.0.0",
      contract_hash: checksum,
      capability_ids: [],
      runtime_ready: false,
      workflow_ids: ["configured-workflow"],
      terminology_keys: ["contact"],
    },
    {
      key: "alternate-pack",
      version: "1.0.0",
      contract_hash: checksum,
      capability_ids: [],
      runtime_ready: false,
      workflow_ids: ["configured-workflow"],
      terminology_keys: ["alternate_term"],
    },
  ],
  capabilities: [],
  locales: ["vi-VN"],
  currencies: ["VND"],
  workflows: [{ id: "configured-workflow", handoff_modes: ["manual" as const] }],
  authored_workflow_versions: [
    {
      id: "00000000-0000-4000-8000-000000000021",
      pack_key: "configured-pack",
      workflow_key: "configured-workflow",
      version_no: 1,
      label: "Quy trình đã cấu hình",
      checksum: "c".repeat(64),
    },
  ],
  integration_keys: ["minimax", "openrouter", "zalo"],
  authentication_methods: ["email_password" as const],
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("InstallationWizard", () => {
  it("opens an empty installation as an optional setup hub", async () => {
    mocks.getDraft.mockResolvedValue(
      draft({
        payload: {},
        section_completion: Object.fromEntries(
          Object.keys(sectionCompletion).map((key) => [key, false]),
        ),
      }),
    );
    mocks.getCatalog.mockResolvedValue(catalog);
    const screen = await render(<InstallationWizard />);

    await expect.element(screen.getByText("Thiết lập chatbot khi sẵn sàng")).toBeVisible();
    await expect.element(screen.getByText("Không có việc bắt buộc lúc khởi tạo")).toBeVisible();
    await screen.getByRole("button", { name: "Thiết lập Agent" }).click();
    await expect.element(screen.getByRole("navigation", { name: "Các bước thiết lập" })).toBeVisible();
  });

  it("shows only the three minimum chatbot settings in a responsive grid", async () => {
    mocks.getDraft.mockResolvedValue(draft());
    mocks.getCatalog.mockResolvedValue(catalog);

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: "Thiết lập Kết nối AI" }).click();
    const navigation = screen.getByRole("navigation", { name: "Các bước thiết lập" });

    await expect.element(navigation).toHaveClass("grid");
    await expect.element(navigation).toHaveClass("sm:grid-cols-3");
    await expect.element(navigation).not.toHaveClass("overflow-x-auto");
    await expect.element(screen.getByRole("button", { name: "Kết nối AI", exact: true })).toBeVisible();
    await expect.element(screen.getByRole("button", { name: "Agent", exact: true })).toBeVisible();
    await expect.element(screen.getByRole("button", { name: "Kiến thức", exact: true })).toBeVisible();
  });

  it("saves a selected persona without requiring unrelated setup data", async () => {
    mocks.getDraft.mockResolvedValue(
      draft({
        payload: {},
        section_completion: Object.fromEntries(
          Object.keys(sectionCompletion).map((key) => [key, false]),
        ),
      }),
    );
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.saveDraft.mockImplementation(async (payload) => draft({ payload, lock_version: 5 }));

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: "Thiết lập Agent" }).click();
    await screen.getByRole("button", { name: "Chọn Agent" }).click();
    await screen.getByRole("button", { name: "Lưu", exact: true }).click();

    expect(mocks.saveDraft).toHaveBeenCalledWith(
      { persona: expect.objectContaining({ checksum }) },
      4,
    );
  });
});
