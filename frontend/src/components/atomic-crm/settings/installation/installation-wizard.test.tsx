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
  IdentityBrandingStep: ({ onChange }: { onChange: (value: unknown) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          customer_identity: { display_name: "Khách hàng tự nhập" },
          branding: { app_name: "Ứng dụng tự nhập" },
        })
      }
    >
      Điền danh tính
    </button>
  ),
  RegionalTerminologyStep: () => <p>Khu vực</p>,
  PackCapabilitiesStep: ({ onChange }: { onChange: (value: unknown) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({ pack_key: "alternate-pack", capability_ids: [] })
      }
    >
      Chọn gói khác
    </button>
  ),
  WorkflowStep: ({ onChange }: { onChange: (value: undefined) => void }) => (
    <><p>Quy trình</p><button type="button" onClick={() => onChange(undefined)}>Xoá lựa chọn quy trình</button></>
  ),
  KnowledgeTemplatesStep: () => <p>Kiến thức</p>,
  PersonaStep: () => <p>Agent</p>,
  ProvidersIntegrationsStep: () => <p>Tích hợp</p>,
}));

import {
  InstallationClientError,
  type InstallationSetupDraft,
} from "../../installation/installation-client";
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

const adminStatus = (validated: boolean) => ({
  lifecycle: validated ? "VALIDATED" : "DRAFT",
  authority_generation: 1,
  lock_version: 8,
  current_revision: validated ? { id: "00000000-0000-4000-8000-000000000009" } : null,
  active_revision_id: null,
  active_validation: null,
  current_validation: validated
    ? {
        revision_id: "00000000-0000-4000-8000-000000000009",
        is_valid: true,
      }
    : null,
  readiness_code: "SETUP_REQUIRED",
});

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("InstallationWizard", () => {
  it("reloads current validation and prevents duplicate finalization", async () => {
    mocks.getDraft.mockResolvedValue(draft());
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.getAdminStatus.mockResolvedValue(adminStatus(true));

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: /Rà soát/ }).click();

    await expect.element(screen.getByRole("button", { name: "Đã xác nhận" })).toBeDisabled();
    expect(mocks.getAdminStatus).toHaveBeenCalledOnce();
    expect(mocks.finalize).not.toHaveBeenCalled();
  });

  it("preserves the dirty section and reapplies it over a newer server draft", async () => {
    const emptyDraft = draft({
      payload: {},
      section_completion: Object.fromEntries(
        Object.keys(sectionCompletion).map((key) => [key, false]),
      ),
      issues: [],
    });
    const serverRegional = completePayload.regional_terminology;
    const latest = draft({
      payload: { regional_terminology: serverRegional },
      lock_version: 5,
    });
    mocks.getDraft.mockResolvedValueOnce(emptyDraft).mockResolvedValueOnce(latest);
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.getAdminStatus.mockResolvedValue(adminStatus(false));
    mocks.saveDraft
      .mockRejectedValueOnce(
        new InstallationClientError(
          "conflict",
          409,
          "INSTALLATION_CONFLICT",
          "DRAFT",
          [],
        ),
      )
      .mockImplementationOnce(async (payload) => draft({ payload, lock_version: 6 }));

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: "Điền danh tính" }).click();
    await screen.getByRole("button", { name: "Lưu bước" }).click();
    await expect.element(screen.getByText("Bản nháp đã được thay đổi ở nơi khác")).toBeVisible();
    await screen.getByRole("button", { name: "Áp dụng lại phần đã sửa" }).click();

    expect(mocks.saveDraft).toHaveBeenLastCalledWith(
      expect.objectContaining({
        identity_branding: expect.objectContaining({
          customer_identity: { display_name: "Khách hàng tự nhập" },
        }),
        regional_terminology: serverRegional,
      }),
      5,
    );
  });

  it("removes pack-dependent workflow and stale terminology during conflict merge", async () => {
    const latest = draft({ lock_version: 5 });
    mocks.getDraft.mockResolvedValueOnce(draft()).mockResolvedValueOnce(latest);
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.getAdminStatus.mockResolvedValue(adminStatus(false));
    mocks.saveDraft
      .mockRejectedValueOnce(
        new InstallationClientError(
          "conflict",
          409,
          "INSTALLATION_CONFLICT",
          "DRAFT",
          [],
        ),
      )
      .mockImplementationOnce(async (payload) => draft({ payload, lock_version: 6 }));

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: /^Gói$/ }).click();
    await screen.getByRole("button", { name: "Chọn gói khác" }).click();
    await screen.getByRole("button", { name: "Lưu bước" }).click();
    await expect.element(screen.getByText("Bản nháp đã được thay đổi ở nơi khác")).toBeVisible();
    await screen.getByRole("button", { name: "Áp dụng lại phần đã sửa" }).click();

    const mergedPayload = mocks.saveDraft.mock.calls.at(-1)?.[0];
    expect(mergedPayload).toMatchObject({
      pack_capabilities: { pack_key: "alternate-pack", capability_ids: [] },
      regional_terminology: { terminology: {} },
    });
    expect(mergedPayload).not.toHaveProperty("workflow");
    expect(mocks.saveDraft).toHaveBeenLastCalledWith(mergedPayload, 5);
  });

  it("does not save a stale completed workflow after the visible selection is cleared", async () => {
    mocks.getDraft.mockResolvedValue(draft());
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.getAdminStatus.mockResolvedValue(adminStatus(false));

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: /^Quy trình$/ }).click();
    await screen.getByRole("button", { name: "Xoá lựa chọn quy trình" }).click();
    await screen.getByRole("button", { name: "Lưu bước" }).click();

    expect(mocks.saveDraft).not.toHaveBeenCalled();
    await expect.element(screen.getByText(/chưa đủ thông tin bắt buộc/)).toBeVisible();
  });

  it("finalizes with both locks while activation and no-send testing stay unavailable", async () => {
    mocks.getDraft.mockResolvedValue(draft());
    mocks.getCatalog.mockResolvedValue(catalog);
    mocks.getAdminStatus.mockResolvedValue(adminStatus(false));
    mocks.finalize.mockResolvedValue({ id: "00000000-0000-4000-8000-000000000009" });
    mocks.refreshRuntime.mockResolvedValue(undefined);

    const screen = await render(<InstallationWizard />);
    await screen.getByRole("button", { name: /Rà soát/ }).click();
    await expect.element(screen.getByText(/chưa khả dụng cho đến khi cơ chế thực thi runtime/)).toBeVisible();
    await expect.element(screen.getByRole("button", { name: /Kích hoạt chưa khả dụng/ })).toBeDisabled();
    await screen.getByRole("button", { name: "Xác nhận cấu hình" }).click();

    expect(mocks.finalize).toHaveBeenCalledWith({
      expectedDraftLockVersion: 4,
      expectedInstallationLockVersion: 8,
    });
    expect(mocks.refreshRuntime).toHaveBeenCalledOnce();
  });
});
