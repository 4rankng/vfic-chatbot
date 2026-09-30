import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  type ProjectKnowledgeCategory,
} from "./project-knowledge-policy";
import type {
  ProjectBrief,
  ProjectBriefFaqEntry,
} from "./project-brief-ingest";

/**
 * project-knowledge-markdown — the one place a parsed brief becomes the
 * Category Markdown v1 the knowledge API accepts.
 *
 * The RAG categories are NOT free text: `PUT /categories/{key}` accepts one
 * `.md` document per category, and each category has its own typed schema. The
 * BACKEND contracts are the source of truth — the renderer
 * `build_source_markdown` in
 * `backend/app/services/knowledge/category_markdown.py` and the document
 * models in `backend/app/schemas/knowledge_categories.py`. `serializeCategoryMarkdown`
 * reproduces the renderer byte for byte: `---` front-matter naming
 * `schema_version` and `category`, one `## <list_field>` section, a
 * `### record: <id>` block per record with every pydantic field in declaration
 * order (mirrored in `CATEGORY_MARKDOWN_SCHEMAS` below), scalars encoded
 * type-faithfully (numbers/booleans/null bare, every string double-quoted with
 * the five escapes), dash lists for scalar lists, markdown tables for the four
 * table fields, records separated by one blank line, one trailing newline.
 * The tests mirror the required field names as a cross-language contract, so a
 * drift there fails here first. This serializer replaces the YAML pipeline.
 *
 * The plan is content-driven, by the owner's ruling ("ingestion pipeline should
 * base on file content to fill in all categories"): every category the brief
 * carries material for is written. A fact the brief states is transcribed into
 * its typed slot (a wage amount into `base_salary_vnd`, a shift into
 * `shifts`); prose the schema has no slot for is carried in the record's
 * notes-style fields — file-derived content is never "fabrication". Only
 * inventing a value the file does not state is.
 *
 * A category therefore lands in `needsHuman` in exactly two cases: the brief
 * gives it NO material, or its schema's REQUIRED fields cannot be honestly
 * derived from what the brief does give (an `available` flag the brief never
 * states, a route `direction` with no route described). Emitting a document
 * that would fail `parse_category_markdown` is worse than `needsHuman` —
 * invalid source lands as a FAILED revision.
 */

/** Drop the C0 control characters a quoted scalar can neither carry raw nor
 *  escape (tab, newline and carriage return are escaped before this runs). */
const stripRawControl = (value: string): string => {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 && code !== 0x09) continue;
    out += ch;
  }
  return out;
};

/** Strip the combining marks NFD leaves behind (U+0300..U+036F). */
const stripMarks = (value: string): string => {
  let out = "";
  for (const ch of value.normalize("NFD")) {
    const code = ch.codePointAt(0) ?? 0;
    if (code >= 0x300 && code <= 0x36f) continue;
    out += ch;
  }
  return out;
};

/** A Category Markdown double-quoted scalar: escape the five escapable
 *  characters in the backend renderer's order (backslash, double quote, \n,
 *  \r, \t) and refuse everything else that would break the document. */
const markdownString = (value: string): string => {
  const escaped = stripRawControl(
    value
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t"),
  );
  return `"${escaped}"`;
};

/** The contract bounds every text field (`NonEmptyText` <= 5000, notes-style
 *  fields <= 3000, address-style <= 1000 ...). Clamping keeps a long brief
 *  from failing validation outright; the bound is the schema's, not ours. */
const clamp = (value: string, max: number): string =>
  value.length <= max ? value : value.slice(0, max);

/** A stable, ASCII, unique-enough id — same rule the project's own slugs use. */
const toEntryId = (value: string, index: number): string => {
  const base = stripMarks(value)
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/g, "");
  return base || `cau-hoi-${index + 1}`;
};

/** Slugs the value and keeps the id unique when two entries collapse together,
 *  rather than letting the API reject the whole submission. */
const claimId = (
  used: Map<string, number>,
  value: string,
  index: number,
): string => {
  const base = toEntryId(value, index);
  const seen = used.get(base) ?? 0;
  used.set(base, seen + 1);
  return seen === 0 ? base : `${base}-${seen + 1}`;
};

// ── text helpers (mirrors the brief parser's own folding idiom) ─────────────

/** Diacritic-free lowercase, so a pattern matches whether or not the brief
 *  carries marks ("Chỗ ở" = "cho o"). */
const fold = (value: string): string =>
  stripMarks(value).replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();

/** The category body the parser mapped, one fact per line. */
const bodyLines = (body: string): string[] =>
  body
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

/** `Label: value` on one line. A label must carry a letter — an isolated
 *  "09:00" is a time, not a label. */
const splitLabel = (line: string): { label: string; value: string } => {
  const match = /^([^:：]{1,80})[:：]\s*(.*)$/.exec(line);
  if (!match || !/[A-Za-zÀ-ỹ]/.test(match[1])) {
    return { label: "", value: line };
  }
  return { label: match[1].trim(), value: match[2].trim() };
};

/** The FAQ transcript header that repeats in every mapped body. It is the
 *  Q&A bank's own scaffolding — already carried verbatim by the `faq`
 *  category — not a fact about the category it leaked into. */
const isTranscriptMarker = (line: string): boolean =>
  /^câu hỏi thường gặp/i.test(line) ||
  /^faq\b/i.test(line) ||
  /^[-–—]{3,}$/.test(line);

/** Every "300.000 VNĐ" / "400.000d" / "8 triệu đồng" amount in a line, as
 *  integers. A multiplier ("triệu") applies to the bare number before it. */
const AMOUNT =
  /(\d{1,3}(?:\.\d{3})+|\d+)\s*(triệu|tr)?\s*(?:VNĐ|VND|đồng|đ)/giu;

const vndValues = (line: string): number[] => {
  const values: number[] = [];
  for (const match of line.matchAll(AMOUNT)) {
    const base = Number(match[1].replace(/\./g, ""));
    values.push(match[2] ? base * 1_000_000 : base);
  }
  return values;
};

/** The pay period a money fact is quoted per. None stated means none written:
 *  a `MoneyItem` without its cadence would be a rate without a period. */
const cadenceOf = (value: string): string | null => {
  const folded = fold(value);
  if (/\/\s*thang|moi thang|hang thang/.test(folded)) return "month";
  if (/\/\s*tuan/.test(folded)) return "week";
  if (/\/\s*dem|dem\b/.test(folded)) return "shift";
  if (/\/\s*ca\b|moi ca/.test(folded)) return "shift";
  if (/\/\s*ngay|moi ngay/.test(folded)) return "day";
  if (/\/\s*gio/.test(folded)) return "hour";
  if (/\/\s*nam/.test(folded)) return "year";
  return null;
};

