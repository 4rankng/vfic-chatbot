import { describe, expect, it } from "vitest";
import {
  buildAccommodationYaml,
  buildCompensationYaml,
  buildContactsYaml,
  buildFaqYaml,
  buildJobsYaml,
  buildMealsYaml,
  buildWorkSchedulesYaml,
  planBriefKnowledge,
} from "./project-knowledge-yaml";
import {
  EMPTY_PROJECT_BRIEF,
  parseProjectBrief,
  type ProjectBrief,
} from "./project-brief-ingest";
import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  type ProjectKnowledgeCategory,
} from "./project-knowledge-policy";
// The real recruiter briefs, copied verbatim — the same ingestion contract
// the parser's fixture tests hold. The v2 sheet is the one with the markdown
// pipe FAQ table ("Bảng tổng hợp câu hỏi thường gặp").
import amtranMd from "./fixtures/amtran-vsip-hai-phong.md?raw";
import fourPElectronicsMd from "./fixtures/four-p-electronics.md?raw";
import samsungSdsMd from "./fixtures/samsung-sds-kho.md?raw";
import samsungSdsV2Md from "./fixtures/samsung-sds-dinh-vu-v2.md?raw";

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
// Mirrors the BACKEND contracts field for field: `CATEGORY_DEFINITIONS` and
// the per-category document models in
// backend/app/services/knowledge/category_contracts.py and
// backend/app/schemas/knowledge_categories.py. A rename or a new required
// field there must fail HERE — an invalid document lands as a FAILED revision
// in production, which is worse than a category honestly left to a human.

const CATEGORY_SCHEMA: Record<
  ProjectKnowledgeCategory,
  { list: string; required: readonly string[]; fields: readonly string[] }
