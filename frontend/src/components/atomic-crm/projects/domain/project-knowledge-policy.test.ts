import { describe, expect, it } from "vitest";

import type { ProductFeature } from "../../types";
import {
  aggregateProjectFeatureReadiness,
  buildProjectCreation,
  isProductFeatureReady,
  mergeUniqueTerms,
  normalizeProjectFaq,
  orderProductFeatureSlots,
  parseCommaList,
  projectActivationConflictVi,
  projectReadinessLabel,
} from "./project-knowledge-policy";

const feature = (
  priority: number,
  overrides: Partial<ProductFeature> = {},
): ProductFeature => ({
  id: `feature-${priority}`,
  project_id: "project-1",
  feature_id: `catalog-${priority}`,
  feature_key: `key-${priority}`,
  name_vi: `Mục ${priority}`,
  category: "income",
  worker_question_vi: null,
  value_text: "Có dữ liệu",
  value_json: {},
  strength_score: 1,
  display_priority: priority,
  is_highlight: false,
  is_missing: false,
  needs_clarification: false,
  evidence_text: null,
  source_document_id: null,
  updated_at: "2026-07-23T00:00:00Z",
  ...overrides,
});

describe("project knowledge policy", () => {
  it("keeps comma-list trim/filter behavior without deduplicating", () => {
    expect(parseCommaList(" LG, LGD, LG ")).toEqual(["LG", "LGD", "LG"]);
  });

  it("always creates a RAG draft — the mode is the ingest pipeline, not a choice", () => {
    expect(buildProjectCreation({ aliases: "" })).toEqual({
      knowledge_mode: "RAG",
      aliases: [],
      is_active: false,
    });
  });

  it("never sends a discovery card — the API derives a RAG one from the categories", () => {
    // `ProjectCreate` raises "RAG discovery cards are derived from active
    // categories" for any non-null card, so sending one fails the whole
    // create. The brief's summary/location reach the assistant through the
    // category YAML instead.
    const payload = buildProjectCreation({ aliases: "LG, LGD" });
    expect(payload).not.toHaveProperty("discovery_card");
    expect(payload.aliases).toEqual(["LG", "LGD"]);
    expect(payload.is_active).toBe(false);
  });

  it("derives readiness from the authoritative mode-specific signal", () => {
    expect(
      projectReadinessLabel({
        knowledge_mode: "DIRECT_CONTEXT",
        knowledge_document_count: 1,
        feature_readiness: { ready: 0, total: 16 },
      }),
    ).toBe("Đã sẵn sàng");
    expect(
      projectReadinessLabel({
        knowledge_mode: "RAG",
        knowledge_document_count: 0,
        feature_readiness: { ready: 7, total: 16 },
      }),
    ).toBe("7/16");
    expect(
      aggregateProjectFeatureReadiness([
        {
          knowledge_mode: "DIRECT_CONTEXT",
          feature_readiness: { ready: 15, total: 16 },
        },
        {
          knowledge_mode: "RAG",
          feature_readiness: { ready: 7, total: 16 },
        },
      ]),
    ).toEqual({ ready: 7, total: 16 });
  });

  it("shows unknown readiness instead of implying a zero-sized catalog is measured", () => {
    expect(
      projectReadinessLabel({
        knowledge_mode: "RAG",
        knowledge_document_count: 0,
        feature_readiness: { ready: 0, total: 0 },
      }),
    ).toBe("Chưa đo");
  });

  it("orders and pads feature slots using the API catalog total", () => {
    const low = feature(2);
    const high = feature(9);
    expect(orderProductFeatureSlots([high, low], 3)).toEqual([low, high, null]);
    expect(isProductFeatureReady(feature(1))).toBe(true);
    expect(isProductFeatureReady(feature(1, { value_text: "  " }))).toBe(false);
    expect(isProductFeatureReady(feature(1, { is_missing: true }))).toBe(false);
    expect(
      isProductFeatureReady(feature(1, { needs_clarification: true })),
    ).toBe(false);
  });

  it("normalizes FAQs and preserves first spelling/order for term chips", () => {
    expect(
      normalizeProjectFaq({
        question: "  Ca làm? ",
        answer: "  Có hai ca. ",
        question_variants: [],
        required_terms: [],
        forbidden_terms: [],
      }),
    ).toMatchObject({ question: "Ca làm?", answer: "Có hai ca." });
    expect(
      normalizeProjectFaq({
        question: " ",
        answer: "Có",
        question_variants: [],
        required_terms: [],
        forbidden_terms: [],
      }),
    ).toBeNull();
    expect(mergeUniqueTerms(["Lương"], "lương, Phụ cấp, PHỤ CẤP")).toEqual([
      "Lương",
      "Phụ cấp",
    ]);
  });
});

describe("projectActivationConflictVi", () => {
  it("maps the frozen activation conflicts to Vietnamese", () => {
    expect(
      projectActivationConflictVi(
        "RAG Project needs an active Jobs category before activation",
      ),
    ).toBe(
      "Dự án cần danh mục Tuyển dụng (Jobs) có dữ liệu trước khi bật. Hãy nạp danh mục trước.",
    );
    expect(
      projectActivationConflictVi(
        "Single-page Project needs its page before activation",
      ),
    ).toBe("Dự án Một trang cần trang kiến thức trước khi bật.");
  });

  it("falls through for unknown messages", () => {
    expect(projectActivationConflictVi("Some other failure")).toBe(
      "Some other failure",
    );
  });
});
