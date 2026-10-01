import { describe, expect, it } from "vitest";
import {
  buildAccommodationMarkdown,
  buildCompensationMarkdown,
  buildContactsMarkdown,
  buildFaqMarkdown,
  buildJobsMarkdown,
  buildMealsMarkdown,
  buildTransportationMarkdown,
  buildWorkSchedulesMarkdown,
  CATEGORY_MARKDOWN_SCHEMAS,
  planBriefKnowledge,
  rolesFromFaqEntries,
  serializeCategoryMarkdown,
  type CategoryPayload,
  type CategoryRecord,
} from "./project-knowledge-markdown";
import {
  EMPTY_PROJECT_BRIEF,
  parseProjectBrief,
  type ProjectBrief,
} from "./project-brief-ingest";
import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  PROJECT_KNOWLEDGE_CATEGORY_LABELS,
  type ProjectKnowledgeCategory,
} from "./project-knowledge-policy";
// The real recruiter briefs, copied verbatim — the same ingestion contract
// the parser's fixture tests hold. The v2 sheet is the one with the markdown
// pipe FAQ table ("Bảng tổng hợp câu hỏi thường gặp").
import amtranMd from "./fixtures/amtran-vsip-hai-phong.md?raw";
import fourPElectronicsMd from "./fixtures/four-p-electronics.md?raw";
import samsungSdsMd from "./fixtures/samsung-sds-kho.md?raw";
import samsungSdsV2Md from "./fixtures/samsung-sds-dinh-vu-v2.md?raw";
import allCategoriesText from "./fixtures/project-all-categories.txt?raw";

const ENTRY = {
  question: "Bên công ty đang tuyển công việc gì?",
  answer: "Vị trí tuyển: Công nhân sản xuất.",
};

const briefWith = (overrides: Partial<ProjectBrief> = {}): ProjectBrief => ({
  ...EMPTY_PROJECT_BRIEF,
  ...overrides,
});

