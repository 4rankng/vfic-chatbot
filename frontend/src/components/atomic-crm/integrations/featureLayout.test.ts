import { describe, expect, it } from "vitest";

/**
 * FE-22 chose to flatten this feature rather than certify it, so the invariant
 * to hold is "no layer directories here".
 *
 * `_FRONTEND_LAYERED_FEATURE_ROOTS` in
 * `backend/tests/test_architecture_boundaries.py` certifies `knowledge/`,
 * `leads/`, `personas/`, `projects/` and `reporting/` only. Nothing in that
 * matrix fires for `integrations`, so a `domain/`, `application/`,
 * `infrastructure/` or `presentation/` directory here would advertise layers
 * that no rule enforces — the defect the flatten removed. Re-creating one
 * also hands the next person four pre-existing outward imports to untangle
 * before the feature can join the matrix at all.
 *
 * That every moved module still works is covered by the console render tests
 * in this directory, not here.
 */
const modulesInThisFeature = import.meta.glob("./**/*.{ts,tsx}");

const CERTIFIED_LAYER_DIRECTORIES = [
  "./domain/",
  "./application/",
  "./infrastructure/",
  "./presentation/",
];

describe("integrations feature layout", () => {
  it("carries no layer directories the boundary matrix does not police", () => {
    const uncertifiedLayers = Object.keys(modulesInThisFeature).filter((path) =>
      CERTIFIED_LAYER_DIRECTORIES.some((dir) => path.startsWith(dir)),
    );

    expect(uncertifiedLayers).toEqual([]);
  });
});
