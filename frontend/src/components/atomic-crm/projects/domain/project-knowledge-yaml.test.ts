import { describe, expect, it } from "vitest";
import { buildFaqYaml, planBriefKnowledge } from "./project-knowledge-yaml";

const ENTRY = {
  question: "Bên công ty đang tuyển công việc gì?",
  answer: "Vị trí tuyển: Công nhân sản xuất.",
};

describe("buildFaqYaml", () => {
  it("emits the shape the category template declares", () => {
    const yaml = buildFaqYaml([ENTRY]);
    expect(yaml).toContain('schema_version: "1.0"');
    expect(yaml).toContain("category: faq");
    expect(yaml).toContain("faq:");
    // The fields the brief does not state stay empty rather than guessed.
    expect(yaml).toContain("tags: []");
    expect(yaml).toContain("question_variants: []");
    expect(yaml).toContain("required_terms: []");
    expect(yaml).toContain("forbidden_terms: []");
  });

  it("carries the question and answer verbatim", () => {
    const yaml = buildFaqYaml([ENTRY]);
    expect(yaml).toContain('question: "Bên công ty đang tuyển công việc gì?"');
    expect(yaml).toContain('answer: "Vị trí tuyển: Công nhân sản xuất."');
  });

  it("slugs the id and keeps it unique when two questions collapse together", () => {
    const yaml = buildFaqYaml([
      { question: "Lương bao nhiêu?", answer: "A" },
      { question: "Lương bao nhiêu ?", answer: "B" },
    ]);
    expect(yaml).toContain("id: luong-bao-nhieu\n");
    expect(yaml).toContain("id: luong-bao-nhieu-2\n");
  });

  it("quotes a value that carries a quote or a backslash", () => {
    const yaml = buildFaqYaml([
      { question: 'Giá "rẻ" thế nào?', answer: "C:\\path\\file" },
    ]);
    expect(yaml).toContain('question: "Giá \\"rẻ\\" thế nào?"');
    expect(yaml).toContain('answer: "C:\\\\path\\\\file"');
  });

  it("flattens a multi-line answer so the document stays one entry", () => {
    const yaml = buildFaqYaml([
      { question: "Q", answer: "dòng một\ndòng hai" },
    ]);
    expect(yaml).toContain('answer: "dòng một dòng hai"');
  });

  it("writes an empty list, not a bare key, when there is no Q&A", () => {
    expect(buildFaqYaml([])).toContain("faq: []");
  });
});

describe("planBriefKnowledge", () => {
  it("plans only the FAQ — the one category the brief states in full", () => {
    const plan = planBriefKnowledge([ENTRY]);
    expect(plan.writes).toHaveLength(1);
    expect(plan.writes[0].key).toBe("faq");
    expect(plan.writes[0].filename).toBe("faq.yaml");
  });

  it("plans nothing to write when the brief pairs no question with an answer", () => {
    expect(planBriefKnowledge([]).writes).toHaveLength(0);
  });

  it("names the eleven categories that still need a human", () => {
    const { needsHuman } = planBriefKnowledge([ENTRY]);
    expect(needsHuman).toHaveLength(11);
    expect(needsHuman).not.toContain("faq");
    expect(needsHuman).toContain("jobs");
    expect(needsHuman).toContain("contacts");
  });
});