describe("buildFaqMarkdown", () => {
  it("emits the shape the category template declares", () => {
    const markdown = buildFaqMarkdown([ENTRY]);
    expect(markdown).toContain('schema_version: "1.0"');
    expect(markdown).toContain("category: faq");
    expect(markdown).toContain("## faq");
    expect(markdown).toContain(
      "### record: ben-cong-ty-dang-tuyen-cong-viec-gi",
    );
    // The fields the brief does not state stay empty rather than guessed.
    expect(markdown).toContain("tags: []");
    expect(markdown).toContain("question_variants: []");
    expect(markdown).toContain("required_terms: []");
    expect(markdown).toContain("forbidden_terms: []");
    // One document, one trailing newline — the backend renderer's closing rule.
    expect(markdown.endsWith("\n")).toBe(true);
    expect(markdown.endsWith("\n\n")).toBe(false);
  });

  it("carries the question and answer verbatim", () => {
    const markdown = buildFaqMarkdown([ENTRY]);
    expect(markdown).toContain(
      'question: "Bên công ty đang tuyển công việc gì?"',
    );
    expect(markdown).toContain('answer: "Vị trí tuyển: Công nhân sản xuất."');
  });

  it("slugs the id and keeps it unique when two questions collapse together", () => {
    const markdown = buildFaqMarkdown([
      { question: "Lương bao nhiêu?", answer: "A" },
      { question: "Lương bao nhiêu ?", answer: "B" },
    ]);
    expect(markdown).toContain("### record: luong-bao-nhieu\n");
    expect(markdown).toContain("### record: luong-bao-nhieu-2\n");
  });

  it("quotes a value that carries a quote or a backslash", () => {
    const markdown = buildFaqMarkdown([
      { question: 'Giá "rẻ" thế nào?', answer: "C:\\path\\file" },
    ]);
    expect(markdown).toContain('question: "Giá \\"rẻ\\" thế nào?"');
    expect(markdown).toContain('answer: "C:\\\\path\\\\file"');
  });

  it("keeps a multi-line answer in one record with the newline escaped", () => {
    const markdown = buildFaqMarkdown([
      { question: "Q", answer: "dòng một\ndòng hai" },
    ]);
    expect(markdown).toContain('answer: "dòng một\\ndòng hai"');
    expect(markdown.match(/### record:/g)).toHaveLength(1);
  });

  it("writes an empty section, not a bare key, when there is no Q&A", () => {
    const markdown = buildFaqMarkdown([]);
    expect(markdown).toContain("## faq");
    expect(markdown).not.toContain("### record:");
  });
});

describe("buildJobsMarkdown", () => {
  it("emits the shape the jobs category template declares", () => {
    const markdown = buildJobsMarkdown(["Công nhân sản xuất"]);
    expect(markdown).toContain('schema_version: "1.0"');
    expect(markdown).toContain("category: jobs");
    expect(markdown).toContain("## jobs");
    expect(markdown).toContain("### record: cong-nhan-san-xuat");
    expect(markdown).toContain('title: "Công nhân sản xuất"');
  });

  it("omits headcount and employment-type fields", () => {
    const markdown = buildJobsMarkdown(["Công nhân sản xuất", "Kỹ thuật viên"]);
    expect(markdown).not.toMatch(/^\s*(?:vacancies|employment_type)\s*:/m);
  });

  it("carries the project location only when the brief stated one", () => {
    expect(buildJobsMarkdown(["Kho"], "Hải Phòng")).toContain(
      'location: "Hải Phòng"',
    );
    expect(buildJobsMarkdown(["Kho"])).toContain("location: null");
  });

  it("slugs the id and keeps it unique when two roles collapse together", () => {
    const markdown = buildJobsMarkdown(["Nhân viên kho", "Nhan vien kho"]);
    expect(markdown).toContain("### record: nhan-vien-kho\n");
    expect(markdown).toContain("### record: nhan-vien-kho-2\n");
  });

  it("writes an empty section when the brief names no role", () => {
    expect(buildJobsMarkdown([])).toContain("## jobs");
    expect(buildJobsMarkdown([])).not.toContain("### record:");
  });
});

describe("rolesFromFaqEntries", () => {
  // The Rorze.md pair, verbatim.
  const SCOPE_FAQ = {
    question: "Bên công ty đang tuyển công việc gì?",
    answer:
      "VFIC đang tuyển vị trí nhân viên lắp ráp và nhân viên vận hành máy CNC",
  };
  const AGE_FAQ = {
    question: "Rorze tuyển đến bao nhiêu tuổi?",
    answer: "Rorze tuyển từ đủ 18 tuổi đến 35 tuổi.",
  };

  it("takes both titles from the recruiting answer's position list", () => {
    expect(rolesFromFaqEntries([SCOPE_FAQ])).toEqual([
      "Nhân viên lắp ráp",
      "Nhân viên vận hành máy CNC",
    ]);
  });

  it("contributes zero roles when the answer states no position", () => {
    expect(rolesFromFaqEntries([AGE_FAQ])).toEqual([]);
  });

  it("ignores an answer whose text is a label line, not a position list", () => {
    expect(
      rolesFromFaqEntries([
        {
          question: "Bên công ty đang tuyển công việc gì?",
          answer: "Vị trí tuyển: Công nhân sản xuất.",
        },
      ]),
    ).toEqual([]);
  });
});

describe("planBriefKnowledge", () => {
  it("plans roles and FAQ in catalog order", () => {
    const plan = planBriefKnowledge(
      briefWith({ roles: ["Công nhân sản xuất"], faqEntries: [ENTRY] }),
    );
    expect(plan.writes.map((write) => write.key)).toEqual(["jobs", "faq"]);
    expect(plan.writes[0].filename).toBe("jobs.md");
    expect(plan.writes[1].filename).toBe("faq.md");
  });

  it("plans project compensation without requiring a jobs category", () => {
    const plan = planBriefKnowledge(
      briefWith({
        categories: { compensation: "Lương cơ bản: 6.200.000 VNĐ/tháng" },
      }),
    );
    expect(plan.writes.map((write) => write.key)).toEqual(["compensation"]);
    expect(plan.writes[0].content).toContain("base_salary_vnd: 6200000");
    expect(plan.writes[0].content).not.toMatch(/^\s*jobs?_ids\s*:/m);
  });

  it("plans nothing to write when the brief states neither a role nor a Q&A", () => {
    expect(planBriefKnowledge(briefWith()).writes).toHaveLength(0);
  });

  it("skips jobs when the brief names no role, so no empty category is written", () => {
    const plan = planBriefKnowledge(briefWith({ faqEntries: [ENTRY] }));
    expect(plan.writes.map((write) => write.key)).toEqual(["faq"]);
    expect(plan.needsHuman).toContain("jobs");
  });

  it("seeds the job scope from the FAQ's own recruiting answer (Rorze.md)", () => {
    // The Rorze brief is FAQ-only: no front matter, no jobs body. Its
    // recruiting Q&A is the only place the job scope is stated.
    const plan = planBriefKnowledge(
      briefWith({
        faqEntries: [
          {
            question: "Bên công ty đang tuyển công việc gì?",
            answer:
              "VFIC đang tuyển vị trí nhân viên lắp ráp và nhân viên vận hành máy CNC",
          },
          {
            question: "Rorze tuyển đến bao nhiêu tuổi?",
            answer: "Rorze tuyển từ đủ 18 tuổi đến 35 tuổi.",
          },
        ],
      }),
    );
    expect(plan.writes[0].key).toBe("jobs");
    expect(plan.writes[0].content).toContain('title: "Nhân viên lắp ráp"');
    expect(plan.writes[0].content).toContain(
      'title: "Nhân viên vận hành máy CNC"',
    );
    expect(plan.writes[0].content).not.toContain("35 tuổi");
    expect(plan.needsHuman).not.toContain("jobs");
  });

  it("names the ten categories that still need a human", () => {
    // A brief with no mapped category bodies has no content to seed them
    // from — content-driven means these stay named, not invented.
    const { needsHuman } = planBriefKnowledge(
      briefWith({ roles: ["Công nhân sản xuất"], faqEntries: [ENTRY] }),
    );
    expect(needsHuman).toHaveLength(10);
    expect(needsHuman).not.toContain("faq");
    expect(needsHuman).not.toContain("jobs");
    expect(needsHuman).toContain("contacts");
  });
});

// ── the cross-language schema contract ─────────────────────────────────────
//
// Mirrors the BACKEND contracts field for field: the per-category document
// models in backend/app/schemas/knowledge_categories.py and the renderer in
// backend/app/services/knowledge/category_markdown.py. A rename or a new
// required field there must fail HERE — an invalid document lands as a FAILED
// revision in production, which is worse than a category honestly left to a
// human.

const CATEGORY_SCHEMA: Record<
  ProjectKnowledgeCategory,
  { list: string; required: readonly string[]; fields: readonly string[] }
> = {
  jobs: {
    list: "jobs",
    required: ["id", "title"],
    fields: ["id", "title", "aliases", "location", "summary", "keywords"],
  },
  compensation: {
    list: "compensation",
    required: ["id"],
    fields: [
      "id",
      "base_salary_vnd",
      "estimated_income_min_vnd",
      "estimated_income_max_vnd",
      "allowances",
      "bonuses",
      "overtime_notes",
      "payment_notes",
    ],
  },
  requirements: {
    list: "requirements",
    required: ["id"],
    fields: [
      "id",
      "age_min",
      "age_max",
      "genders",
      "education",
      "experience",
      "health",
      "skills",
      "required_documents",
      "other",
    ],
  },
  work_schedules: {
    list: "work_schedules",
    required: ["id"],
    fields: [
      "id",
      "work_days",
      "shifts",
      "rotation",
      "breaks",
      "overtime",
      "notes",
    ],
  },
  benefits: {
    list: "benefits",
    required: ["id", "name"],
    fields: ["id", "name", "description", "eligibility"],
  },
  accommodation: {
    list: "accommodation",
    required: ["id", "available"],
    fields: [
      "id",
      "available",
      "type",
      "address",
      "monthly_cost_vnd",
      "deposit_vnd",
      "included_services",
      "eligibility",
      "notes",
    ],
  },
  meals: {
    list: "meals",
    required: ["id", "provided"],
    fields: [
      "id",
      "provided",
      "meals_per_shift",
      "allowance_vnd",
      "menu_notes",
      "eligibility",
      "notes",
    ],
  },
  transportation: {
    list: "transportation",
    required: ["id", "name", "direction"],
    fields: [
      "id",
      "name",
      "direction",
      "service_days",
      "shift",
      "fee_vnd",
      "stops",
      "notes",
    ],
  },
  insurance: {
    list: "insurance",
    required: ["id", "name"],
    fields: [
      "id",
      "name",
      "provider",
      "employee_contribution",
      "employer_contribution",
      "coverage",
      "starts_after",
      "eligibility",
      "notes",
    ],
  },
  application: {
    list: "application",
    required: ["id"],
    fields: [
      "id",
      "application_steps",
      "required_documents",
      "interview_location",
      "interview_process",
      "onboarding_steps",
      "processing_time",
      "fees",
      "notes",
    ],
  },
  contacts: {
    list: "contacts",
    required: ["id", "name"],
    fields: [
      "id",
      "name",
      "role",
      "phone",
      "zalo",
      "email",
      "address",
      "working_hours",
      "notes",
    ],
  },
  faq: {
    list: "faq",
    required: ["id", "question", "answer"],
    fields: [
      "id",
      "question",
      "answer",
      "tags",
      "question_variants",
      "required_terms",
      "forbidden_terms",
    ],
  },
};

/** `MoneyItem`, `ShiftItem` and `BusStopItem` — the nested rows the backend
 *  models type inside a category record. */
const MONEY_ITEM_FIELDS = ["name", "amount_vnd", "cadence", "conditions"];
const SHIFT_ITEM_FIELDS = [
  "name",
  "start_time",
  "end_time",
  "crosses_midnight",
];
const BUS_STOP_ITEM_FIELDS = ["order", "name", "time", "address"];

/** The backend's `StableId` pattern. */
const STABLE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

type MarkdownValue =
  | string
  | number
  | boolean
  | null
  | MarkdownValue[]
  | { [key: string]: MarkdownValue };

/** Undoes the five escapes, mirroring the backend's `_unescape`. */
const unescapeMarkdown = (body: string): string => {
  const decoded: Record<string, string> = {
    n: "\n",
    r: "\r",
    t: "\t",
    '"': '"',
    "\\": "\\",
  };
  let out = "";
  let escaped = false;
  for (const ch of body) {
    if (escaped) {
      out += decoded[ch] ?? ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    out += ch;
  }
  if (escaped) out += "\\";
  return out;
};

/** Decode one scalar token, mirroring the renderer's type-faithful encoding:
 *  numbers/booleans/null bare, every string double-quoted. */
const decodeScalar = (raw: string): MarkdownValue => {
  const value = raw.trim();
  if (value === "null") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
    return unescapeMarkdown(value.slice(1, -1));
  }
  if (/^-?\d+$/.test(value)) return Number(value);
  return value;
};

const splitCells = (line: string): string[] =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

const SEPARATOR_CELL = /^:?-{3,}:?$/;

/** A reader for the exact Category Markdown v1 the serializer emits: the
 *  front-matter envelope, the one section, `### record:` blocks, bare and
 *  quoted scalars, dash lists and pipe tables. It mirrors the backend parser
 *  (`category_markdown.parse_category_markdown`) so `parse(serialize(payload))`
 *  equals the payload by strict equality — the same property the backend's
 *  round-trip fixtures assert over `build_source_markdown`. */
const parseMarkdownDocument = (
  text: string,
  listField: string,
): Record<string, MarkdownValue> => {
  if (!text.startsWith("---\n")) throw new Error("front-matter missing");
  const close = text.indexOf("\n---", 4);
  if (close === -1) throw new Error("front-matter never closes");
  const meta: Record<string, string> = {};
  for (const line of text.slice(4, close).split("\n")) {
    if (!line.trim()) continue;
    const separator = line.indexOf(":");
    if (separator === -1) throw new Error(`bad front-matter line: ${line}`);
    meta[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }

  const body = text.slice(close + 4).replace(/^\n+/, "");
  const lines = body.split("\n");
  const heading = `## ${listField}`;
  if (lines[0] !== heading) {
    throw new Error(`expected '${heading}' first, got '${lines[0]}'`);
  }

  const records: Record<string, MarkdownValue>[] = [];
  let record: Record<string, MarkdownValue> | null = null;
  /** The bare `field:` awaiting its dash items or table rows, if any. */
  let openField: string | null = null;
  let tableColumns: string[] | null = null;

  for (const line of lines.slice(1)) {
    if (line.trim() === "") continue;
    if (line.startsWith("### record: ")) {
      record = { id: line.slice("### record: ".length) };
      records.push(record);
      openField = null;
      tableColumns = null;
      continue;
    }
    if (record === null) {
      throw new Error(`content outside a record: ${line}`);
    }
    if (line.startsWith("|")) {
      if (openField === null) {
        throw new Error(`table row without an open field: ${line}`);
      }
      const cells = splitCells(line);
      if (tableColumns === null) {
        tableColumns = cells;
        record[openField] = [];
        continue;
      }
      if (cells.every((cell) => SEPARATOR_CELL.test(cell))) continue;
      if (cells.length !== tableColumns.length) {
        throw new Error(`row width mismatch: ${line}`);
      }
      const row: Record<string, MarkdownValue> = {};
      tableColumns.forEach((column, index) => {
        if (cells[index] !== "") row[column] = decodeScalar(cells[index]);
      });
      (record[openField] as MarkdownValue[]).push(row);
      continue;
    }
    if (line.trim().startsWith("- ")) {
      if (openField === null) {
        throw new Error(`list item without an open field: ${line}`);
      }
      (record[openField] as MarkdownValue[]).push(
        decodeScalar(line.trim().slice(2)),
      );
      continue;
    }
    const field = /^([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)$/.exec(line);
    if (!field) throw new Error(`unrecognized line: ${line}`);
    const name = field[1];
    const raw = field[2].trim();
    if (raw === "[]") {
      record[name] = [];
      openField = null;
      tableColumns = null;
      continue;
    }
    if (raw !== "") {
      record[name] = decodeScalar(raw);
      openField = null;
      tableColumns = null;
      continue;
    }
    record[name] = [];
    openField = name;
    tableColumns = null;
  }

  return {
    schema_version: decodeScalar(meta.schema_version ?? ""),
    category: decodeScalar(meta.category ?? ""),
    [listField]: records,
  };
};

/** One write, held to the backend contract: the document envelope, the
 *  category's list field with at least one row, every row's required fields
 *  present, no field the model does not declare, unique stable ids. */
const expectContractShape = (write: {
  key: ProjectKnowledgeCategory;
  content: string;
}): void => {
  const schema = CATEGORY_SCHEMA[write.key];
  const document = parseMarkdownDocument(write.content, schema.list);
  expect(document.schema_version).toBe("1.0");
  expect(document.category).toBe(write.key);
  const rows = document[schema.list];
  expect(Array.isArray(rows)).toBe(true);
  const records = rows as Record<string, MarkdownValue>[];
  expect(records.length).toBeGreaterThan(0);

  const seenIds = new Set<string>();
  for (const record of records) {
    for (const field of schema.required) {
      // Presence, not truthiness: `available: false` and `provided: false`
      // are stated facts the contract requires.
      const value = record[field];
      expect(
        value !== undefined && value !== null && value !== "",
        `${write.key}.${String(field)} is required`,
      ).toBe(true);
    }
    for (const field of Object.keys(record)) {
      expect(
        schema.fields,
        `${write.key}.${field} must be a declared field`,
      ).toContain(field);
    }
    const id = record.id as string;
    expect(id).toMatch(STABLE_ID);
    expect(seenIds.has(id), `${write.key} duplicate id ${id}`).toBe(false);
    seenIds.add(id);

    for (const nested of [record.allowances, record.bonuses]) {
      if (!Array.isArray(nested)) continue;
      for (const item of nested as Record<string, MarkdownValue>[]) {
        for (const field of Object.keys(item)) {
          expect(MONEY_ITEM_FIELDS).toContain(field);
        }
        expect(item.name).toBeTruthy();
        expect(typeof item.amount_vnd).toBe("number");
        expect(item.cadence).toBeTruthy();
      }
    }
    if (Array.isArray(record.shifts)) {
      for (const item of record.shifts as Record<string, MarkdownValue>[]) {
        for (const field of Object.keys(item)) {
          expect(SHIFT_ITEM_FIELDS).toContain(field);
        }
        expect(item.start_time).toMatch(/^[0-2]\d:[0-5]\d$/);
        expect(item.end_time).toMatch(/^[0-2]\d:[0-5]\d$/);
      }
    }
    if (Array.isArray(record.stops)) {
      const orders = (record.stops as Record<string, MarkdownValue>[]).map(
        (item) => {
          for (const field of Object.keys(item)) {
            expect(BUS_STOP_ITEM_FIELDS).toContain(field);
          }
          expect(item.name).toBeTruthy();
          return item.order as number;
        },
      );
      expect(orders).toEqual([...orders].sort((a, b) => a - b));
    }
  }
};

describe("CATEGORY_MARKDOWN_SCHEMAS — the declaration-order mirror", () => {
  it("lists each category's fields in the pydantic declaration order", () => {
    for (const key of PROJECT_KNOWLEDGE_CATEGORIES) {
      expect(
        CATEGORY_MARKDOWN_SCHEMAS[key].fields.map((field) => field.name),
      ).toEqual([...CATEGORY_SCHEMA[key].fields]);
      expect(CATEGORY_MARKDOWN_SCHEMAS[key].listField).toBe(
        CATEGORY_SCHEMA[key].list,
      );
    }
  });

  it("types the four table fields with the backend's exact column order", () => {
    const fieldOf = (key: ProjectKnowledgeCategory, name: string) =>
      CATEGORY_MARKDOWN_SCHEMAS[key].fields.find(
        (field) => field.name === name,
      );
    expect(fieldOf("compensation", "allowances")).toEqual({
      name: "allowances",
      kind: "table",
      columns: MONEY_ITEM_FIELDS,
    });
    expect(fieldOf("compensation", "bonuses")).toEqual({
      name: "bonuses",
      kind: "table",
      columns: MONEY_ITEM_FIELDS,
    });
    expect(fieldOf("work_schedules", "shifts")).toEqual({
      name: "shifts",
      kind: "table",
      columns: SHIFT_ITEM_FIELDS,
    });
    expect(fieldOf("transportation", "stops")).toEqual({
      name: "stops",
      kind: "table",
      columns: BUS_STOP_ITEM_FIELDS,
    });
  });
});

// ── the backend renderer's own fixtures ────────────────────────────────────
//
// The twelve full records from
// backend/tests/test_category_markdown_contracts.py. The serializer must
// render each payload and re-parse to the identical object — the same strict
// round-trip the backend asserts over `build_source_markdown` and the one the
// data migration leans on. The controller runs the true cross-language check
// against the Python renderer; this is the TypeScript half of that net.

const FULL_RECORDS: Record<ProjectKnowledgeCategory, CategoryRecord> = {
  jobs: {
    id: "vi-cong-nhan",
    title: "Công nhân sản xuất",
    aliases: ["Công nhân kiểm tra màn hình", "CN đóng gói"],
    location: "KCN VSIP, Thủy Nguyên, Hải Phòng",
    summary: 'Dây chuyền điện tử, dấu nháy "và" xuống dòng\nthứ hai',
    keywords: ["điện tử", "kiểm tra"],
  },
  compensation: {
    id: "thu-nhap-chung",
    base_salary_vnd: 6300000,
    estimated_income_min_vnd: 9000000,
    estimated_income_max_vnd: 12000000,
    allowances: [
      {
        name: "Hỗ trợ đời sống",
        amount_vnd: 700000,
        cadence: "month",
        conditions: null,
      },
      {
        name: "Trợ cấp ca đêm",
        amount_vnd: 50000,
        cadence: "shift",
        conditions: "Mỗi đêm thực tế",
      },
    ],
    bonuses: [
      {
        name: "Thưởng năng suất",
        amount_vnd: 1000000,
        cadence: "month",
        conditions: null,
      },
    ],
    overtime_notes: null,
    payment_notes: "Chuyển khoản hàng tháng",
  },
  requirements: {
    id: "yeu-cau-chung",
    age_min: 18,
    age_max: 37,
    genders: ["any"],
    education: "Không yêu cầu bằng cấp",
    experience: "Được đào tạo từ đầu",
    health: ["Khám sức khỏe đạt"],
    skills: ["Cẩn thận"],
    required_documents: ["CCCD bản gốc"],
    other: ["Nhận người có hình xăm"],
  },
  work_schedules: {
    id: "lich-lam-chung",
    work_days: ["Thứ 2", "Thứ 7"],
    shifts: [
      {
        name: "Ca ngày",
        start_time: "07:30",
        end_time: "16:30",
        crosses_midnight: false,
      },
      {
        name: "Ca đêm",
        start_time: "20:00",
        end_time: "05:00",
        crosses_midnight: true,
      },
    ],
    rotation: "Luân phiên theo tuần",
    breaks: ["Nghỉ trưa 12:00 - 13:00"],
    overtime: "Tối thiểu 1 giờ mới tính",
    notes: null,
  },
  benefits: {
    id: "chuyen-can",
    name: "Phụ cấp chuyên cần",
    description: "Cộng vào lương tháng",
    eligibility: "Đủ công trong tháng",
  },
  accommodation: {
    id: "ky-tuc-xa",
    available: true,
    type: "Ký túc xá",
    address: "Trong khuôn viên KCN",
    monthly_cost_vnd: 300000,
    deposit_vnd: 300000,
    included_services: ["Điện", "Nước"],
    eligibility: "Người ở xa",
    notes: null,
  },
  meals: {
    id: "bua-an-ca",
    provided: true,
    meals_per_shift: 1,
    allowance_vnd: 0,
    menu_notes: "Cơm ba món",
    eligibility: "Mọi công nhân",
    notes: null,
  },
  transportation: {
    id: "tuyen-xe-1",
    name: "Tuyến số 1",
    direction: "round_trip",
    service_days: ["Thứ 2"],
    shift: "Ca ngày",
    fee_vnd: 0,
    stops: [
      { order: 1, name: "Cửa KCN", time: "06:45", address: null },
      { order: 2, name: "Bến xe", time: "07:00", address: "Số 1 Đường A" },
    ],
    notes: null,
  },
  insurance: {
    id: "bhxh",
    name: "BHXH bắt buộc",
    provider: "Bảo hiểm xã hội",
    employee_contribution: "10,5%",
    employer_contribution: "17,5%",
    coverage: ["Ốm đau", "Hưu trí"],
    starts_after: "Ngày chính thức",
    eligibility: "Người làm việc chính thức",
    notes: null,
  },
  application: {
    id: "ung-tuyen-nhan-viec",
    application_steps: ["Đăng ký", "Phỏng vấn", "Khám sức khỏe"],
    required_documents: ["CCCD photo công chứng"],
    interview_location: "Văn phòng tại KCN",
    interview_process: "Phỏng vấn trực tiếp",
    onboarding_steps: ["Nhận việc", "Đào tạo"],
    processing_time: "1-3 ngày",
    fees: "Miễn phí",
    notes: null,
  },
  contacts: {
    id: "lien-he-chung",
    name: "Ngọc Thảo",
    role: "Phụ trách hồ sơ",
    phone: "0963019380",
    zalo: "0963019380",
    email: "tuyendung@example.com",
    address: "Văn phòng tại KCN",
    working_hours: "08:00 - 17:00",
    notes: null,
  },
  faq: {
    id: "cau-hoi-1",
    question: "Công ty có tuyển vị trí nào không?",
    answer: "Đang tuyển Công nhân sản xuất.",
    tags: ["tuyen-dung"],
    question_variants: ["Bên mình tuyển gì?", "Có việc nào không?"],
    required_terms: ["tuyển"],
    forbidden_terms: [],
  },
};

const payloadOf = (key: ProjectKnowledgeCategory): CategoryPayload => ({
  schema_version: "1.0",
  category: key,
  records: [FULL_RECORDS[key]],
});

describe("serializeCategoryMarkdown — byte rules and the backend fixtures", () => {
  it("renders the empty document exactly as the backend renderer does", () => {
    expect(
      serializeCategoryMarkdown("jobs", {
        schema_version: "1.0",
        category: "jobs",
        records: [],
      }),
    ).toBe('---\nschema_version: "1.0"\ncategory: jobs\n---\n\n## jobs\n');
  });

  it("opens with the exact front-matter and section heading lines", () => {
    const head = serializeCategoryMarkdown("jobs", payloadOf("jobs"))
      .split("\n")
      .slice(0, 7);
    expect(head).toEqual([
      "---",
      'schema_version: "1.0"',
      "category: jobs",
      "---",
      "",
      "## jobs",
      "",
    ]);
  });

  it("closes the document with exactly one trailing newline", () => {
    const markdown = serializeCategoryMarkdown("jobs", payloadOf("jobs"));
    expect(markdown.endsWith("\n")).toBe(true);
    expect(markdown.endsWith("\n\n")).toBe(false);
  });

  for (const legacy of [
    { vacancies: null, employment_type: null },
    { vacancies: 100, employment_type: "temporary" },
  ]) {
    it(`omits retired role metadata even when legacy values are ${legacy.vacancies === null ? "null" : "populated"}`, () => {
      const payload = payloadOf("jobs");
      const markdown = serializeCategoryMarkdown("jobs", {
        ...payload,
        records: payload.records.map((record) => ({ ...record, ...legacy })),
      });
      expect(markdown).not.toMatch(/^\s*(?:vacancies|employment_type)\s*:/m);
      expect(parseMarkdownDocument(markdown, "jobs").jobs).toEqual(
        payload.records,
      );
    });
  }

  it("quotes every string and escapes only the five escapable characters", () => {
    const markdown = serializeCategoryMarkdown("jobs", payloadOf("jobs"));
    expect(markdown).toContain(
      'summary: "Dây chuyền điện tử, dấu nháy \\"và\\" xuống dòng\\nthứ hai"',
    );
  });

  it("renders a table field with the header, separator and encoded cells", () => {
    const markdown = serializeCategoryMarkdown(
      "work_schedules",
      payloadOf("work_schedules"),
    );
    expect(markdown).toContain(
      "| name | start_time | end_time | crosses_midnight |",
    );
    expect(markdown).toContain("| --- | --- | --- | --- |");
    expect(markdown).toContain('| "Ca ngày" | "07:30" | "16:30" | false |');
    expect(markdown).toContain('| "Ca đêm" | "20:00" | "05:00" | true |');
  });

  it("renders a dash list one `- ` line per entry, `[]` when empty", () => {
    const markdown = serializeCategoryMarkdown(
      "requirements",
      payloadOf("requirements"),
    );
    expect(markdown).toContain('genders:\n- "any"\n');
    expect(markdown).toContain('health:\n- "Khám sức khỏe đạt"\n');
    // A field the record omits renders `null`; an omitted list renders `[]`:
    expect(
      serializeCategoryMarkdown("accommodation", {
        schema_version: "1.0",
        category: "accommodation",
        records: [{ id: "cho-o", available: false }],
      }),
    ).toContain("deposit_vnd: null\nincluded_services: []");
  });

  for (const key of PROJECT_KNOWLEDGE_CATEGORIES) {
    it(`omits retired job references from the ${key} document`, () => {
      const payload = payloadOf(key);
      const markdown = serializeCategoryMarkdown(key, {
        ...payload,
        records: payload.records.map((record) => ({
          ...record,
          job_ids: ["retired-role"],
          jobs_ids: ["misspelled-retired-role"],
        })),
      });
      expect(markdown).not.toMatch(/^\s*jobs?_ids\s*:/m);
      expect(markdown).not.toContain("retired-role");
      expect(
        parseMarkdownDocument(markdown, CATEGORY_SCHEMA[key].list)[key],
      ).toEqual(payload.records);
    });

    it(`re-parses the ${key} fixture to the identical payload`, () => {
      const payload = payloadOf(key);
      const markdown = serializeCategoryMarkdown(key, payload);
      const document = parseMarkdownDocument(
        markdown,
        CATEGORY_SCHEMA[key].list,
      );
      expect(document.schema_version).toBe("1.0");
      expect(document.category).toBe(key);
      expect(document[key]).toEqual(payload.records);
    });
  }

  it("preserves ordinary prose mentioning the retired field names", () => {
    const answer =
      "Tệp cũ dùng job_ids, jobs_ids, vacancies và employment_type; dự án không cần chúng.";
    expect(
      buildFaqMarkdown([{ question: "Đổi tệp cũ thế nào?", answer }]),
    ).toContain(`answer: "${answer}"`);
  });
});

describe("planBriefKnowledge — the real recruiter briefs (golden)", () => {
  const cases = [
    ["Amtran", amtranMd],
    ["4P Electronics", fourPElectronicsMd],
    ["Samsung SDS kho", samsungSdsMd],
    ["Samsung SDS Đình Vũ v2 (FAQ table)", samsungSdsV2Md],
  ] as const;

  for (const [name, markdown] of cases) {
    describe(name, () => {
      const plan = planBriefKnowledge(parseProjectBrief(markdown));

      it("writes every category with sufficient source facts", () => {
        const expected =
          name === "4P Electronics" || name === "Amtran"
            ? PROJECT_KNOWLEDGE_CATEGORIES.filter(
                (key) => key !== "transportation",
              )
            : PROJECT_KNOWLEDGE_CATEGORIES;
        expect(plan.writes.map((write) => write.key)).toEqual([...expected]);
        // These sources explicitly have no shuttle. A route direction cannot be extracted
        // from a service that does not exist; keep the existing category.
        expect(plan.needsHuman).toEqual(
          name === "4P Electronics" || name === "Amtran"
            ? ["transportation"]
            : [],
        );
      });

      it("emits schema-shaped markdown the backend contract accepts", () => {
        for (const write of plan.writes) {
          expectContractShape(write);
          expect(write.content).not.toMatch(
            /^\s*(?:jobs?_ids|vacancies|employment_type)\s*:/m,
          );
        }
      });
    });
  }

  it("transcribes the SDS wage, income and payment facts into typed fields", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const compensation = plan.writes.find(
      (write) => write.key === "compensation",
    );
    expect(compensation?.content).toContain("base_salary_vnd: 300000");
    expect(compensation?.content).toContain(
      "estimated_income_min_vnd: 8000000",
    );
    expect(compensation?.content).toContain(
      "estimated_income_max_vnd: 9000000",
    );
    // The period the amount is quoted per stays in the prose, since
    // `base_salary_vnd` has no cadence field to carry it.
    expect(compensation?.content).toContain("ca 8 tiếng");
    expect(compensation?.content).toContain("theo tuần");
  });

  it("reads the SDS shifts as clock rows, night crossing midnight", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const write = plan.writes.find((write) => write.key === "work_schedules");
    const document = parseMarkdownDocument(
      write?.content ?? "",
      "work_schedules",
    );
    const shifts = (
      document.work_schedules as Record<string, MarkdownValue>[]
    )[0].shifts as Record<string, MarkdownValue>[];
    expect(shifts).toContainEqual(
      expect.objectContaining({
        start_time: "09:00",
        end_time: "18:00",
        crosses_midnight: false,
      }),
    );
    expect(shifts).toContainEqual(
      expect.objectContaining({
        start_time: "20:00",
        end_time: "04:00",
        crosses_midnight: true,
      }),
    );
  });

  it("lists the SDS shuttle stops in the order the brief gives them", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const write = plan.writes.find((write) => write.key === "transportation");
    const document = parseMarkdownDocument(
      write?.content ?? "",
      "transportation",
    );
    expect(document.category).toBe("transportation");
    const record = (
      document.transportation as Record<string, MarkdownValue>[]
    )[0];
    expect(record.direction).toBe("round_trip");
    expect(record.fee_vnd).toBe(0);
    const stops = record.stops as Record<string, MarkdownValue>[];
    expect(stops.map((stop) => stop.name)).toEqual(
      expect.arrayContaining([
        "Kiến An",
        "Aeon Mall Lê Chân",
        "Siêu thị Go! (Big C)",
      ]),
    );
  });

  it("carries the SDS meal, age and insurance facts in their typed slots", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const byKey = new Map(
      plan.writes.map((write) => [write.key, write.content]),
    );
    expect(byKey.get("meals")).toContain("provided: true");
    expect(byKey.get("meals")).toContain("meals_per_shift: 1");
    expect(byKey.get("meals")).toContain("allowance_vnd: 30000");
    expect(byKey.get("requirements")).toContain("age_min: 18");
    expect(byKey.get("requirements")).toContain("age_max: 65");
    expect(byKey.get("insurance")).toContain("starts_after:");
    expect(byKey.get("insurance")).toContain("tháng làm việc thứ 3");
    expect(byKey.get("insurance")).toContain("BHXH");
  });

  it("names each SDS contact person with their phone", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const contacts = plan.writes.find(
      (write) => write.key === "contacts",
    )?.content;
    for (const [name, phone] of [
      ["Mr. Trần Hữu Minh Thái", "0394765767"],
      ["Mr. Vũ Công Toàn", "0901500098"],
      ["Ms. Minh Anh", "0372294135"],
    ] as const) {
      expect(contacts).toContain(name);
      expect(contacts).toContain(`phone: "${phone}"`);
    }
  });

  it("keeps the Amtran no-dorm and no-shuttle facts as stated", () => {
    const plan = planBriefKnowledge(parseProjectBrief(amtranMd));
    const byKey = new Map(
      plan.writes.map((write) => [write.key, write.content]),
    );
    expect(byKey.get("accommodation")).toContain("available: false");
    expect(byKey.get("accommodation")).toContain("chưa có ký túc xá");
    expect(byKey.has("transportation")).toBe(false);
    expect(plan.needsHuman).toContain("transportation");
    expect(parseProjectBrief(amtranMd).categories.transportation).toContain(
      "không có tuyến xe đưa đón",
    );
    expect(parseProjectBrief(amtranMd).categories.transportation).toContain(
      "500.000",
    );
    // The stated monthly allowance lands as its own row in the money table.
    const document = parseMarkdownDocument(
      byKey.get("compensation") ?? "",
      "compensation",
    );
    const record = (
      document.compensation as Record<string, MarkdownValue>[]
    )[0];
    const allowances = record.allowances as Record<string, MarkdownValue>[];
    expect(allowances).toContainEqual(
      expect.objectContaining({ name: "Hỗ trợ đời sống", amount_vnd: 700000 }),
    );
  });

  it("pairs the v2 pipe-table FAQ rows into question and answer", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsV2Md));
    const faq = plan.writes.find((write) => write.key === "faq")?.content ?? "";
    // The table's question column and answer column, kept together.
    expect(faq).toContain(
      'question: "Kho Samsung SDS tuyển đến bao nhiêu tuổi?"',
    );
    expect(faq).toContain(
      'answer: "Kho Samsung SDS tuyển từ đủ 18 tuổi đến 65 tuổi."',
    );
    expect(faq).toContain('question: "Lương cơ bản và phụ cấp là bao nhiêu?"');
    expect(faq).toContain("300.000 VNĐ");
    // Every emitted record carries a non-empty answer — the exact defect the
    // backend contract rejects (`FaqItem.answer` is `NonEmptyText`, 409 on
    // upload). The table's separator row never becomes a record either.
    expect(faq).not.toContain('answer: ""');
    expect(faq).not.toContain(":---");
  });
});

