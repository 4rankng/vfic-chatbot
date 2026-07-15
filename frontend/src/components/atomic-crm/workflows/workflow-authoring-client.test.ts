import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../providers/rest/api", () => ({ apiJson: api.apiJson }));

import {
  createBlankWorkflowVersion,
  getWorkflowVersion,
  listWorkflowVersions,
  publishWorkflowVersion,
} from "./workflow-authoring-client";

describe("workflow authoring client", () => {
  it("starts blank without a customer, recruitment, or sample fallback", () => {
    expect(createBlankWorkflowVersion()).toEqual({
      pack_key: "",
      workflow_key: "",
      label: "",
      stages: [],
      transitions: [],
      tags: [],
      case_attribute_schema: {},
    });
  });

  it("publishes the complete administrator-authored immutable version", async () => {
    const draft = {
      ...createBlankWorkflowVersion(),
      pack_key: "configured-pack",
      workflow_key: "support",
      label: "Quy trình hỗ trợ",
      stages: [
        {
          key: "new",
          label: "Mới",
          position: 0,
          is_initial: true,
          is_terminal: false,
        },
      ],
    };
    api.apiJson.mockResolvedValue({ id: "workflow-version" });

    await publishWorkflowVersion(draft);

    expect(api.apiJson).toHaveBeenCalledWith("/api/v1/admin/case-workflows", {
      method: "POST",
      body: draft,
    });
  });

  it("lists authored versions through the pre-active admin endpoint", async () => {
    api.apiJson.mockResolvedValue({ data: [{ id: "one" }], total: 1 });
    await expect(listWorkflowVersions()).resolves.toEqual([{ id: "one" }]);
  });

  it("loads the selected immutable workflow definition for Case fields", async () => {
    const id = "00000000-0000-4000-8000-000000000010";
    api.apiJson.mockResolvedValue({ id, case_attribute_schema: {} });

    await getWorkflowVersion(id);

    expect(api.apiJson).toHaveBeenCalledWith(`/api/v1/admin/case-workflows/${id}`);
  });
});
