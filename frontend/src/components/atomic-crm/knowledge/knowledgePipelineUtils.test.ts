import { describe, expect, it } from "vitest";

import type { KnowledgeSource } from "../types";

import {
  PIPELINE_STEPS,
  flaggedCount,
  isFailed,
  isPipelineActive,
  isPossiblyStuck,
  isProcessing,
  isPublished,
  isRunning,
  isWaitingForWorker,
  needsReview,
  pipelinePercent,
  pipelineStepIndex,
  sourceStage,
} from "./knowledgePipelineUtils";

// Characterization tests for the pipeline-stage helpers. These pin the
// CURRENT behaviour of the pure functions extracted from KnowledgeSourceList
// so the move (and every future edit) stays behaviour-preserving.

const makeSource = (
  overrides: Partial<KnowledgeSource> = {},
): KnowledgeSource =>
  ({
    id: "src-1",
    drive_file_id: null,
    file_name: "doc.pdf",
    source: "upload",
    version: null,
    status: "unknown",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  }) as KnowledgeSource;

const at = (minutesAgo: number) =>
  new Date(Date.now() - minutesAgo * 60_000).toISOString();

describe("sourceStage", () => {
  it("prefers stage, then status, then UNKNOWN", () => {
    expect(sourceStage(makeSource({ stage: "DIGESTING" }))).toBe("DIGESTING");
    expect(sourceStage(makeSource({ stage: undefined, status: "ready" }))).toBe(
      "ready",
    );
    expect(
      sourceStage(makeSource({ stage: undefined, status: "unknown" })),
    ).toBe("unknown");
  });
});

describe("isPublished / isFailed", () => {
  it("treats PUBLISHED and READY (any case) as published", () => {
    expect(isPublished(makeSource({ stage: "PUBLISHED" }))).toBe(true);
    expect(isPublished(makeSource({ stage: "published" }))).toBe(true);
    expect(isPublished(makeSource({ stage: "READY" }))).toBe(true);
    expect(isPublished(makeSource({ stage: "DIGESTING" }))).toBe(false);
  });

  it("treats FAILED and ERROR (any case) as failed", () => {
    expect(isFailed(makeSource({ stage: "FAILED" }))).toBe(true);
    expect(isFailed(makeSource({ stage: "error" }))).toBe(true);
    expect(isFailed(makeSource({ stage: "PUBLISHED" }))).toBe(false);
  });
});

describe("isPipelineActive / isRunning / isProcessing / isWaitingForWorker", () => {
  it("flags every in-flight stage as pipeline-active", () => {
    for (const stage of [
      "UPLOADED",
      "EXTRACTED",
      "DIGESTING",
      "EMBEDDING",
      "INDEXING",
      "PROCESSING",
    ]) {
      expect(isPipelineActive(makeSource({ stage }))).toBe(true);
    }
    expect(isPipelineActive(makeSource({ stage: "PUBLISHED" }))).toBe(false);
    expect(isPipelineActive(makeSource({ stage: "FAILED" }))).toBe(false);
  });

  it("isRunning covers the worker-busy stages", () => {
    expect(isRunning(makeSource({ stage: "DIGESTING" }))).toBe(true);
    expect(isRunning(makeSource({ stage: "PROCESSING" }))).toBe(true);
    expect(isRunning(makeSource({ stage: "UPLOADED" }))).toBe(false);
  });

  it("isProcessing = active && not failed", () => {
    expect(isProcessing(makeSource({ stage: "DIGESTING" }))).toBe(true);
    expect(isProcessing(makeSource({ stage: "PROCESSING" }))).toBe(true);
    expect(isProcessing(makeSource({ stage: "FAILED" }))).toBe(false);
    expect(isProcessing(makeSource({ stage: "PUBLISHED" }))).toBe(false);
  });

  it("isWaitingForWorker covers UPLOADED/EXTRACTED", () => {
    expect(isWaitingForWorker(makeSource({ stage: "UPLOADED" }))).toBe(true);
    expect(isWaitingForWorker(makeSource({ stage: "EXTRACTED" }))).toBe(true);
    expect(isWaitingForWorker(makeSource({ stage: "DIGESTING" }))).toBe(false);
  });
});

describe("pipelineStepIndex / pipelinePercent", () => {
  it("maps each stage to its timeline slot", () => {
    expect(pipelineStepIndex(makeSource({ stage: "UPLOADED" }))).toBe(0);
    expect(pipelineStepIndex(makeSource({ stage: "EXTRACTED" }))).toBe(1);
    expect(pipelineStepIndex(makeSource({ stage: "DIGESTING" }))).toBe(2);
    expect(pipelineStepIndex(makeSource({ stage: "EMBEDDING" }))).toBe(3);
    expect(pipelineStepIndex(makeSource({ stage: "INDEXING" }))).toBe(4);
    expect(pipelineStepIndex(makeSource({ stage: "PUBLISHED" }))).toBe(5);
    expect(pipelineStepIndex(makeSource({ stage: "READY" }))).toBe(
      PIPELINE_STEPS.length - 1,
    );
    // PROCESSING is collapsed onto the Digest slot.
    expect(pipelineStepIndex(makeSource({ stage: "PROCESSING" }))).toBe(2);
    // Unknown stages fall back to the first step.
    expect(pipelineStepIndex(makeSource({ stage: "WAT" }))).toBe(0);
  });

  it("clamps progress to a 12% floor, 100% when published/failed", () => {
    expect(pipelinePercent(makeSource({ stage: "PUBLISHED" }))).toBe(100);
    expect(pipelinePercent(makeSource({ stage: "FAILED" }))).toBe(100);
    expect(pipelinePercent(makeSource({ stage: "UPLOADED" }))).toBe(12); // floor
    expect(pipelinePercent(makeSource({ stage: "EXTRACTED" }))).toBe(20);
    expect(pipelinePercent(makeSource({ stage: "DIGESTING" }))).toBe(40);
    expect(pipelinePercent(makeSource({ stage: "INDEXING" }))).toBe(80);
  });
});

describe("flaggedCount / needsReview", () => {
  it("counts flagged digest units", () => {
    expect(flaggedCount(makeSource())).toBe(0);
    expect(
      flaggedCount(
        makeSource({ digest_meta: { flagged_unit_indexes: [0, 2, 4] } }),
      ),
    ).toBe(3);
  });

  it("needs a review when flagged or failed", () => {
    expect(needsReview(makeSource({ stage: "PUBLISHED" }))).toBe(false);
    expect(
      needsReview(
        makeSource({
          stage: "PUBLISHED",
          digest_meta: { flagged_unit_indexes: [0] },
        }),
      ),
    ).toBe(true);
    expect(needsReview(makeSource({ stage: "FAILED" }))).toBe(true);
  });
});

describe("isPossiblyStuck", () => {
  it("only flags waiting-for-worker sources stale by >=2 min", () => {
    expect(
      isPossiblyStuck(makeSource({ stage: "EXTRACTED", updated_at: at(5) })),
    ).toBe(true);
    expect(
      isPossiblyStuck(makeSource({ stage: "EXTRACTED", updated_at: at(0) })),
    ).toBe(false);
    // A published source is never "stuck" regardless of age.
    expect(
      isPossiblyStuck(makeSource({ stage: "PUBLISHED", updated_at: at(30) })),
    ).toBe(false);
  });
});