> = {
  jobs: {
    list: "jobs",
    required: ["id", "title"],
    fields: [
      "id",
      "title",
      "aliases",
      "location",
      "vacancies",
      "employment_type",
      "summary",
      "keywords",
    ],
  },
  compensation: {
    list: "compensation",
    required: ["id"],
    fields: [
      "id",
      "job_ids",
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
      "job_ids",
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
      "job_ids",
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
    fields: ["id", "job_ids", "name", "description", "eligibility"],
  },
  accommodation: {
    list: "accommodation",
    required: ["id", "available"],
    fields: [
      "id",
      "job_ids",
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
      "job_ids",
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
      "job_ids",
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
      "job_ids",
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
      "job_ids",
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
const SHIFT_ITEM_FIELDS = ["name", "start_time", "end_time", "crosses_midnight"];
const BUS_STOP_ITEM_FIELDS = ["order", "name", "time", "address"];

/** The backend's `StableId` pattern. */
const STABLE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

type YamlValue =
  | string
  | number
  | boolean
  | YamlValue[]
  | { [key: string]: YamlValue };

/** A reader for the exact YAML subset the builders emit: block sequences and
 *  mappings on two-space indents, `[]` empty lists, quoted scalars, integers
 *  and booleans. It doubles as a guard that no builder ever emits a shape
 *  outside that subset. */
const parseYamlDocument = (text: string): Record<string, YamlValue> => {
  type Row = Readonly<{ indent: number; content: string }>;
  const rows: Row[] = text
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => ({
      indent: line.length - line.trimStart().length,
      content: line.trim(),
    }));

  const scalar = (raw: string): YamlValue => {
    if (raw === "[]") return [];
    if (raw.startsWith('"')) {
      if (!raw.endsWith('"')) {
        throw new Error(`unterminated quoted scalar: ${raw}`);
      }
      return raw
        .slice(1, -1)
        .replace(/\\(\\|n|")/g, (_match, ch: string) =>
          ch === "n" ? "\n" : ch,
        );
    }
    if (raw === "true") return true;
    if (raw === "false") return false;
    if (/^-?\d+$/.test(raw)) return Number(raw);
    return raw;
  };

  const parseMapping = (
    start: number,
    indent: number,
  ): [Record<string, YamlValue>, number] => {
    const map: Record<string, YamlValue> = {};
    let pos = start;
    while (
      pos < rows.length &&
      rows[pos].indent === indent &&
      !rows[pos].content.startsWith("-")
    ) {
      const match = /^([^:]+):\s*(.*)$/.exec(rows[pos].content);
      if (!match) throw new Error(`not a mapping row: ${rows[pos].content}`);
      const rest = match[2];
      pos += 1;
      if (rest) map[match[1]] = scalar(rest);
      else {
        const [child, next] = parseNode(pos, indent + 2);
        map[match[1]] = child;
        pos = next;
      }
    }
    return [map, pos];
  };

  const parseNode = (start: number, indent: number): [YamlValue, number] => {
    if (rows[start]?.content.startsWith("-")) {
      const list: YamlValue[] = [];
      let pos = start;
      while (
        pos < rows.length &&
        rows[pos].indent === indent &&
        rows[pos].content.startsWith("-")
      ) {
        const inline = rows[pos].content.replace(/^-\s?/, "");
        pos += 1;
        if (inline.startsWith('"')) {
          list.push(scalar(inline));
          continue;
        }
        if (!inline) {
          const [child, next] = parseNode(pos, indent + 2);
          list.push(child);
          pos = next;
          continue;
        }
        // The item's first `key: value` sits on the dash row; its remaining
        // keys follow two spaces deeper.
        const first = /^([^:]+):\s*(.+)$/.exec(inline);
        if (!first) throw new Error(`not a sequence item mapping: ${inline}`);
        const item: Record<string, YamlValue> = {
          [first[1]]: scalar(first[2]),
        };
        const [rest, next] = parseMapping(pos, indent + 2);
        Object.assign(item, rest);
        list.push(item);
        pos = next;
      }
      return [list, pos];
    }
    return parseMapping(start, indent);
  };

  const [document] = parseNode(0, rows[0]?.indent ?? 0);
  return document as Record<string, YamlValue>;
};

/** One write, held to the backend contract: the document envelope, the
 *  category's list field with at least one row, every row's required fields
 *  present, no field the model does not declare, unique stable ids. */
const expectContractShape = (write: {
  key: ProjectKnowledgeCategory;
  content: string;
}): void => {
  const schema = CATEGORY_SCHEMA[write.key];
  const document = parseYamlDocument(write.content);
  expect(document.schema_version).toBe("1.0");
  expect(document.category).toBe(write.key);
  const rows = document[schema.list];
  expect(Array.isArray(rows)).toBe(true);
  const records = rows as Record<string, YamlValue>[];
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
      expect(schema.fields, `${write.key}.${field} must be a declared field`).toContain(
        field,
      );
    }
    const id = record.id as string;
    expect(id).toMatch(STABLE_ID);
    expect(seenIds.has(id), `${write.key} duplicate id ${id}`).toBe(false);
    seenIds.add(id);

    for (const nested of [record.allowances, record.bonuses]) {
      if (!Array.isArray(nested)) continue;
      for (const item of nested as Record<string, YamlValue>[]) {
        for (const field of Object.keys(item)) {
          expect(MONEY_ITEM_FIELDS).toContain(field);
        }
        expect(item.name).toBeTruthy();
        expect(typeof item.amount_vnd).toBe("number");
        expect(item.cadence).toBeTruthy();
      }
    }
    if (Array.isArray(record.shifts)) {
      for (const item of record.shifts as Record<string, YamlValue>[]) {
        for (const field of Object.keys(item)) {
          expect(SHIFT_ITEM_FIELDS).toContain(field);
        }
        expect(item.start_time).toMatch(/^[0-2]\d:[0-5]\d$/);
        expect(item.end_time).toMatch(/^[0-2]\d:[0-5]\d$/);
      }
    }
    if (Array.isArray(record.stops)) {
      const orders = (record.stops as Record<string, YamlValue>[]).map(
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

      it("writes all twelve categories — the sheet genuinely carries them", () => {
        expect(plan.writes.map((write) => write.key)).toEqual([
          ...PROJECT_KNOWLEDGE_CATEGORIES,
        ]);
        expect(plan.needsHuman).toEqual([]);
      });

      it("emits schema-shaped YAML the backend contract accepts", () => {
        for (const write of plan.writes) expectContractShape(write);
      });
    });
  }

  it("transcribes the SDS wage, income and payment facts into typed fields", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const compensation = plan.writes.find(
      (write) => write.key === "compensation",
    );
    expect(compensation?.content).toContain("base_salary_vnd: 300000");
    expect(compensation?.content).toContain("estimated_income_min_vnd: 8000000");
    expect(compensation?.content).toContain("estimated_income_max_vnd: 9000000");
    // The period the amount is quoted per stays in the prose, since
    // `base_salary_vnd` has no cadence field to carry it.
    expect(compensation?.content).toContain("ca 8 tiếng");
    expect(compensation?.content).toContain("theo tuần");
  });

  it("reads the SDS shifts as clock rows, night crossing midnight", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const schedules = plan.writes.find(
      (write) => write.key === "work_schedules",
    )?.content;
    expect(schedules).toContain('start_time: "09:00"');
    expect(schedules).toContain('end_time: "18:00"');
    expect(schedules).toContain('start_time: "20:00"');
    expect(schedules).toContain('end_time: "04:00"');
    expect(schedules).toContain("crosses_midnight: true");
    expect(schedules).toContain("crosses_midnight: false");
  });

  it("lists the SDS shuttle stops in the order the brief gives them", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const transportation = plan.writes.find(
      (write) => write.key === "transportation",
    )?.content;
    expect(transportation).toContain("direction: round_trip");
    expect(transportation).toContain("fee_vnd: 0");
    expect(transportation).toContain('name: "Kiến An"');
    expect(transportation).toContain('name: "Aeon Mall Lê Chân"');
    expect(transportation).toContain('name: "Siêu thị Go! (Big C)"');
  });

  it("carries the SDS meal, age and insurance facts in their typed slots", () => {
    const plan = planBriefKnowledge(parseProjectBrief(samsungSdsMd));
    const byKey = new Map(plan.writes.map((write) => [write.key, write.content]));
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
    const contacts = plan.writes.find((write) => write.key === "contacts")
      ?.content;
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
    const byKey = new Map(plan.writes.map((write) => [write.key, write.content]));
    expect(byKey.get("accommodation")).toContain("available: false");
    expect(byKey.get("accommodation")).toContain("chưa có ký túc xá");
    expect(byKey.get("transportation")).toContain("không có tuyến xe đưa đón");
    expect(byKey.get("transportation")).toContain("500.000");
    // The stated monthly allowances each land as their own money row.
    expect(byKey.get("compensation")).toContain('name: "Hỗ trợ đời sống"');
    expect(byKey.get("compensation")).toContain("amount_vnd: 700000");
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
    expect(faq).toContain(
      'question: "Lương cơ bản và phụ cấp là bao nhiêu?"',
    );
    expect(faq).toContain("300.000 VNĐ");
    // Every emitted record carries a non-empty answer — the exact defect the
    // backend contract rejects (`FaqItem.answer` is `NonEmptyText`, 409 on
    // upload). The table's separator row never becomes a record either.
    expect(faq).not.toContain('answer: ""');
    expect(faq).not.toContain(":---");
  });
});