/** The `HH:MM` an explicit "09:00" / "09h00" writes. */
const toClock = (hours: string, minutes: string): string =>
  `${hours.padStart(2, "0")}:${minutes}`;

const TIME_RANGE =
  /(\d{1,2})[:h](\d{2})\s*(?:–|—|-|đến|tới|~|to)\s*(?:lúc\s*)?(\d{1,2})[:h](\d{2})/giu;

/** Every start/end clock range in a line. */
const timeRanges = (line: string): Readonly<{ start: string; end: string }>[] =>
  [...line.matchAll(TIME_RANGE)].map((match) => ({
    start: toClock(match[1], match[2]),
    end: toClock(match[3], match[4]),
  }));

// ── the emit layer (byte-compatible with the backend renderer) ─────────────

/** One scalar slot. `undefined` means "not stated by the brief" and renders
 *  as `null` — the same spelling the backend's `model_dump` gives an unset
 *  optional field, and the same `null` its parser decodes back. */
export type CategoryScalar = string | number | boolean | null | undefined;

type CategoryValue =
  | CategoryScalar
  | readonly CategoryScalar[]
  | readonly CategoryRow[]
  | undefined;

/** One row of a table field (`MoneyItem`, `ShiftItem`, `BusStopItem`); a
 *  column the row omits renders as `null`, exactly like an unset pydantic
 *  field in `model_dump(mode="json")`. */
export type CategoryRow = Record<string, CategoryScalar>;

/** One category record. The serializer walks the category's schema, not the
 *  record, so a key outside the schema never reaches the document. */
export type CategoryRecord = {
  id: string;
  [field: string]: CategoryValue;
};

/** The envelope one category write carries, mirroring the backend document
 *  payload (`schema_version`, `category`, the list field's records). */
export type CategoryPayload = Readonly<{
  schema_version: "1.0";
  category: ProjectKnowledgeCategory;
  records: readonly CategoryRecord[];
}>;

type MarkdownField =
  | Readonly<{ name: string; kind: "scalar" }>
  | Readonly<{ name: string; kind: "list" }>
  | Readonly<{ name: string; kind: "table"; columns: readonly string[] }>;

/** The record schema of one category, mirroring the pydantic model in
 *  `backend/app/schemas/knowledge_categories.py` field for field, in
 *  declaration order — the order the backend renderer writes them in. */
export type CategoryMarkdownSchema = Readonly<{
  listField: string;
  fields: readonly MarkdownField[];
}>;

const scalarField = (name: string): MarkdownField => ({ name, kind: "scalar" });
const listField = (name: string): MarkdownField => ({ name, kind: "list" });
const tableField = (
  name: string,
  columns: readonly string[],
): MarkdownField => ({ name, kind: "table", columns });

const MONEY_COLUMNS = ["name", "amount_vnd", "cadence", "conditions"];
const SHIFT_COLUMNS = ["name", "start_time", "end_time", "crosses_midnight"];
const BUS_STOP_COLUMNS = ["order", "name", "time", "address"];

export const CATEGORY_MARKDOWN_SCHEMAS: Readonly<
  Record<ProjectKnowledgeCategory, CategoryMarkdownSchema>
> = {
  jobs: {
    listField: "jobs",
    fields: [
      scalarField("id"),
      scalarField("title"),
      listField("aliases"),
      scalarField("location"),
      scalarField("vacancies"),
      scalarField("employment_type"),
      scalarField("summary"),
      listField("keywords"),
    ],
  },
  compensation: {
    listField: "compensation",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("base_salary_vnd"),
      scalarField("estimated_income_min_vnd"),
      scalarField("estimated_income_max_vnd"),
      tableField("allowances", MONEY_COLUMNS),
      tableField("bonuses", MONEY_COLUMNS),
      scalarField("overtime_notes"),
      scalarField("payment_notes"),
    ],
  },
  requirements: {
    listField: "requirements",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("age_min"),
      scalarField("age_max"),
      listField("genders"),
      scalarField("education"),
      scalarField("experience"),
      listField("health"),
      listField("skills"),
      listField("required_documents"),
      listField("other"),
    ],
  },
  work_schedules: {
    listField: "work_schedules",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      listField("work_days"),
      tableField("shifts", SHIFT_COLUMNS),
      scalarField("rotation"),
      listField("breaks"),
      scalarField("overtime"),
      scalarField("notes"),
    ],
  },
  benefits: {
    listField: "benefits",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("name"),
      scalarField("description"),
      scalarField("eligibility"),
    ],
  },
  accommodation: {
    listField: "accommodation",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("available"),
      scalarField("type"),
      scalarField("address"),
      scalarField("monthly_cost_vnd"),
      scalarField("deposit_vnd"),
      listField("included_services"),
      scalarField("eligibility"),
      scalarField("notes"),
    ],
  },
  meals: {
    listField: "meals",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("provided"),
      scalarField("meals_per_shift"),
      scalarField("allowance_vnd"),
      scalarField("menu_notes"),
      scalarField("eligibility"),
      scalarField("notes"),
    ],
  },
  transportation: {
    listField: "transportation",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("name"),
      scalarField("direction"),
      listField("service_days"),
      scalarField("shift"),
      scalarField("fee_vnd"),
      tableField("stops", BUS_STOP_COLUMNS),
      scalarField("notes"),
    ],
  },
  insurance: {
    listField: "insurance",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      scalarField("name"),
      scalarField("provider"),
      scalarField("employee_contribution"),
      scalarField("employer_contribution"),
      listField("coverage"),
      scalarField("starts_after"),
      scalarField("eligibility"),
      scalarField("notes"),
    ],
  },
  application: {
    listField: "application",
    fields: [
      scalarField("id"),
      listField("job_ids"),
      listField("application_steps"),
      listField("required_documents"),
      scalarField("interview_location"),
      scalarField("interview_process"),
      listField("onboarding_steps"),
      scalarField("processing_time"),
      scalarField("fees"),
      scalarField("notes"),
    ],
  },
  contacts: {
    listField: "contacts",
    fields: [
      scalarField("id"),
      scalarField("name"),
      scalarField("role"),
      scalarField("phone"),
      scalarField("zalo"),
      scalarField("email"),
      scalarField("address"),
      scalarField("working_hours"),
      scalarField("notes"),
    ],
  },
  faq: {
    listField: "faq",
    fields: [
      scalarField("id"),
      scalarField("question"),
      scalarField("answer"),
      listField("tags"),
      listField("question_variants"),
      listField("required_terms"),
      listField("forbidden_terms"),
    ],
  },
};

