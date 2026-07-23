import { describe, expect, it } from "vitest";

import type { AdapterPersonaAssignment, Persona } from "../../types";
import {
  createInitialAssignmentFeedback,
  getPersonaAssignmentState,
  normalizePersonaAssignments,
} from "./assignmentState";

const persona: Persona = {
  id: "persona-1",
  knowledge_base_id: "kb-1",
  name: "Agent chính",
  slug: "agent-chinh",
  body_md: "",
  followup_rules: {
    hot: { enabled: true, cadence_hours: [4], eligible_stages: ["NEW"] },
    warm: { enabled: true, cadence_hours: [8], eligible_stages: ["NEW"] },
    not_interested: { enabled: false, cadence_hours: [], eligible_stages: ["SKIPPED"] },
  },
  is_active: false,
  created_at: "2026-07-23T00:00:00Z",
  updated_at: "2026-07-23T00:00:00Z",
};

describe("assignmentState", () => {
  it("creates feedback entries for every adapter", () => {
    expect(Object.keys(createInitialAssignmentFeedback())).toEqual([
      "zalo_bot",
      "zalo_oa",
      "facebook_messenger",
    ]);
  });

  it("fills missing assignments for every adapter provider", () => {
    const assignments = normalizePersonaAssignments([
      {
        provider: "zalo_bot",
        label: "Zalo Chatbot",
        persona_id: null,
        effective_persona_id: null,
        is_default: false,
      },
    ]);

    expect(assignments).toHaveLength(3);
    expect(assignments[1]?.provider).toBe("zalo_oa");
  });

  it("derives explicit and inherited assignment states", () => {
    const explicit: AdapterPersonaAssignment = {
      provider: "zalo_oa",
      label: "Zalo OA",
      persona_id: persona.id,
      effective_persona_id: persona.id,
      is_default: false,
    };
    const inherited: AdapterPersonaAssignment = {
      ...explicit,
      persona_id: null,
      is_default: true,
    };

    expect(getPersonaAssignmentState(explicit, persona).actionLabel).toBe(
      "Trả về mặc định",
    );
    expect(getPersonaAssignmentState(inherited, persona).actionDisabled).toBe(
      true,
    );
  });
});