describe("content-driven builders — derivation and honesty", () => {
  it("retains every typed field when importing a full category Markdown bundle", () => {
    const documents = PROJECT_KNOWLEDGE_CATEGORIES.map((key) => ({
      key,
      filename: `${key}.md`,
      content: serializeCategoryMarkdown(key, {
        schema_version: "1.0",
        category: key,
        records: [FULL_RECORDS[key]],
      }),
    }));
    const bundled =
      "# Kiến thức dự án\n\n" +
      documents
        .map((write) => `<!-- ${write.key} -->\n${write.content}`)
        .join("\n");
    const plan = planBriefKnowledge(parseProjectBrief(bundled));
    expect(plan.writes).toEqual(documents);
    expect(plan.needsHuman).toEqual([]);
  });

  it("imports project export display headings without dropping record content", () => {
    const documents = PROJECT_KNOWLEDGE_CATEGORIES.map((key) => ({
      key,
      filename: `${key}.md`,
      content: serializeCategoryMarkdown(key, payloadOf(key)),
    }));
    const exported =
      "# Kiến thức dự án: Minh Hải\n\n" +
      documents
        .map(
          (write) =>
            `## ${PROJECT_KNOWLEDGE_CATEGORY_LABELS[write.key]}\n\n${write.content}`,
        )
        .join("\n");
    expect(planBriefKnowledge(parseProjectBrief(exported)).writes).toEqual(
      documents,
    );
  });

  it("rejects a repeated typed section instead of silently truncating it", () => {
    const first = serializeCategoryMarkdown("jobs", payloadOf("jobs"));
    const malformed =
      first + '\n## jobs\n\n### record: second\ntitle: "Kỹ thuật viên"\n';
    expect(() => planBriefKnowledge(parseProjectBrief(malformed))).toThrow(
      /không hợp lệ/,
    );
  });

  it("rejects duplicate or unknown declared categories without treating them as prose", () => {
    const document = serializeCategoryMarkdown("jobs", payloadOf("jobs"));
    expect(() =>
      planBriefKnowledge(parseProjectBrief(document + "\n" + document)),
    ).toThrow(/bị lặp/);
    expect(() =>
      planBriefKnowledge(
        parseProjectBrief(
          document.replace("category: jobs", "category: invalid"),
        ),
      ),
    ).toThrow(/không hợp lệ/);
  });

  it("keeps a genuine blank template as missing instead of publishing commented examples", () => {
    const template = `---\nschema_version: "1.0"\ncategory: jobs\n---\n\n## jobs\n\n<!--\n### record: example\ntitle: "[Tên vị trí?]"\n-->\n`;
    const plan = planBriefKnowledge(parseProjectBrief(template));
    expect(plan.writes).toEqual([]);
    expect(plan.needsHuman).toEqual(PROJECT_KNOWLEDGE_CATEGORIES);
    expect(() =>
      planBriefKnowledge(
        parseProjectBrief(
          template +
            "\n" +
            serializeCategoryMarkdown("jobs", payloadOf("jobs")),
        ),
      ),
    ).toThrow(/bị lặp/);
  });

  it("leaves absent categories untouched when a typed bundle supplies only FAQ", () => {
    const content = serializeCategoryMarkdown("faq", payloadOf("faq"));
    const plan = planBriefKnowledge(parseProjectBrief(content));
    expect(plan.writes).toEqual([{ key: "faq", filename: "faq.md", content }]);
    expect(plan.needsHuman).toEqual(
      PROJECT_KNOWLEDGE_CATEGORIES.filter((key) => key !== "faq"),
    );
  });

  it("does not fabricate a route when the source explicitly denies a shuttle", () => {
    expect(
      buildTransportationMarkdown(
        "Không có xe đưa đón; hỗ trợ đi lại 300.000 đồng/tháng.",
      ),
    ).toBeNull();
  });

  it("preserves unanswered inline questions for review without borrowing another answer", () => {
    const brief = parseProjectBrief(
      "## FAQ\nHỏi: Lương thế nào?\nHỏi: Có KTX không?\nTrả lời: Không có KTX.",
    );
    const plan = planBriefKnowledge(brief);
    expect(
      plan.writes.find((write) => write.key === "faq")?.content,
    ).not.toContain("Lương thế nào?");
    expect(plan.writes.find((write) => write.key === "faq")?.content).toContain(
      "Không có KTX.",
    );
    expect(plan.needsHuman).toContain("faq");
  });

  it("marks long category content for review instead of claiming complete extraction", () => {
    const brief = parseProjectBrief(
      "## Phúc lợi\n" + "Quyền lợi: " + "a".repeat(4000),
    );
    expect(planBriefKnowledge(brief).needsHuman).toContain("benefits");
  });
  it("extracts all twelve categories from an ordinary text brief", () => {
    const plan = planBriefKnowledge(parseProjectBrief(allCategoriesText));
    expect(plan.writes.map((write) => write.key)).toEqual([
      ...PROJECT_KNOWLEDGE_CATEGORIES,
    ]);
    expect(plan.needsHuman).toEqual([]);
    for (const write of plan.writes) expectContractShape(write);
    const byKey = new Map(
      plan.writes.map((write) => [write.key, write.content]),
    );
    expect(byKey.get("compensation")).toContain(
      "estimated_income_min_vnd: 8500000",
    );
    expect(byKey.get("compensation")).toContain(
      "estimated_income_max_vnd: 10500000",
    );
    expect(byKey.get("requirements")).toContain('genders:\n- "any"');
    expect(byKey.get("requirements")).toContain(
      'education: "Học vấn: Tốt nghiệp THCS"',
    );
    expect(byKey.get("accommodation")).toContain("available: true");
    expect(byKey.get("meals")).toContain("meals_per_shift: 1");
    expect(byKey.get("contacts")).toContain('working_hours: "08:00 – 17:00"');
    expect(byKey.get("transportation")).toContain('"06:20"');
    expect(byKey.get("transportation")).toContain('"07:10"');
  });

  it("leaves contradictory housing and meal availability for review", () => {
    expect(buildAccommodationMarkdown("Có KTX.\nKhông có KTX.")).toBeNull();
    expect(
      buildMealsMarkdown("Cung cấp bữa ăn ca.\nKhông cung cấp bữa ăn ca."),
    ).toBeNull();
  });

  it("does not turn qualified meal exclusions into blanket no-meal claims", () => {
    expect(
      buildMealsMarkdown("Không phục vụ bữa sáng, cung cấp cơm ca trưa."),
    ).toBeNull();
    expect(buildMealsMarkdown("Công ty không có bữa ăn miễn phí.")).toBeNull();
  });

  it("preserves jobs prose beyond the role names", () => {
    const brief = parseProjectBrief(
      "Tên dự án: Minh Hải\nVị trí tuyển dụng: Công nhân\n## Mô tả công việc\nKiểm tra linh kiện dưới kính lúp; làm việc trong phòng sạch.",
    );
    const jobs = planBriefKnowledge(brief).writes.find(
      (write) => write.key === "jobs",
    )?.content;
    expect(jobs).toContain("Kiểm tra linh kiện dưới kính lúp");
    expect(jobs).toContain("phòng sạch");
  });
  it("never invents a base wage from a range", () => {
    const markdown = buildCompensationMarkdown(
      "Mức lương cơ bản: Từ 6.200.000 đến 6.300.000 VNĐ / tháng.",
    );
    expect(markdown).toContain("base_salary_vnd: null");
    expect(markdown).not.toMatch(/base_salary_vnd: \d/);
    // The range keeps its meaning in the payment notes, as written.
    expect(markdown).toContain("6.200.000");
    expect(markdown).toContain("6.300.000");
  });

  it("leaves an accommodation body with no dorm verdict for a human", () => {
    // `available` is REQUIRED and is a fact; nothing in this body states one,
    // so the category goes to `needsHuman` instead of guessing a flag.
    expect(
      buildAccommodationMarkdown(
        "Người lao động tự túc tìm phòng trọ quanh KCN.",
      ),
    ).toBeNull();
  });

  it("records provided: false when the brief says meals are not served", () => {
    const markdown = buildMealsMarkdown("Công ty không phục vụ bữa ăn ca.");
    expect(markdown).toContain("provided: false");
  });

  it("writes one contact row per person the brief names", () => {
    const markdown = buildContactsMarkdown(
      [
        "Cán bộ phụ trách đón tiếp:",
        "Họ và tên: Ngọc Thảo",
        "Số điện thoại / Zalo: 0963019380",
        "Họ và tên: Minh Anh",
        "Số điện thoại / Zalo: 0372294135",
      ].join("\n"),
    );
    expect(markdown).toContain('name: "Ngọc Thảo"');
    expect(markdown).toContain('name: "Minh Anh"');
    expect(markdown).toContain('phone: "0963019380"');
    expect(markdown).toContain('phone: "0372294135"');
    expect(markdown).toContain('role: "Cán bộ phụ trách đón tiếp"');
  });

  it("reads crosses_midnight off the clock, not off a label", () => {
    const markdown = buildWorkSchedulesMarkdown(
      "Ca Đêm: Từ 20:00 đến 04:00 sáng hôm sau.",
    );
    if (markdown === null) throw new Error("the night shift line must parse");
    const document = parseMarkdownDocument(markdown, "work_schedules");
    const shifts = (
      document.work_schedules as Record<string, MarkdownValue>[]
    )[0].shifts as Record<string, MarkdownValue>[];
    expect(shifts).toEqual([
      {
        name: "Ca Đêm",
        start_time: "20:00",
        end_time: "04:00",
        crosses_midnight: true,
      },
    ]);
  });

  it("never emits a FAQ record whose question or answer is empty", () => {
    // `FaqItem.question`/`answer` are `NonEmptyText` in the backend contract;
    // a question without an answer is not knowledge and must not reach the
    // API. The builder is structurally incapable of emitting one.
    const empty = buildFaqMarkdown([
      { question: "Thiếu câu trả lời?", answer: "" },
    ]);
    expect(empty).toContain("## faq");
    expect(empty).not.toContain("### record:");
    const markdown = buildFaqMarkdown([
      { question: "Đủ mặt?", answer: "Đủ." },
      { question: "Thiếu câu trả lời?", answer: "   " },
    ]);
    expect(markdown).toContain('question: "Đủ mặt?"');
    expect(markdown).not.toContain("Thiếu câu trả lời");
  });

  it("names the FAQ bank in needsHuman when the brief leaves questions open", () => {
    const plan = planBriefKnowledge(
      briefWith({
        roles: ["Công nhân sản xuất"],
        faqEntries: [ENTRY, { question: "Chưa có câu trả lời?", answer: "" }],
      }),
    );
    // What the brief answers is still written ...
    expect(plan.writes.map((write) => write.key)).toContain("faq");
    // ... but the open questions reach a human instead of vanishing.
    expect(plan.needsHuman).toContain("faq");
  });
});