/** The backend's `_encode_scalar`: type-faithful on purpose, so the emitted
 *  document re-parses to the payload that produced it. */
const encodeScalar = (value: CategoryScalar): string => {
  if (value === null || value === undefined) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return String(value);
  return markdownString(value);
};

/** A schema declares each list field's item shape; the record honours it, so
 *  reading the items through the declared kind is safe. */
const listOf = (value: CategoryValue): readonly CategoryScalar[] =>
  Array.isArray(value) ? (value as readonly CategoryScalar[]) : [];
const rowsOf = (value: CategoryValue): readonly CategoryRow[] =>
  Array.isArray(value) ? (value as readonly CategoryRow[]) : [];

/** Render one category payload to Category Markdown v1, byte-compatible with
 *  `build_source_markdown(payload)` in
 *  `backend/app/services/knowledge/category_markdown.py`: every schema field
 *  in declaration order, unstated optionals as `null` and unstated lists as
 *  `[]`, records separated by one blank line, exactly one trailing newline. */
export const serializeCategoryMarkdown = (
  categoryKey: ProjectKnowledgeCategory,
  payload: CategoryPayload,
): string => {
  const schema = CATEGORY_MARKDOWN_SCHEMAS[categoryKey];
  const lines = [
    "---",
    `schema_version: "${payload.schema_version}"`,
    `category: ${categoryKey}`,
    "---",
    "",
    `## ${schema.listField}`,
    "",
  ];
  for (const record of payload.records) {
    lines.push(`### record: ${record.id}`);
    for (const field of schema.fields) {
      if (field.name === "id") continue;
      const value = record[field.name];
      if (field.kind === "scalar") {
        // The schema declares this slot scalar; the record honours the
        // declaration, so the array kinds never reach a scalar field.
        lines.push(`${field.name}: ${encodeScalar(value as CategoryScalar)}`);
      } else if (field.kind === "list") {
        const items = listOf(value);
        if (items.length === 0) {
          lines.push(`${field.name}: []`);
          continue;
        }
        lines.push(`${field.name}:`);
        for (const item of items) lines.push(`- ${encodeScalar(item)}`);
      } else {
        const rows = rowsOf(value);
        if (rows.length === 0) {
          lines.push(`${field.name}: []`);
          continue;
        }
        lines.push(`${field.name}:`);
        lines.push(`| ${field.columns.join(" | ")} |`);
        lines.push(`| ${field.columns.map(() => "---").join(" | ")} |`);
        for (const row of rows) {
          lines.push(
            `| ${field.columns
              .map((column) => encodeScalar(row[column]))
              .join(" | ")} |`,
          );
        }
      }
    }
    lines.push("");
  }
  // The backend renderer strips every trailing blank line and closes the
  // document with exactly one newline.
  return `${lines.join("\n").replace(/\n+$/, "")}\n`;
};

// ── the two original builders ──────────────────────────────────────────────

/** The `faq` category document: every question the brief paired with an answer,
 *  with the fields the template declares and the brief does not supply left as
 *  empty lists rather than guessed at.
 *
 *  Structurally incapable of emitting an invalid record: `FaqItem.question`
 *  and `FaqItem.answer` are `NonEmptyText` in the backend contract, so a pair
 *  missing either side is dropped HERE — a question without an answer is not
 *  knowledge. The plan names the gap in `needsHuman` instead of shipping a
 *  document the API would reject. */
export const buildFaqMarkdown = (
  entries: readonly ProjectBriefFaqEntry[],
): string => {
  const usable = entries.filter(
    (entry) => entry.question.trim() && entry.answer.trim(),
  );
  const used = new Map<string, number>();
  return serializeCategoryMarkdown("faq", {
    schema_version: "1.0",
    category: "faq",
    records: usable.map((entry, index) => ({
      id: claimId(used, entry.question, index),
      question: clamp(entry.question, 5000),
      answer: clamp(entry.answer, 5000),
    })),
  });
};

/** The `jobs` category document: one row per role the brief's overview listed.
 *
 *  `vacancies` is intentionally left unset (it renders `null`). The recruiter
 *  does not manage headcount for these roles, and the schema makes the field
 *  optional precisely so an unknown count stays unknown instead of becoming a
 *  confident wrong number in an answer a candidate will read.
 *  `employment_type` likewise: the enum only accepts forms the sheet would
 *  have to state in exactly those terms. */
export const buildJobsMarkdown = (
  roles: readonly string[],
  location = "",
): string => {
  const cleaned = roles.map((role) => role.trim()).filter(Boolean);
  const used = new Map<string, number>();
  return serializeCategoryMarkdown("jobs", {
    schema_version: "1.0",
    category: "jobs",
    records: cleaned.map((role, index) => ({
      id: claimId(used, role, index),
      title: clamp(role, 5000),
      // The project address genuinely covers every role in it, so carrying it
      // across is transcription rather than invention.
      ...(location ? { location: clamp(location, 500) } : {}),
    })),
  });
};

// ── content-driven builders ────────────────────────────────────────────────
//
// Each builder takes the body the parser mapped to its category and returns
// the category document, or `null` when the body carries no material or the
// schema's required fields cannot be honestly derived from it. Structured
// facts land in their typed slots; every other line lands in the record's
// notes-style sink, so no file content is dropped on the way in.

type MoneyRow = Readonly<{
  name: string;
  amountVnd: number;
  cadence: string;
  conditions?: string;
}>;

const moneyRows = (
  lines: readonly string[],
  want: (foldedLabel: string) => boolean,
): { rows: MoneyRow[]; used: Set<number> } => {
  const rows: MoneyRow[] = [];
  const used = new Set<number>();
  lines.forEach((line, index) => {
    const { label, value } = splitLabel(line);
    if (!label || !want(fold(label))) return;
    let amounts = vndValues(value);
    let name = label;
    if (amounts.length !== 1) {
      // Some sheets write the amount INTO the label ("Phụ cấp 400.000 VNĐ /
      // tháng: Dành cho ..."). The row keeps the label's words minus the
      // number; a genuine range still has no single amount and stays prose.
      amounts = vndValues(line);
      if (amounts.length !== 1) return;
      name =
        label.replace(/\s*[\d.,]+\s*(?:VNĐ|VND|đồng|đ).*$/iu, "").trim() ||
        label;
    }
    const cadence = cadenceOf(line);
    if (!cadence) return;
    const parenthetical = /\(([^)]+)\)/.exec(value);
    const conditions = parenthetical
      ? clamp(parenthetical[1], 2000)
      : undefined;
    rows.push({
      name: clamp(name, 5000),
      amountVnd: amounts[0],
      cadence,
      conditions,
    });
    used.add(index);
  });
  return { rows, used };
};

