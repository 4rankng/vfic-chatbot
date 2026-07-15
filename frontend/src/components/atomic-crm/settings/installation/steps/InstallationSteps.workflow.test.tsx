import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstallationCatalog } from "../../../installation/installation-client";

vi.mock("../../../workflows/WorkflowAuthoringPage", () => ({
  WorkflowAuthoringPage: () => <div>Tạo phiên bản trống</div>,
}));

import { WorkflowStep } from "./InstallationSteps";

const versionId = "00000000-0000-4000-8000-000000000011";
const checksum = "d".repeat(64);
const catalog: InstallationCatalog = {
  schema_version: 1,
  packs: [
    {
      key: "configured-pack",
      version: "1",
      contract_hash: "a".repeat(64),
      capability_ids: [],
      runtime_ready: false,
      workflow_ids: ["support"],
      terminology_keys: [],
    },
    {
      key: "alternate-pack",
      version: "1",
      contract_hash: "b".repeat(64),
      capability_ids: [],
      runtime_ready: false,
      workflow_ids: ["billing"],
      terminology_keys: [],
    },
  ],
  capabilities: [],
  locales: ["vi-VN"],
  currencies: ["VND"],
  workflows: [
    { id: "support", handoff_modes: ["manual", "assisted", "automatic"] },
    { id: "billing", handoff_modes: ["manual"] },
  ],
  authored_workflow_versions: [
    {
      id: versionId,
      pack_key: "configured-pack",
      workflow_key: "support",
      version_no: 2,
      label: "Quy trình hỗ trợ",
      checksum,
    },
    {
      id: "00000000-0000-4000-8000-000000000012",
      pack_key: "alternate-pack",
      workflow_key: "billing",
      version_no: 1,
      label: "Quy trình thanh toán",
      checksum: "e".repeat(64),
    },
  ],
  integration_keys: [],
  authentication_methods: ["email_password"],
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("WorkflowStep", () => {
  it("requires an explicit authored version and persists its hidden checksum", async () => {
    const onChange = vi.fn();
    const screen = await render(
      <WorkflowStep
        catalog={catalog}
        issues={[]}
        selectedPackKey="configured-pack"
        onChange={onChange}
      />,
    );

    await screen.getByLabelText("Quy trình *").selectOptions("support");
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    await screen.getByLabelText("Phiên bản đã xuất bản *").selectOptions(versionId);
    await screen.getByLabelText("Cách bàn giao *").selectOptions("assisted");
    await screen.getByRole("radio", { name: "Bật tự động hóa", exact: true }).click();

    expect(onChange).toHaveBeenLastCalledWith({
      workflow_policy: {
        workflow_id: "support",
        workflow_version_id: versionId,
        workflow_version_checksum: checksum,
        handoff_mode: "assisted",
        automation_enabled: true,
      },
    });
    await expect.element(screen.getByText("Tạo phiên bản trống")).toBeVisible();
  });

  it("invalidates a completed parent value immediately when a selector changes or clears", async () => {
    const onChange = vi.fn();
    const value = {
      workflow_policy: {
        workflow_id: "support",
        workflow_version_id: versionId,
        workflow_version_checksum: checksum,
        handoff_mode: "manual" as const,
        automation_enabled: false,
      },
    };
    const screen = await render(
      <WorkflowStep catalog={catalog} issues={[]} selectedPackKey="configured-pack" value={value} onChange={onChange} />,
    );

    await screen.getByLabelText("Phiên bản đã xuất bản *").selectOptions("");
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    await expect.element(screen.getByLabelText("Phiên bản đã xuất bản *")).toHaveValue("");
  });

  it("synchronizes discarded/reloaded values and clears selectors on pack change", async () => {
    const onChange = vi.fn();
    const configuredValue = {
      workflow_policy: {
        workflow_id: "support",
        workflow_version_id: versionId,
        workflow_version_checksum: checksum,
        handoff_mode: "assisted" as const,
        automation_enabled: true,
      },
    };
    const screen = await render(
      <WorkflowStep catalog={catalog} issues={[]} selectedPackKey="configured-pack" value={configuredValue} onChange={onChange} />,
    );
    await expect.element(screen.getByLabelText("Quy trình *")).toHaveValue("support");
    await expect.element(screen.getByRole("radio", { name: "Bật tự động hóa", exact: true })).toBeChecked();

    await screen.rerender(
      <WorkflowStep catalog={catalog} issues={[]} selectedPackKey="alternate-pack" onChange={onChange} />,
    );
    await expect.element(screen.getByLabelText("Quy trình *")).toHaveValue("");
    await expect.element(screen.getByLabelText("Phiên bản đã xuất bản *")).toBeDisabled();
    await expect.element(screen.getByRole("radio", { name: "Bật tự động hóa", exact: true })).not.toBeChecked();
  });

  it("clears an incomplete local selection when discard reloads the same empty parent value", async () => {
    const onChange = vi.fn();
    const screen = await render(
      <WorkflowStep catalog={catalog} issues={[]} selectedPackKey="configured-pack" syncToken={0} onChange={onChange} />,
    );
    await screen.getByLabelText("Quy trình *").selectOptions("support");
    await expect.element(screen.getByLabelText("Quy trình *")).toHaveValue("support");

    await screen.rerender(
      <WorkflowStep catalog={catalog} issues={[]} selectedPackKey="configured-pack" syncToken={1} onChange={onChange} />,
    );
    await expect.element(screen.getByLabelText("Quy trình *")).toHaveValue("");
  });
});
