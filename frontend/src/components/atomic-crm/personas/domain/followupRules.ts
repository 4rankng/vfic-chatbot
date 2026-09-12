import type { LeadScoreValue, PersonaFollowupRules } from "../../types";

export const defaultPersonaFollowupRules = (): PersonaFollowupRules => ({
  hot: {
    enabled: true,
    cadence_hours: [10, 22, 46],
    eligible_stages: ["NEW"],
  },
  warm: {
    enabled: true,
    cadence_hours: [22, 46],
    eligible_stages: ["NEW"],
  },
  not_interested: {
    enabled: true,
    cadence_hours: [46],
    eligible_stages: ["NEW"],
  },
});

export const normalizePersonaFollowupRules = (
  rules?: Partial<PersonaFollowupRules> | null,
): PersonaFollowupRules => {
  const defaults = defaultPersonaFollowupRules();
  return {
    hot: { ...defaults.hot, ...(rules?.hot ?? {}) },
    warm: { ...defaults.warm, ...(rules?.warm ?? {}) },
    not_interested: {
      ...defaults.not_interested,
      ...(rules?.not_interested ?? {}),
    },
  };
};

export const parseFollowupCadenceHours = (value: string): number[] =>
  value
    .split(/[,\s]+/)
    .map((part) => Number.parseInt(part.trim(), 10))
    .filter((hours) => Number.isFinite(hours) && hours > 0);

export const FOLLOWUP_SCORE_ORDER: LeadScoreValue[] = [
  "hot",
  "warm",
  "not_interested",
] as const;