const moneyItemRow = (row: MoneyRow): CategoryRow => ({
  name: row.name,
  amount_vnd: row.amountVnd,
  cadence: row.cadence,
  ...(row.conditions ? { conditions: row.conditions } : {}),
});

/** The `compensation` document: the wage facts the brief states, typed where
 *  the schema is typed (base wage, estimated income range, allowance/bonus
 *  rows with their cadence) and transcribed into the payment/overtime notes
 *  everywhere else. */
export const buildCompensationMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const used = new Set<number>();
  let baseSalary: number | null = null;
  let incomeMin: number | null = null;
  let incomeMax: number | null = null;

  lines.forEach((line) => {
    const folded = fold(line);
    if (/tong thu nhap/.test(folded)) {
      const amounts = vndValues(line);
      if (amounts.length >= 2) {
        incomeMin = Math.min(amounts[0], amounts[1]);
        incomeMax = Math.max(amounts[0], amounts[1]);
      }
      // The line keeps flowing into the payment notes: its surrounding prose
      // ("gồm tiền lương công nhật + phụ cấp vị trí") is part of the fact.
      return;
    }
    const { label } = splitLabel(line);
    if (
      baseSalary === null &&
      label &&
      /luong/.test(fold(label)) &&
      !/tong thu nhap|phu cap|tro cap|thuong/.test(fold(label)) &&
      vndValues(line).length === 1
    ) {
      // A single stated wage becomes the base; a range ("Từ 6.200.000 đến
      // 6.300.000") cannot. Either way the line also stays in the payment
      // notes, because `base_salary_vnd` carries no period and the prose
      // ("300.000 VNĐ / ca 8 tiếng") is where the period lives.
      baseSalary = vndValues(line)[0];
    }
  });

  const allowances = moneyRows(
    lines,
    (label) => /phu cap|tro cap|ho tro/.test(label) && !/thuong/.test(label),
  );
  const bonuses = moneyRows(lines, (label) => /thuong/.test(label));
  for (const index of allowances.used) used.add(index);
  for (const index of bonuses.used) used.add(index);

  const overtime: string[] = [];
  const payment: string[] = [];
  lines.forEach((line, index) => {
    if (used.has(index)) return;
    if (/tang ca|lam them/.test(fold(line))) overtime.push(line);
    else payment.push(line);
  });

  const record: CategoryRecord = { id: "luong-thu-nhap", job_ids: [] };
  if (baseSalary !== null) record.base_salary_vnd = baseSalary;
  if (incomeMin !== null && incomeMax !== null) {
    record.estimated_income_min_vnd = incomeMin;
    record.estimated_income_max_vnd = incomeMax;
  }
  if (allowances.rows.length > 0) {
    record.allowances = allowances.rows.map(moneyItemRow);
  }
  if (bonuses.rows.length > 0) {
    record.bonuses = bonuses.rows.map(moneyItemRow);
  }
  if (overtime.length > 0) {
    record.overtime_notes = clamp(overtime.join("\n"), 3000);
  }
  if (payment.length > 0) {
    record.payment_notes = clamp(payment.join("\n"), 3000);
  }

  return serializeCategoryMarkdown("compensation", {
    schema_version: "1.0",
    category: "compensation",
    records: [record],
  });
};

/** The `requirements` document: the stated age band, gender, education and
 *  experience in their typed slots, everything else (tattoo policy, papers to
 *  bring, personal qualities) as the list items the schema provides. */
export const buildRequirementsMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const ages: number[] = [];
  for (const line of lines) {
    for (const pair of line.matchAll(
      /\b(\d{2})\s*(?:tuổi)?\s*(?:đến|tới|-|–|~)\s*(\d{2})\s*tuổi\b/giu,
    )) {
      ages.push(Number(pair[1]), Number(pair[2]));
    }
    for (const single of line.matchAll(/\b(\d{2})\s*tuổi\b/giu)) {
      ages.push(Number(single[1]));
    }
  }
  const inBand = ages.filter((age) => age >= 15 && age <= 80);
  const ageMin = inBand.length > 0 ? Math.min(...inBand) : null;
  const ageMax = inBand.length > 0 ? Math.max(...inBand) : null;

  let genders: "female" | "male" | "any" | null = null;
  let education: string | null = null;
  let experience: string | null = null;
  const health: string[] = [];
  const skills: string[] = [];
  const documents: string[] = [];
  const other: string[] = [];

  for (const line of lines) {
    const folded = fold(line);
    if (!genders && /gioi tinh|tuyen (ca )?(nam|nu)/.test(folded)) {
      if (/nam (va|,) nu|ca nam|nu (va|,) nam/.test(folded)) genders = "any";
      else if (/\bnam\b/.test(folded)) genders = "male";
      else if (/\bnu\b/.test(folded)) genders = "female";
      continue;
    }
    if (!education && /hoc vanh|van hoa|bang cap/.test(folded)) {
      education = line;
      continue;
    }
    if (!experience && /kinh nghiem|tay nghe/.test(folded)) {
      experience = line;
      continue;
    }
    // An age line's words are already in `age_min`/`age_max`; it must not be
    // read as a health requirement just because it says "đủ sức khỏe".
    if (/\d{2}\s*tuổi/.test(line)) {
      other.push(line);
      continue;
    }
    if (
      /giay to|ho so|cccd|can cuoc|so yeu ly lich|photo cong chung|vneid|giay xac nhan|giay kham/.test(
        folded,
      )
    ) {
      documents.push(line);
      continue;
    }
    if (/suc khoe/.test(folded)) {
      health.push(line);
      continue;
    }
    if (/ky nang/.test(folded)) {
      skills.push(line);
      continue;
    }
    other.push(line);
  }

  const record: CategoryRecord = { id: "yeu-cau-ung-vien", job_ids: [] };
  if (ageMin !== null) record.age_min = ageMin;
  if (ageMax !== null) record.age_max = ageMax;
  if (genders) record.genders = [genders];
  if (education) record.education = clamp(education, 1000);
  if (experience) record.experience = clamp(experience, 1000);
  if (health.length > 0) {
    record.health = health.map((value) => clamp(value, 2000));
  }
  if (skills.length > 0) {
    record.skills = skills.map((value) => clamp(value, 2000));
  }
  if (documents.length > 0) {
    record.required_documents = documents.map((value) => clamp(value, 2000));
  }
  if (other.length > 0) {
    record.other = other.map((value) => clamp(value, 2000));
  }

  return serializeCategoryMarkdown("requirements", {
    schema_version: "1.0",
    category: "requirements",
    records: [record],
  });
};

