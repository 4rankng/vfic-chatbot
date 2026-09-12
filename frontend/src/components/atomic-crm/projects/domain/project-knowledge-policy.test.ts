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

  it("requires a mode and direct-context discovery fields", () => {
    const input = {
      aliases: "",
      discovery: { summary: "", location: "", roles: "", highlights: "" },
    };
    expect(buildProjectCreation({ ...input, mode: "" })).toEqual({
      ok: false,
      reason: "mode_required",
    });
    expect(buildProjectCreation({ ...input, mode: "DIRECT_CONTEXT" })).toEqual({
      ok: false,
      reason: "discovery_required",
    });
  });

  it("builds the canonical inactive direct-context creation payload", () => {
    expect(
      buildProjectCreation({
        aliases: "LG, LGD",
        mode: "DIRECT_CONTEXT",
        discovery: {
          summary: " Nhà máy ",
          location: " Hải Phòng ",
          roles: "Công nhân, Kỹ thuật",
          highlights: "Xe đưa đón, Ký túc xá",
        },
      }),
    ).toEqual({
      ok: true,
      data: {
        aliases: ["LG", "LGD"],
        discovery_card: {
          summary: "Nhà máy",
          location: "Hải Phòng",
          roles: ["Công nhân", "Kỹ thuật"],
          eligibility: [],
          highlights: ["Xe đưa đón", "Ký túc xá"],
        },
        is_active: false,
        knowledge_mode: "DIRECT_CONTEXT",
      },
    });
  });

  it("keeps RAG creation inactive without a discovery card", () => {
    expect(
      buildProjectCreation({
        aliases: "",
        mode: "RAG",
        discovery: {
          summary: "",
          location: "",
          roles: "",
          highlights: "",
        },
      }),
    ).toEqual({
      ok: true,
      data: {
        aliases: [],
        discovery_card: undefined,
        is_active: false,
        knowledge_mode: "RAG",
      },
    });
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
