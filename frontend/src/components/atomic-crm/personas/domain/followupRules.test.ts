import { describe, expect, it } from "vitest";

import {
  FOLLOWUP_SCORE_ORDER,
  normalizePersonaFollowupRules,
  parseFollowupCadenceHours,
} from "./followupRules";

describe("followupRules", () => {
  it("normalizes partial rule payloads onto the default cadence", () => {
    const rules = normalizePersonaFollowupRules({
      hot: { enabled: false, cadence_hours: [4], eligible_stages: ["NEW"] },
    });

    expect(rules.hot).toEqual({
      enabled: false,
      cadence_hours: [4],
      eligible_stages: ["NEW"],
    });
    expect(rules.warm.cadence_hours).toEqual([22, 46]);
  });

  it("parses comma and whitespace separated cadence hours", () => {
    expect(parseFollowupCadenceHours("4, 8 12 invalid 0")).toEqual([4, 8, 12]);
    expect(FOLLOWUP_SCORE_ORDER).toEqual(["hot", "warm", "not_interested"]);
  });
});