/** The `work_schedules` document: every stated shift as `HH:MM` rows (with
 *  `crosses_midnight` read off the clock, not guessed), plus the breaks,
 *  rotation and overtime rules the brief wrote, in their own fields. */
export const buildWorkSchedulesMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const shifts = new Map<
    string,
    { name: string; start: string; end: string }
  >();
  const breaks: string[] = [];
  const rotation: string[] = [];
  const overtime: string[] = [];
  const workDays: string[] = [];
  const notes: string[] = [];
  let currentShift = "";

  for (const line of lines) {
    const folded = fold(line);
    const { label } = splitLabel(line);

    // "Ca Ngày:" alone names the shift the following lines describe.
    const bareShift = /^ca\s+(\S+?)\s*[:：]\s*$/.exec(line);
    if (bareShift) {
      currentShift = `Ca ${bareShift[1]}`;
      continue;
    }

    // "Ca ngày: 09:00 – 18:00", "Ca ngày (08:00 – 17:00 ...)" — the name and
    // the clock range written together, wherever in the line they sit.
    let claimed = false;
    for (const match of line.matchAll(
      /ca\s+(ngày|đêm|sáng|chiều|tối|hc|hành chính)\b[^0-9]{0,30}?(\d{1,2})[:h](\d{2})\s*(?:–|—|-|đến|tới|~|to)\s*(\d{1,2})[:h](\d{2})/giu,
    )) {
      const name = `Ca ${match[1]}`;
      const key = `${fold(name)}-${match[2]}:${match[3]}`;
      if (!shifts.has(key)) {
        shifts.set(key, {
          name,
          start: toClock(match[2], match[3]),
          end: toClock(match[4], match[5]),
        });
      }
      currentShift = name;
      claimed = true;
    }

    const ranges = timeRanges(line);

    // "Giờ làm việc chính khóa: 08:00 – 17:00 (Nghỉ trưa: 12:00 – 13:00)"
    // under a "Ca ..." header: the range is the shift, the parenthetical is
    // the break inside it.
    if (
      ranges.length > 0 &&
      label &&
      /gio lam viec|chinh khuc|thoi gian lam viec/.test(fold(label))
    ) {
      const name = currentShift || "Ca làm việc";
      const key = `${fold(name)}-${ranges[0].start}`;
      if (!shifts.has(key)) {
        shifts.set(key, { name, start: ranges[0].start, end: ranges[0].end });
      }
      for (const paren of line.matchAll(/\(([^)]*)\)/g)) {
        // Folded, because "Nghỉ" carries marks the pattern cannot.
        if (/nghi/.test(fold(paren[1])) && timeRanges(paren[1]).length > 0) {
          breaks.push(clamp(paren[1].trim(), 2000));
        }
      }
      continue;
    }
    if (claimed) continue;

    const hasParenBreak = [...line.matchAll(/\(([^)]*)\)/g)].some(
      (paren) => /nghi/.test(fold(paren[1])) && timeRanges(paren[1]).length > 0,
    );
    if (
      (label && /nghi/.test(fold(label)) && ranges.length > 0) ||
      hasParenBreak
    ) {
      breaks.push(line);
      continue;
    }
    if (/tang ca|lam them/.test(folded)) {
      overtime.push(clamp(line, 3000));
      continue;
    }
    if (/luan phien|xoay ca|xoay vong|doi ca|\d+\s*tuan/.test(folded)) {
      rotation.push(line);
      continue;
    }
    if (/(thứ\s*[2-7]|chủ nhật)/i.test(line)) {
      workDays.push(line);
      continue;
    }
    notes.push(line);
  }

  const record: CategoryRecord = { id: "lich-lam-viec", job_ids: [] };
  if (workDays.length > 0) {
    record.work_days = workDays.map((day) => clamp(day, 2000));
  }
  if (shifts.size > 0) {
    record.shifts = [...shifts.values()].map((shift) => ({
      name: clamp(shift.name, 5000),
      start_time: shift.start,
      end_time: shift.end,
      crosses_midnight: shift.end <= shift.start,
    }));
  }
  if (rotation.length > 0) {
    record.rotation = clamp(rotation.join("\n"), 2000);
  }
  if (breaks.length > 0) {
    record.breaks = breaks.map((item) => clamp(item, 2000));
  }
  if (overtime.length > 0) {
    record.overtime = clamp(overtime.join("\n"), 3000);
  }
  if (notes.length > 0) {
    record.notes = clamp(notes.join("\n"), 3000);
  }

  return serializeCategoryMarkdown("work_schedules", {
    schema_version: "1.0",
    category: "work_schedules",
    records: [record],
  });
};

/** The `benefits` document: one row per benefit the brief states. A
 *  `Label: mô tả` line names the benefit after its label; a bare sentence is
 *  its own benefit as written. */
export const buildBenefitsMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const used = new Map<string, number>();
  const records = lines.map((line, index) => {
    const { label, value } = splitLabel(line);
    const name = label && value ? label : line;
    const description = label && value ? value : "";
    const record: CategoryRecord = {
      id: claimId(used, name, index),
      job_ids: [],
      name: clamp(name, 5000),
    };
    if (description) record.description = clamp(description, 3000);
    return record;
  });

  return serializeCategoryMarkdown("benefits", {
    schema_version: "1.0",
    category: "benefits",
    records,
  });
};

/** The `accommodation` document. `available` is REQUIRED by the contract and
 *  is a fact: the brief either states a dormitory exists or states it does
 *  not. A body that never answers that question cannot honestly fill the
 *  slot, so it stays in `needsHuman` instead of guessing a flag. */
export const buildAccommodationMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const foldedAll = fold(lines.join("\n"));
  let available: boolean | null = null;
  if (
    /chua co ky tuc xa|khong (?:co|ho tro|cap) ?ky tuc xa|khong co ktx|chua co cho o|khong co cho o/.test(
      foldedAll,
    )
  ) {
    available = false;
  } else if (/co ky tuc xa|ky tuc xa cho|o ky tuc xa/.test(foldedAll)) {
    available = true;
  }
  if (available === null) return null;

  const cost = lines
    .map((line) =>
      /phong tro|thue tro|tien phong|chi phi o/.test(fold(line))
        ? vndValues(line)
        : [],
    )
    .find((amounts) => amounts.length === 1)?.[0];

  const record: CategoryRecord = {
    id: "cho-o",
    job_ids: [],
    available,
  };
  if (available && /ky tuc xa|ktx/.test(foldedAll)) {
    record.type = "Ký túc xá";
  }
  if (cost !== undefined) record.monthly_cost_vnd = cost;
  record.notes = clamp(lines.join("\n"), 3000);

  return serializeCategoryMarkdown("accommodation", {
    schema_version: "1.0",
    category: "accommodation",
    records: [record],
  });
};