describe("content-driven builders — derivation and honesty", () => {
  it("never invents a base wage from a range", () => {
    const yaml = buildCompensationYaml(
      "Mức lương cơ bản: Từ 6.200.000 đến 6.300.000 VNĐ / tháng.",
    );
    expect(yaml).not.toContain("base_salary_vnd");
    // The range keeps its meaning in the payment notes, as written.
    expect(yaml).toContain("6.200.000");
    expect(yaml).toContain("6.300.000");
  });

  it("leaves an accommodation body with no dorm verdict for a human", () => {
    // `available` is REQUIRED and is a fact; nothing in this body states one,
    // so the category goes to `needsHuman` instead of guessing a flag.
    expect(
      buildAccommodationYaml("Người lao động tự túc tìm phòng trọ quanh KCN."),
    ).toBeNull();
  });

  it("records provided: false when the brief says meals are not served", () => {
    const yaml = buildMealsYaml("Công ty không phục vụ bữa ăn ca.");
    expect(yaml).toContain("provided: false");
  });

  it("writes one contact row per person the brief names", () => {
    const yaml = buildContactsYaml(
      [
        "Cán bộ phụ trách đón tiếp:",
        "Họ và tên: Ngọc Thảo",
        "Số điện thoại / Zalo: 0963019380",
        "Họ và tên: Minh Anh",
        "Số điện thoại / Zalo: 0372294135",
      ].join("\n"),
    );
    expect(yaml).toContain('name: "Ngọc Thảo"');
    expect(yaml).toContain('name: "Minh Anh"');
    expect(yaml).toContain('phone: "0963019380"');
    expect(yaml).toContain('phone: "0372294135"');
    expect(yaml).toContain('role: "Cán bộ phụ trách đón tiếp"');
  });

  it("reads crosses_midnight off the clock, not off a label", () => {
    const yaml = buildWorkSchedulesYaml("Ca Đêm: Từ 20:00 đến 04:00 sáng hôm sau.");
    expect(yaml).toContain('start_time: "20:00"');
    expect(yaml).toContain('end_time: "04:00"');
    expect(yaml).toContain("crosses_midnight: true");
  });

  it("never emits a FAQ record whose question or answer is empty", () => {
    // `FaqItem.question`/`answer` are `NonEmptyText` in the backend contract;
    // a question without an answer is not knowledge and must not reach the
    // API. The builder is structurally incapable of emitting one.
    expect(
      buildFaqYaml([{ question: "Thiếu câu trả lời?", answer: "" }]),
    ).toContain("faq: []");
    const yaml = buildFaqYaml([
      { question: "Đủ mặt?", answer: "Đủ." },
      { question: "Thiếu câu trả lời?", answer: "   " },
    ]);
    expect(yaml).toContain('question: "Đủ mặt?"');
    expect(yaml).not.toContain("Thiếu câu trả lời");
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
