import { describe, expect, it } from "vitest";
import {
  buildFaqYaml,
  buildJobsYaml,
  planBriefKnowledge,
} from "./project-knowledge-yaml";
import { EMPTY_PROJECT_BRIEF, type ProjectBrief } from "./project-brief-ingest";

const ENTRY = {
  question: "Bên công ty đang tuyển công việc gì?",
  answer: "Vị trí tuyển: Công nhân sản xuất.",
};

const briefWith = (overrides: Partial<ProjectBrief> = {}): ProjectBrief => ({
  ...EMPTY_PROJECT_BRIEF,
  ...overrides,
});

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

describe("buildJobsYaml", () => {
  it("emits the shape the jobs category template declares", () => {
    const yaml = buildJobsYaml(["Công nhân sản xuất"]);
    expect(yaml).toContain('schema_version: "1.0"');
    expect(yaml).toContain("category: jobs");
    expect(yaml).toContain("jobs:");
    expect(yaml).toContain("  - id: cong-nhan-san-xuat");
    expect(yaml).toContain('title: "Công nhân sản xuất"');
  });

  it("never states a vacancy count — the recruiter does not manage headcount", () => {
    // The schema makes `vacancies` optional for exactly this reason: an unknown
    // count must stay unknown rather than become a confident wrong number in an
    // answer a candidate will read.
    const yaml = buildJobsYaml(["Công nhân sản xuất", "Kỹ thuật viên"]);
    expect(yaml).not.toContain("vacancies");
    expect(yaml).not.toContain("employment_type");
  });

  it("carries the project location only when the brief stated one", () => {
    expect(buildJobsYaml(["Kho"], "Hải Phòng")).toContain(
      'location: "Hải Phòng"',
    );
    expect(buildJobsYaml(["Kho"])).not.toContain("location");
  });

  it("slugs the id and keeps it unique when two roles collapse together", () => {
    const yaml = buildJobsYaml(["Nhân viên kho", "Nhan vien kho"]);
    expect(yaml).toContain("id: nhan-vien-kho\n");
    expect(yaml).toContain("id: nhan-vien-kho-2\n");
  });

  it("writes an empty list when the brief names no role", () => {
    expect(buildJobsYaml([])).toContain("jobs: []");
  });
});

describe("planBriefKnowledge", () => {
  it("plans jobs before faq so every later write can resolve its job ids", () => {
    const plan = planBriefKnowledge(
      briefWith({ roles: ["Công nhân sản xuất"], faqEntries: [ENTRY] }),
    );
    expect(plan.writes.map((write) => write.key)).toEqual(["jobs", "faq"]);
    expect(plan.writes[0].filename).toBe("jobs.yaml");
    expect(plan.writes[1].filename).toBe("faq.yaml");
  });

  it("plans nothing to write when the brief states neither a role nor a Q&A", () => {
    expect(planBriefKnowledge(briefWith()).writes).toHaveLength(0);
  });

  it("skips jobs when the brief names no role, so no empty category is written", () => {
    const plan = planBriefKnowledge(briefWith({ faqEntries: [ENTRY] }));
    expect(plan.writes.map((write) => write.key)).toEqual(["faq"]);
    expect(plan.needsHuman).toContain("jobs");
  });

  it("names the ten categories that still need a human", () => {
    const { needsHuman } = planBriefKnowledge(
      briefWith({ roles: ["Công nhân sản xuất"], faqEntries: [ENTRY] }),
    );
    expect(needsHuman).toHaveLength(10);
    expect(needsHuman).not.toContain("faq");
    expect(needsHuman).not.toContain("jobs");
    expect(needsHuman).toContain("contacts");
  });
});