/** The `meals` document. Like `accommodation`, the required `provided` flag
 *  must be stated by the brief itself; the per-shift meal count and the
 *  in-lieu allowance are transcribed when the brief numbers them. */
export const buildMealsMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const foldedAll = fold(lines.join("\n"));
  let provided: boolean | null = null;
  if (/khong (?:phuc vu|cung cap|co com|bao an|co bua an)/.test(foldedAll)) {
    provided = false;
  } else if (
    /mien phi|phuc vu|cung cap|duoc an|suat com|com ca|bao com/.test(foldedAll)
  ) {
    provided = true;
  }
  if (provided === null) return null;

  let mealsPerShift: number | null = null;
  let allowance: number | null = null;
  const menu: string[] = [];
  const notes: string[] = [];
  for (const line of lines) {
    const folded = fold(line);
    const perShift = /\b(\d+)\s*(?:suất|bữa)(?:\s*cơm)?\s*ca\b/iu.exec(line);
    if (mealsPerShift === null && perShift) mealsPerShift = Number(perShift[1]);
    if (
      allowance === null &&
      /khong an|khong su dung|ho tro|tien an/.test(folded)
    ) {
      const amounts = vndValues(line);
      if (amounts.length === 1) allowance = amounts[0];
    }
    if (/suat|com|bua an|thuc don|dinh duong/.test(folded)) menu.push(line);
    else notes.push(line);
  }

  const record: CategoryRecord = { id: "bua-an", job_ids: [], provided };
  if (mealsPerShift !== null) record.meals_per_shift = mealsPerShift;
  if (allowance !== null) record.allowance_vnd = allowance;
  if (menu.length > 0) {
    record.menu_notes = clamp(menu.join("\n"), 3000);
  }
  if (notes.length > 0) {
    record.notes = clamp(notes.join("\n"), 3000);
  }

  return serializeCategoryMarkdown("meals", {
    schema_version: "1.0",
    category: "meals",
    records: [record],
  });
};

/** The `transportation` document. `direction` is REQUIRED and describes the
 *  route the brief names ("đưa đón" is pick-up AND return). The pickup points
 *  the brief lists become `stops` in the order it lists them. */
export const buildTransportationMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const foldedAll = fold(lines.join("\n"));
  let direction: "to_factory" | "from_factory" | "round_trip" | null = null;
  if (/dua don|don tra|hai chieu|2 chieu/.test(foldedAll))
    direction = "round_trip";
  else if (/\bdon\b/.test(foldedAll)) direction = "to_factory";
  else if (/\btra\b/.test(foldedAll)) direction = "from_factory";
  if (direction === null) return null;

  const firstLabel = lines
    .map((line) => splitLabel(line).label)
    .find((label) => label && /xe|tuyen|dua don|van tai/.test(fold(label)));
  const name = clamp(firstLabel || "Xe đưa đón", 500);

  const fee = /mien phi|khong mat phi/.test(foldedAll)
    ? 0
    : lines
        .map((line) =>
          /phi van tai|phi xe|tien xe|gia ve/.test(fold(line))
            ? vndValues(line)
            : [],
        )
        .find((amounts) => amounts.length === 1)?.[0];

  const stops: { order: number; name: string }[] = [];
  for (const line of lines) {
    const numbered = /^điểm\s*(\d+)\s*[:.]\s*(.*)$/iu.exec(line);
    if (numbered && numbered[2]) {
      stops.push({
        order: Number(numbered[1]),
        name: clamp(numbered[2], 5000),
      });
      continue;
    }
    const listed =
      /(?:tại|gồm|có)\s*(?:các\s*)?(?:\d+\s*)?điểm\s*[:：]\s*(.+)$/iu.exec(
        line,
      );
    if (listed && stops.length === 0) {
      listed[1]
        .split(/,\s*|\s+và\s+/)
        .map((stop) => stop.trim().replace(/\.$/, ""))
        .filter(Boolean)
        .forEach((stop, index) =>
          stops.push({ order: index + 1, name: clamp(stop, 5000) }),
        );
    }
  }
  stops.sort((left, right) => left.order - right.order);

  const stopLine =
    /^(?:điểm\s*\d+\s*[:.])|(?:tại|gồm|có)\s*(?:các\s*)?(?:\d+\s*)?điểm\s*[:：]/iu;
  const notes = lines.filter(
    (line) => !(stops.length > 0 && stopLine.test(line)),
  );

  const record: CategoryRecord = {
    id: "tuyen-xe-dua-don",
    job_ids: [],
    name,
    direction,
  };
  if (fee !== undefined) record.fee_vnd = fee;
  if (stops.length > 0) {
    record.stops = stops.map((stop) => ({
      order: stop.order,
      name: stop.name,
    }));
  }
  record.notes = clamp(notes.join("\n"), 3000);

  return serializeCategoryMarkdown("transportation", {
    schema_version: "1.0",
    category: "transportation",
    records: [record],
  });
};

/** The `insurance` document: the scheme the brief names as `name`, the
 *  statutory schemes it lists as `coverage`, and the enrolment timing it
 *  states in `starts_after`. */
export const buildInsuranceMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const named = lines
    .map((line) => splitLabel(line).label)
    .find((label) => label && /bao hiem|bhxh|bh/.test(fold(label)));
  if (!named) return null;

  const foldedAll = fold(lines.join("\n"));
  const coverage: string[] = [];
  if (/bhxh|bao hiem xa hoi/.test(foldedAll)) coverage.push("BHXH");
  if (/bhyt|bao hiem y te/.test(foldedAll)) coverage.push("BHYT");
  if (/bhtn|bao hiem that nghiep/.test(foldedAll)) coverage.push("BHTN");
  if (/bao hiem tai nan/.test(foldedAll)) coverage.push("Bảo hiểm tai nạn");

  const startsAfter =
    lines
      .map(
        (line) =>
          // Marked and plain spellings of "từ tháng", matched on the raw
          // line because the matched TEXT is what gets transcribed.
          /từ tháng[^.,;)]*/u.exec(line)?.[0] ??
          /tu thang[^.,;)]*/iu.exec(line)?.[0],
      )
      .find(Boolean) ?? null;
  const eligibility = lines.filter((line) =>
    /nguyen vong|co nhu cau|dieu kien/.test(fold(line)),
  );

  const record: CategoryRecord = {
    id: "bao-hiem",
    job_ids: [],
    name: clamp(named, 500),
  };
  if (coverage.length > 0) record.coverage = coverage;
  if (startsAfter) record.starts_after = clamp(startsAfter, 1000);
  if (eligibility.length > 0) {
    record.eligibility = clamp(eligibility.join("\n"), 2000);
  }
  record.notes = clamp(lines.join("\n"), 3000);

  return serializeCategoryMarkdown("insurance", {
    schema_version: "1.0",
    category: "insurance",
    records: [record],
  });
};

