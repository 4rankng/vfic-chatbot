import type { TranslateFunction } from "ra-core";
import {
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
} from "../domain/personaMarkdown";
import { ADAPTER_PROVIDER_LABELS, type Persona } from "../../types";

export type PersonaDerivedStats = {
  adapterCount: number;
  adapterLabels: string[];
  contentLength: number;
  followupEnabledCount: number;
  sectionCount: number;
};

export const FOLLOWUP_KEYS = ["hot", "warm", "not_interested"] as const;

export const numberFormatter = new Intl.NumberFormat("vi-VN");

export const getEffectiveAdapterLabels = (persona: Persona) =>
  (persona.effective_adapter_providers ?? []).map(
    (provider) => ADAPTER_PROVIDER_LABELS[provider],
  );

export const getPersonaDerivedStats = (
  persona: Persona,
): PersonaDerivedStats => ({
  adapterCount: getEffectiveAdapterLabels(persona).length,
  adapterLabels: getEffectiveAdapterLabels(persona),
  contentLength: getPersonaAuthoredContentLength(persona.body_md),
  followupEnabledCount: FOLLOWUP_KEYS.filter(
    (key) => persona.followup_rules?.[key]?.enabled,
  ).length,
  sectionCount: getCompletedPersonaSectionCount(persona.body_md),
});

export const getScopeLabel = (
  persona: Persona,
  stats: PersonaDerivedStats,
  translate: TranslateFunction,
) => {
  if (stats.adapterCount > 0) {
    return `${stats.adapterCount} adapter`;
  }
  if (persona.is_active) {
    return translate("personas.status_default");
  }
  return translate("personas.status_fallback");
};
