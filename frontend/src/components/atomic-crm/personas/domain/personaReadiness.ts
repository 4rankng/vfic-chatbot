export const PERSONA_SECTION_TOTAL = 7;

export const getPersonaReadinessPercent = (sectionCount: number) =>
  Math.round(
    (Math.max(0, Math.min(PERSONA_SECTION_TOTAL, sectionCount)) /
      PERSONA_SECTION_TOTAL) *
      100,
  );