/** The `application` document: the process the brief writes (arrow chains and
 *  action lines become steps), the papers it lists, and the interview, timing
 *  and fee facts in their own fields. */
export const buildApplicationMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  const steps: string[] = [];
  const documents: string[] = [];
  const onboarding: string[] = [];
  const interview: string[] = [];
  const notes: string[] = [];
  let interviewLocation: string | null = null;
  let processingTime: string | null = null;
  let fees: string | null = null;

  for (const line of lines) {
    const folded = fold(line);
    if (/[➔➜→⟶]/.test(line)) {
      for (const step of line.split(/\s*[➔➜→⟶]+\s*/)) {
        const value = step.trim().replace(/^[*\s]+|[*\s]+$/, "");
        if (value) steps.push(clamp(value, 2000));
      }
      continue;
    }
    if (
      /giay to|ho so|cccd|can cuoc|so yeu ly lich|don xin viec|giay kham|bang cap|photo cong chung|vneid|giay xac nhan/.test(
        folded,
      )
    ) {
      documents.push(clamp(line, 2000));
      continue;
    }
    if (/phong van/.test(folded)) {
      interview.push(clamp(line, 3000));
      const at = /\s(?:tai|o)\s+([^.;]+)$/iu.exec(line);
      if (interviewLocation === null && at) {
        interviewLocation = clamp(at[1], 1000);
      }
      continue;
    }
    if (
      /trong ngay|ngay hom sau|bao lau|thoi gian xu ly|di lam ngay/.test(folded)
    ) {
      if (processingTime === null) processingTime = clamp(line, 1000);
      continue;
    }
    if (/\bphi\b|tien phi|khong thu phi/.test(folded)) {
      if (fees === null) fees = clamp(line, 1000);
      continue;
    }
    if (/ngay dau|nhan viec|vao lam|hoan tat/.test(folded)) {
      onboarding.push(clamp(line, 2000));
      continue;
    }
    if (
      /^(dang ky|nop|tham gia|di kham|nhan lich|bo tri|xac nhan|hoan thien)/.test(
        folded,
      )
    ) {
      steps.push(clamp(line, 2000));
      continue;
    }
    notes.push(line);
  }

  const record: CategoryRecord = { id: "quy-trinh-ung-tuyen", job_ids: [] };
  if (steps.length > 0) record.application_steps = steps;
  if (documents.length > 0) record.required_documents = documents;
  if (interviewLocation) record.interview_location = interviewLocation;
  if (interview.length > 0) {
    record.interview_process = clamp(interview.join("\n"), 3000);
  }
  if (onboarding.length > 0) record.onboarding_steps = onboarding;
  if (processingTime) record.processing_time = processingTime;
  if (fees) record.fees = fees;
  if (notes.length > 0) {
    record.notes = clamp(notes.join("\n"), 3000);
  }

  return serializeCategoryMarkdown("application", {
    schema_version: "1.0",
    category: "application",
    records: [record],
  });
};

/** The `contacts` document: one row per person the brief names. A block
 *  header ("Cán bộ phụ trách đón tiếp...") becomes the role of the people
 *  under it; an office header collects the address and working hours the
 *  brief states. `ContactItem.name` is REQUIRED, so a row exists only where
 *  the brief names somebody or something. */
export const buildContactsMarkdown = (body: string): string | null => {
  const lines = bodyLines(body).filter((line) => !isTranscriptMarker(line));
  if (lines.length === 0) return null;

  type Draft = {
    name: string;
    role: string;
    phone: string;
    zalo: string;
    email: string;
    address: string;
    workingHours: string;
    notes: string[];
  };
  const PHONE = /(?:\+?84|0)(?:[\s.-]*\d){8,9}/;
  const takePhone = (draft: Draft, value: string): void => {
    const match = PHONE.exec(value);
    if (!match) return;
    const digits = match[0].replace(/[\s.-]/g, "");
    if (!draft.phone) draft.phone = digits;
    if (/zalo/i.test(value) && !draft.zalo) draft.zalo = digits;
  };

  const drafts: Draft[] = [];
  let current: Draft | null = null;
  let pendingRole = "";
  let pendingName = "";
  const startDraft = (name: string): Draft => {
    const draft: Draft = {
      name,
      role: pendingRole,
      phone: "",
      zalo: "",
      email: "",
      address: "",
      workingHours: "",
      notes: [],
    };
    drafts.push(draft);
    current = draft;
    return draft;
  };

  for (const line of lines) {
    const { label, value } = splitLabel(line);
    const folded = fold(label);

    if (label && /^(mr|mrs|ms|anh|chi|thay|co)\b/.test(fold(label))) {
      const draft = startDraft(label);
      takePhone(draft, value);
      continue;
    }
    if (label && /ho va ten|ten lien he|ho ten/.test(folded)) {
      startDraft(value || label);
      continue;
    }
    if (
      label &&
      /sdt|so dien thoai|dien thoai|phone|zalo|hotline/.test(folded)
    ) {
      const draft = current ?? startDraft(pendingName || label);
      takePhone(draft, value);
      continue;
    }
    if (
      label &&
      /chuc nang|chuc vu|vai tro|nhiem vu|phu trach|cong viec/.test(folded)
    ) {
      if (value) {
        const draft = current ?? startDraft(pendingName);
        draft.role = clamp(value, 500);
      } else {
        pendingRole = clamp(label, 500);
      }
      continue;
    }
    if (label && /dia chi/.test(folded)) {
      const draft = current ?? startDraft(pendingName || label);
      if (value) draft.address = clamp(value, 1000);
      else pendingName = label;
      continue;
    }
    if (label && /thoi gian lam viec|gio lam viec|gio mo cua/.test(folded)) {
      const draft = current ?? startDraft(pendingName || label);
      draft.workingHours = clamp(value, 1000);
      continue;
    }
    if (label && /mail/.test(folded)) {
      const draft = current ?? startDraft(pendingName || label);
      draft.email = clamp(value, 320);
      continue;
    }
    if (label && !value) {
      // A bare header line: either the office block ("Thông tin văn phòng
      // công ty") or the role of the people below it.
      if (/van phong/.test(folded)) pendingName = clamp(label, 500);
      else if (
        /^(can bo|nhan vien|chuyen vien|nguoi phu trach|admin|quan ly)/.test(
          folded,
        )
      ) {
        pendingRole = clamp(label, 500);
      }
      continue;
    }
    // Plain prose: an address line under an office header, a phone with no
    // label, anything else — attached to the block it arrived in.
    const draft = current ?? startDraft(pendingName);
    if (
      pendingName &&
      !draft.address &&
      /phong|dia chi/.test(fold(pendingName))
    ) {
      draft.address = clamp(line, 1000);
      pendingName = "";
      continue;
    }
    takePhone(draft, line);
    draft.notes.push(clamp(line, 3000));
  }

  // Every row needs a name the brief stated. A name-less row is only kept
  // when it still carries contact facts — nothing is invented to give it an
  // identity.
  const kept = drafts.filter(
    (draft) =>
      draft.name ||
      draft.phone ||
      draft.role ||
      draft.address ||
      draft.workingHours ||
      draft.email,
  );
  if (kept.length === 0) return null;

  const used = new Map<string, number>();
  const records = kept.map((draft, index) => {
    const name = clamp(draft.name || "Liên hệ", 500);
    const record: CategoryRecord = { id: claimId(used, name, index), name };
    if (draft.role) record.role = draft.role;
    if (draft.phone) record.phone = draft.phone;
    if (draft.zalo) record.zalo = draft.zalo;
    if (draft.email) record.email = draft.email;
    if (draft.address) record.address = draft.address;
    if (draft.workingHours) record.working_hours = draft.workingHours;
    if (draft.notes.length > 0) {
      record.notes = clamp(draft.notes.join("\n"), 3000);
    }
    return record;
  });

  return serializeCategoryMarkdown("contacts", {
    schema_version: "1.0",
    category: "contacts",
    records,
  });
};

