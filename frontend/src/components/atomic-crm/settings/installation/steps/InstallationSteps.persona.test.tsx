import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as SetupAuthoringClientModule from "../../../installation/setup-authoring-client";
import type { InstallationCatalog } from "../../../installation/installation-client";

const mocks = vi.hoisted(() => ({
  createPersona: vi.fn(),
  listPersonas: vi.fn(),
  listVersions: vi.fn(),
}));

vi.mock("../../../installation/setup-authoring-client", async (importOriginal) => {
  const actual = await importOriginal<typeof SetupAuthoringClientModule>();
  return {
    ...actual,
    createSetupPersona: mocks.createPersona,
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
  it("requires an explicit disabled follow-up choice and sends the neutral policy", async () => {
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

    const screen = await render(
      <PersonaStep catalog={catalog} issues={[]} onChange={onChange} />,
    );
    await screen.getByLabelText("Tên Agent *").fill("Agent do quản trị viên tạo");
    await screen
      .getByLabelText("Nội dung và chính sách *")
      .fill("Nội dung do quản trị viên nhập");
    const createButton = screen.getByRole("button", {
      name: "Tạo và chọn phiên bản",
    });

    await expect.element(createButton).toBeDisabled();
    expect(mocks.createPersona).not.toHaveBeenCalled();
    await screen
      .getByRole("checkbox", { name: /Xác nhận tắt theo dõi chủ động/ })
      .click();
    await expect.element(createButton).toBeEnabled();
    await createButton.click();

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
    await expect.element(screen.getByText("Phiên bản 1")).toBeVisible();
    expect(onChange).toHaveBeenCalledWith({
      persona_version_id: versionId,
      checksum,
    });
  });
});
