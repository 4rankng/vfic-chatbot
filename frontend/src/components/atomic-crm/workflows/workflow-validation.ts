import type { WorkflowVersionDraft } from "./workflow-authoring-client";

export type WorkflowValidationIssue = Readonly<{
  code: string;
  message: string;
}>;

const duplicateValues = (values: readonly string[]): string[] => {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values.map((item) => item.trim()).filter(Boolean)) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return [...duplicates];
};

export const validateWorkflowGraph = (
  draft: WorkflowVersionDraft,
  attributeKeys: readonly string[],
): WorkflowValidationIssue[] => {
  const issues: WorkflowValidationIssue[] = [];
  const stageKeys = draft.stages.map((stage) => stage.key.trim());
  const knownStageKeys = new Set(stageKeys.filter(Boolean));
  const initialStages = draft.stages.filter((stage) => stage.is_initial);
  const terminalStages = draft.stages.filter((stage) => stage.is_terminal);
  const terminalKeys = new Set(terminalStages.map((stage) => stage.key.trim()).filter(Boolean));

  if (draft.stages.some((stage) => !stage.key.trim() || !stage.label.trim())) {
    issues.push({ code: "STAGE_REQUIRED", message: "Mỗi giai đoạn cần có mã và tên hiển thị." });
  }
  if (initialStages.length !== 1) {
    issues.push({ code: "INITIAL_COUNT", message: "Chọn đúng một giai đoạn bắt đầu." });
  }
  if (terminalStages.length === 0) {
    issues.push({ code: "TERMINAL_REQUIRED", message: "Chọn ít nhất một giai đoạn kết thúc." });
  }
  if (duplicateValues(stageKeys).length > 0) {
    issues.push({ code: "STAGE_KEY_DUPLICATE", message: "Mã giai đoạn không được trùng nhau." });
  }
  if (new Set(draft.stages.map((stage) => stage.position)).size !== draft.stages.length) {
    issues.push({ code: "STAGE_POSITION_DUPLICATE", message: "Thứ tự giai đoạn không được trùng nhau." });
  }

  const transitionPairs = new Set<string>();
  for (const transition of draft.transitions) {
    const from = transition.from_stage_key.trim();
    const to = transition.to_stage_key.trim();
    if (!from || !to) {
      issues.push({ code: "TRANSITION_REQUIRED", message: "Mỗi luồng chuyển cần đủ giai đoạn đầu và giai đoạn tiếp theo." });
      continue;
    }
    if (!knownStageKeys.has(from) || !knownStageKeys.has(to)) {
      issues.push({ code: "TRANSITION_ENDPOINT", message: "Luồng chuyển phải dùng các giai đoạn đang có trong bản nháp." });
    }
    if (from === to) {
      issues.push({ code: "TRANSITION_SELF", message: "Một giai đoạn không thể tự chuyển sang chính nó." });
    }
    if (terminalKeys.has(from)) {
      issues.push({ code: "TERMINAL_OUTGOING", message: "Giai đoạn kết thúc không được có luồng chuyển đi." });
    }
    const pair = `${from}\u0000${to}`;
    if (transitionPairs.has(pair)) {
      issues.push({ code: "TRANSITION_DUPLICATE", message: "Luồng chuyển không được lặp lại." });
    }
    transitionPairs.add(pair);
  }

  if (
    initialStages.length === 1 &&
    knownStageKeys.size === draft.stages.length &&
    !issues.some((issue) => issue.code === "TRANSITION_ENDPOINT")
  ) {
    const reachable = new Set<string>([initialStages[0]!.key.trim()]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const transition of draft.transitions) {
        if (reachable.has(transition.from_stage_key) && !reachable.has(transition.to_stage_key)) {
          reachable.add(transition.to_stage_key);
          changed = true;
        }
      }
    }
    const unreachable = draft.stages.filter((stage) => !reachable.has(stage.key.trim()));
    if (unreachable.length > 0) {
      issues.push({
        code: "STAGE_UNREACHABLE",
        message: `Không thể đi từ giai đoạn bắt đầu đến: ${unreachable.map((stage) => stage.label || stage.key).join(", ")}.`,
      });
    }
  }

  if (duplicateValues(draft.tags.map((tag) => tag.key)).length > 0) {
    issues.push({ code: "TAG_KEY_DUPLICATE", message: "Mã nhãn không được trùng nhau." });
  }
  if (new Set(draft.tags.map((tag) => tag.position)).size !== draft.tags.length) {
    issues.push({ code: "TAG_POSITION_DUPLICATE", message: "Thứ tự nhãn không được trùng nhau." });
  }
  if (duplicateValues(attributeKeys).length > 0) {
    issues.push({ code: "ATTRIBUTE_KEY_DUPLICATE", message: "Mã thuộc tính hồ sơ không được trùng nhau." });
  }
  return issues;
};
