import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as SetupAuthoringClientModule from "../../../installation/setup-authoring-client";
import type { InstallationCatalog } from "../../../installation/installation-client";

const mocks = vi.hoisted(() => ({
  createPersona: vi.fn(),
  getTemplate: vi.fn(),
  listPersonas: vi.fn(),
  listVersions: vi.fn(),
}));

vi.mock("../../../installation/setup-authoring-client", async (importOriginal) => {
  const actual = await importOriginal<typeof SetupAuthoringClientModule>();
  return {
    ...actual,
    createSetupPersona: mocks.createPersona,
    getSetupPersonaTemplate: mocks.getTemplate,
    listSetupPersonas: mocks.listPersonas,
    listSetupPersonaVersions: mocks.listVersions,
  };
});

import { PersonaStep } from "./InstallationSteps";

const catalog: InstallationCatalog = {
  schema_version: 1,
  packs: [],
  capabilities: [],
  locales: [],
  currencies: [],
  workflows: [],
  authored_workflow_versions: [],
  integration_keys: [],
  authentication_methods: ["email_password"],
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("PersonaStep", () => {
  it("creates an agent when the wizard saves, with proactive follow-up disabled by default", async () => {
    const personaId = "00000000-0000-4000-8000-000000000001";
    const versionId = "00000000-0000-4000-8000-000000000002";
    const checksum = "a".repeat(64);
    mocks.listPersonas.mockResolvedValue([]);
    mocks.createPersona.mockResolvedValue({
      id: personaId,
      name: "Agent do quản trị viên tạo",
    });
    mocks.listVersions.mockResolvedValue([
      {
        id: versionId,
        version_no: 1,
        checksum,
        created_at: "2026-07-15T00:00:00Z",
      },
    ]);
    const onChange = vi.fn();
    const saveRef: { current: (() => Promise<unknown>) | null } = { current: null };

    const screen = await render(
      <PersonaStep catalog={catalog} issues={[]} onChange={onChange} onRegisterSave={(next) => { saveRef.current = next; }} />,
    );
    await screen.getByLabelText("Tên Agent *").fill("Agent do quản trị viên tạo");
    await screen
      .getByLabelText("Nội dung và chính sách *")
      .fill("Nội dung do quản trị viên nhập");
    await expect.element(screen.getByText("Ghi chú")).not.toBeInTheDocument();
    await expect.element(screen.getByRole("button", { name: "Tạo và chọn phiên bản" })).not.toBeInTheDocument();
    const save = saveRef.current;
    if (!save) throw new Error("Persona save handler was not registered.");
    await save();

    expect(mocks.createPersona).toHaveBeenCalledWith({
      name: "Agent do quản trị viên tạo",
      body_md: "Nội dung do quản trị viên nhập",
      notes: null,
      followup_rules: {
        hot: { enabled: false, cadence_hours: [], eligible_stages: [] },
        warm: { enabled: false, cadence_hours: [], eligible_stages: [] },
        not_interested: { enabled: false, cadence_hours: [], eligible_stages: [] },
      },
    });
    await expect.element(screen.getByText("Chọn phiên bản Agent")).not.toBeInTheDocument();
    await expect.element(screen.getByText("Phiên bản 1")).not.toBeInTheDocument();
    await expect
      .element(screen.getByText("Xác nhận tắt theo dõi chủ động"))
      .not.toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith({
      persona_version_id: versionId,
      checksum,
    });
  });

  it("loads an editable starter template without creating an agent", async () => {
    const template = "### 1. Vai trò của tôi\n[Mô tả Agent]";
    mocks.listPersonas.mockResolvedValue([]);
    mocks.getTemplate.mockResolvedValue(template);

    const screen = await render(
      <PersonaStep catalog={catalog} issues={[]} onChange={vi.fn()} />,
    );
    await screen.getByRole("button", { name: "Tải mẫu" }).click();

    await expect.element(screen.getByLabelText("Nội dung và chính sách *")).toHaveValue(template);
    expect(mocks.createPersona).not.toHaveBeenCalled();
  });

  it("selects the latest Agent revision without exposing revision controls", async () => {
    const firstVersion = "00000000-0000-4000-8000-000000000011";
    const latestVersion = "00000000-0000-4000-8000-000000000012";
    mocks.listPersonas.mockResolvedValue([
      { id: "00000000-0000-4000-8000-000000000010", name: "Tư vấn tuyển dụng" },
    ]);
    mocks.listVersions.mockResolvedValue([
      { id: firstVersion, version_no: 1, checksum: "b".repeat(64), created_at: "2026-07-15T00:00:00Z" },
      { id: latestVersion, version_no: 2, checksum: "c".repeat(64), created_at: "2026-07-16T00:00:00Z" },
    ]);
    const onChange = vi.fn();

    const screen = await render(
      <PersonaStep catalog={catalog} issues={[]} onChange={onChange} />,
    );
    const agentSelect = screen.getByLabelText("Agent", { exact: true });
    await expect.element(agentSelect).toHaveTextContent("Tư vấn tuyển dụng");
    await agentSelect.selectOptions("00000000-0000-4000-8000-000000000010");

    expect(onChange).toHaveBeenCalledWith({
      persona_version_id: latestVersion,
      checksum: "c".repeat(64),
    });
    await expect.element(screen.getByText("Phiên bản 2")).not.toBeInTheDocument();
  });

  it("explains an unavailable Agent without exposing its revision storage", async () => {
    mocks.listPersonas.mockResolvedValue([
      { id: "00000000-0000-4000-8000-000000000020", name: "Agent cũ" },
    ]);
    mocks.listVersions.mockResolvedValue([]);

    const screen = await render(
      <PersonaStep catalog={catalog} issues={[]} onChange={vi.fn()} />,
    );
    const agentSelect = screen.getByLabelText("Agent", { exact: true });
    await expect.element(agentSelect).toHaveTextContent("Agent cũ");
    await agentSelect.selectOptions("00000000-0000-4000-8000-000000000020");

    await expect
      .element(screen.getByText("Agent này chưa sẵn sàng để sử dụng. Hãy chọn Agent khác hoặc tạo Agent mới."))
      .toBeVisible();
    await expect.element(screen.getByText("phiên bản bất biến")).not.toBeInTheDocument();
  });
});