// ── the plan ───────────────────────────────────────────────────────────────

/** What a brief can seed without inventing anything, and what it cannot. */
export type BriefKnowledgePlan = Readonly<{
  /** Categories to write, in the order they should be written. */
  writes: readonly Readonly<{
    key: ProjectKnowledgeCategory;
    filename: string;
    content: string;
  }>[];
  /** Categories the brief does not carry in a form their schema accepts —
   *  named so the recruiter is told, not left guessing. */
  needsHuman: readonly ProjectKnowledgeCategory[];
}>;

/** Roles a brief states only in prose ("Chức danh: ...") still seed `jobs`:
 *  the overview table is the usual source, not the only honest one. */
const rolesFromJobsBody = (body: string): string[] =>
  bodyLines(body)
    .map((line) => /^chức danh\s*[:：]\s*(.*)$/iu.exec(line)?.[1]?.trim() ?? "")
    .filter(Boolean);

export const planBriefKnowledge = (brief: ProjectBrief): BriefKnowledgePlan => {
  const writes: {
    key: ProjectKnowledgeCategory;
    filename: string;
    content: string;
  }[] = [];
  const push = (
    key: ProjectKnowledgeCategory,
    content: string | null,
  ): void => {
    if (content) writes.push({ key, filename: `${key}.md`, content });
  };

  // `jobs` goes FIRST and always. Every other category's rows may reference
  // `job_ids`, and the API rejects a write whose references do not resolve
  // against the jobs that are active at that moment — so activating jobs first
  // is what makes the rest of the batch writable. It is also the category
  // activation itself requires, so a brief with no role at all has nothing to
  // activate and the form asks the recruiter for one title instead.
  const roles =
    brief.roles.length > 0
      ? brief.roles
      : rolesFromJobsBody(brief.categories.jobs ?? "");
  if (roles.length > 0) {
    writes.push({
      key: "jobs",
      filename: "jobs.md",
      content: buildJobsMarkdown(roles, brief.location),
    });
  }

  // Content-driven, in catalog order: whatever the brief genuinely mapped to a
  // category is formatted into that category's schema; a builder returning
  // null (no material, or required fields the brief does not state) leaves the
  // category for `needsHuman` below.
  push(
    "compensation",
    buildCompensationMarkdown(brief.categories.compensation ?? ""),
  );
  push(
    "requirements",
    buildRequirementsMarkdown(brief.categories.requirements ?? ""),
  );
  push(
    "work_schedules",
    buildWorkSchedulesMarkdown(brief.categories.work_schedules ?? ""),
  );
  push("benefits", buildBenefitsMarkdown(brief.categories.benefits ?? ""));
  push(
    "accommodation",
    buildAccommodationMarkdown(brief.categories.accommodation ?? ""),
  );
  push("meals", buildMealsMarkdown(brief.categories.meals ?? ""));
  push(
    "transportation",
    buildTransportationMarkdown(brief.categories.transportation ?? ""),
  );
  push("insurance", buildInsuranceMarkdown(brief.categories.insurance ?? ""));
  push(
    "application",
    buildApplicationMarkdown(brief.categories.application ?? ""),
  );
  push("contacts", buildContactsMarkdown(brief.categories.contacts ?? ""));

  // The Q&A bank writes only pairs the brief actually answered — the builder
  // drops the rest as a contract rule. A bank with dropped pairs still writes
  // what it can answer, but stays named in `needsHuman` so the questions the
  // brief left open reach a human instead of vanishing.
  const faqEntries = brief.faqEntries.filter(
    (entry) => entry.question.trim() && entry.answer.trim(),
  );
  const faqIncomplete = faqEntries.length < brief.faqEntries.length;
  if (faqEntries.length > 0) {
    writes.push({
      key: "faq",
      filename: "faq.md",
      content: buildFaqMarkdown(faqEntries),
    });
  }

  const written = new Set(writes.map((write) => write.key));
  return {
    writes,
    // Every category this batch did NOT write, plus a category whose content
    // had gaps the batch could not honestly fill. Computed from the full list
    // rather than a fixed remainder so a category that is skipped because the
    // brief had nothing to say about it — `jobs` above all — is still named as
    // needing a person instead of vanishing from the report.
    needsHuman: PROJECT_KNOWLEDGE_CATEGORIES.filter(
      (key) => !written.has(key) || (key === "faq" && faqIncomplete),
    ),
  };
};
