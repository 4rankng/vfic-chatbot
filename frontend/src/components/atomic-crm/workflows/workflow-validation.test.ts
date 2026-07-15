import { describe, expect, it } from "vitest";

import { createBlankWorkflowVersion } from "./workflow-authoring-client";
import { validateWorkflowGraph } from "./workflow-validation";

const validDraft = () => ({
  ...createBlankWorkflowVersion(),
  pack_key: "configured-pack",
  workflow_key: "support",
  label: "Hỗ trợ",
  stages: [
    { key: "new", label: "Mới", position: 0, is_initial: true, is_terminal: false },
    { key: "done", label: "Hoàn tất", position: 1, is_initial: false, is_terminal: true },
  ],
  transitions: [{ from_stage_key: "new", to_stage_key: "done" }],
});

const codes = (draft = validDraft(), attributeKeys: string[] = []) =>
  validateWorkflowGraph(draft, attributeKeys).map((issue) => issue.code);

describe("validateWorkflowGraph", () => {
  it("accepts a reachable graph with an explicit terminal stage", () => {
    expect(codes()).toEqual([]);
  });

  it("requires a terminal stage", () => {
    const draft = validDraft();
    draft.stages[1]!.is_terminal = false;
    expect(codes(draft)).toContain("TERMINAL_REQUIRED");
  });

  it("rejects an initial stage that is also terminal", () => {
    const draft = validDraft();
    draft.stages[0]!.is_terminal = true;
    expect(codes(draft)).toContain("INITIAL_TERMINAL");
  });

  it("rejects duplicate stage, tag, attribute keys and positions", () => {
    const draft = validDraft();
    draft.stages[1]!.key = "new";
    draft.stages[1]!.position = 0;
    draft.tags = [
      { key: "urgent", label: "Khẩn", tone: "danger", position: 0 },
      { key: "urgent", label: "Rất khẩn", tone: "warning", position: 0 },
    ];
    expect(codes(draft, ["tier", "tier"])).toEqual(
      expect.arrayContaining(["STAGE_KEY_DUPLICATE", "STAGE_POSITION_DUPLICATE", "TAG_KEY_DUPLICATE", "TAG_POSITION_DUPLICATE", "ATTRIBUTE_KEY_DUPLICATE"]),
    );
  });

  it("rejects self transitions and outgoing transitions from terminal stages", () => {
    const draft = validDraft();
    draft.transitions.push({ from_stage_key: "done", to_stage_key: "done" });
    expect(codes(draft)).toEqual(expect.arrayContaining(["TRANSITION_SELF", "TERMINAL_OUTGOING"]));
  });

  it("rejects unreachable stages", () => {
    const draft = validDraft();
    draft.stages.push({ key: "waiting", label: "Chờ", position: 2, is_initial: false, is_terminal: false });
    expect(codes(draft)).toContain("STAGE_UNREACHABLE");
  });

  it("rejects stale transition endpoints after a stage key is edited", () => {
    const draft = validDraft();
    draft.stages[1]!.key = "closed";
    expect(codes(draft)).toContain("TRANSITION_ENDPOINT");
  });

  it("rejects known-invalid stage, tag, and protected attribute keys", () => {
    const draft = validDraft();
    draft.stages[1]!.key = "Not Valid";
    draft.tags = [{ key: "Bad Tag", label: "Sai", tone: "warning", position: 0 }];
    expect(codes(draft, ["stage_key"])).toEqual(
      expect.arrayContaining(["STAGE_KEY_INVALID", "TAG_KEY_INVALID", "ATTRIBUTE_KEY_INVALID"]),
    );
  });
});
