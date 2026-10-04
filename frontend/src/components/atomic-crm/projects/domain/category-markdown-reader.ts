import {
  CATEGORY_MARKDOWN_SCHEMAS,
  type CategoryRow,
  type CategoryScalar,
} from "./project-knowledge-markdown";
import type { ProjectKnowledgeCategory } from "./project-knowledge-policy";

/**
 * Display-side reader for Category Markdown v1 — the mirror image of
 * `serializeCategoryMarkdown`. Where the backend parser is strict (it guards
 * what the bot ingests), this reader is tolerant: an operator-authored or
 * partially-broken document must still render, so every rule violation lands
 * in `malformed`/`errors` instead of throwing.
 */

export type CategoryRecordFieldView =
  | Readonly<{ kind: "scalar"; name: string; display: string }>
  | Readonly<{ kind: "list"; name: string; items: readonly string[] }>
  | Readonly<{
      kind: "table";
      name: string;
      columns: readonly string[];
      rows: readonly (readonly string[])[];
    }>;

export type CategoryRecordView = Readonly<{
  /** The `### record:` id, or `record-N` when the heading omitted it. */
  id: string;
  /** First of title/question/name, or the id — the card heading. */
  title: string;
  fields: readonly CategoryRecordFieldView[];
  malformed: readonly string[];
}>;

export type CategoryDocumentView = Readonly<{
  schema_version: string | null;
  category: string | null;
  records: readonly CategoryRecordView[];
  /** True when the document carries the v1 envelope (frontmatter + section heading). */
  isCategoryMarkdown: boolean;
  errors: readonly string[];
}>;

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

const decodeScalar = (raw: string): CategoryScalar => {
  const value = raw.trim();
  if (value === "null" || value === "") return null;
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

/** Field labels shown on the record cards. Unknown keys fall back to the raw
 *  key — display only, never fed back to the API. */
const FIELD_LABELS_VI: Readonly<Record<string, string>> = {
  title: "Vị trí",
  question: "Câu hỏi",
  answer: "Trả lời",
  name: "Tên",
  role: "Vai trò",
  location: "Địa điểm",
  summary: "Mô tả",
  keywords: "Từ khóa",
  aliases: "Tên gọi khác",
  gender: "Giới tính",
  age_min: "Tuổi tối thiểu",
  age_max: "Tuổi tối đa",
  degree: "Bằng cấp",
  experience: "Kinh nghiệm",
  salary_gross: "Lương gross",
  amount_vnd: "Số tiền (VND)",
  cadence: "Chu kỳ",
  conditions: "Điều kiện",
  work_days: "Ngày làm việc",
  work_hours: "Giờ làm việc",
  breaks: "Nghỉ giữa ca",
  overtime_policy: "Tăng ca",
  included_services: "Dịch vụ bao gồm",
  address: "Địa chỉ",
  phone: "Điện thoại",
  zalo: "Zalo",
  email: "Email",
  working_hours: "Giờ làm việc",
  tags: "Nhãn",
  question_variants: "Biến thể câu hỏi",
  required_terms: "Từ bắt buộc",
  forbidden_terms: "Từ cấm",
  start_time: "Giờ bắt đầu",
  end_time: "Giờ kết thúc",
  notes: "Ghi chú",
};

export const fieldLabel = (name: string): string =>
  FIELD_LABELS_VI[name] ?? name;

const displayScalar = (value: CategoryScalar): string => {
  if (value === null || value === undefined) return "";
  if (value === true) return "Có";
  if (value === false) return "Không";
  return String(value);
};

const displayRow = (row: CategoryRow, columns: readonly string[]): string[] =>
  columns.map((column) => displayScalar(row[column] ?? null));

type ParsedEntry =
  | { kind: "scalar"; name: string; raw: string }
  | { kind: "list"; name: string; items: CategoryScalar[] }
  | {
      kind: "table";
      name: string;
      columns: string[];
      rows: CategoryRow[];
    };

const SCALAR_LINE = /^([A-Za-z][A-Za-z0-9_]*):(?:[ ](.*))?$/;

const buildFieldViews = (entries: ParsedEntry[]): CategoryRecordFieldView[] => {
  const views: CategoryRecordFieldView[] = [];
  for (const entry of entries) {
    if (entry.kind === "scalar") {
      const value = decodeScalar(entry.raw);
      if (value === null || value === "") continue;
      views.push({
        kind: "scalar",
        name: entry.name,
        display: displayScalar(value),
      });
      continue;
    }
    if (entry.kind === "list") {
      const items = entry.items
        .map((item) => displayScalar(item))
        .filter((item) => item !== "");
      if (items.length === 0) continue;
      views.push({ kind: "list", name: entry.name, items });
      continue;
    }
    if (entry.rows.length === 0) continue;
    views.push({
      kind: "table",
      name: entry.name,
      columns: entry.columns,
      rows: entry.rows.map((row) => displayRow(row, entry.columns)),
    });
  }
  return views;
};

const orderEntries = (
  entries: ParsedEntry[],
  order: readonly string[],
): ParsedEntry[] => {
  const byName = new Map(entries.map((entry) => [entry.name, entry]));
  const ordered: ParsedEntry[] = [];
  for (const name of order) {
    const entry = byName.get(name);
    if (!entry) continue;
    if (name === "id") continue;
    ordered.push(entry);
    byName.delete(name);
  }
  ordered.push(...byName.values());
  return ordered;
};

export const parseCategoryMarkdownView = (
  source: string,
  categoryKey: ProjectKnowledgeCategory,
): CategoryDocumentView => {
  const schema = CATEGORY_MARKDOWN_SCHEMAS[categoryKey];
  const errors: string[] = [];
  const lines = source.split("\n");

  let schemaVersion: string | null = null;
  let categoryMeta: string | null = null;
  let bodyStart = 0;
  let isCategoryMarkdown = false;
  if (lines[0] === "---") {
    const close = lines.indexOf("---", 1);
    if (close > 0) {
      for (const line of lines.slice(1, close)) {
        const separator = line.indexOf(":");
        if (separator === -1) continue;
        const key = line.slice(0, separator).trim();
        const value = line.slice(separator + 1).trim();
        if (key === "schema_version") schemaVersion = value.replace(/"/g, "");
        if (key === "category") categoryMeta = value;
      }
      bodyStart = close + 1;
      isCategoryMarkdown = true;
    }
  }

  const heading = `## ${schema.listField}`;
  const headingIndex = lines.indexOf(heading, bodyStart);
  if (headingIndex >= 0) {
    bodyStart = headingIndex + 1;
    isCategoryMarkdown = true;
  }

  const recordViews: CategoryRecordView[] = [];
  let entries: ParsedEntry[] = [];
  let malformed: string[] = [];
  let recordId: string | null = null;
  let ordinal = 0;
  let openField: ParsedEntry | null = null;
  let tableColumns: string[] | null = null;

  const flushRecord = () => {
    if (recordId === null) return;
    const titleEntry = entries.find(
      (entry) =>
        entry.name === "title" ||
        entry.name === "question" ||
        entry.name === "name",
    );
    const title =
      titleEntry && titleEntry.kind === "scalar"
        ? decodeScalar(titleEntry.raw) || recordId
        : recordId;
    recordViews.push({
      id: recordId,
      title: typeof title === "string" ? title : recordId,
      fields: buildFieldViews(
        orderEntries(
          entries,
          schema.fields.map((field) => field.name),
        ),
      ),
      malformed,
    });
    entries = [];
    malformed = [];
  };

  for (let index = bodyStart; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim() === "") continue;
    if (line.startsWith("### record: ")) {
      flushRecord();
      recordId = line.slice("### record: ".length).trim() || null;
      ordinal += 1;
      if (recordId === null) recordId = `record-${ordinal}`;
      openField = null;
      tableColumns = null;
      continue;
    }
    if (line.startsWith("|")) {
      const cells = splitCells(line);
      if (openField === null || openField.kind !== "table") {
        malformed.push(`Dòng ${index + 1}: ${line}`);
        continue;
      }
      if (tableColumns === null) {
        tableColumns = cells;
        continue;
      }
      if (cells.every((cell) => SEPARATOR_CELL.test(cell))) continue;
      if (cells.length !== tableColumns.length) {
        malformed.push(`Dòng ${index + 1}: ${line}`);
        continue;
      }
      const row: CategoryRow = {};
      tableColumns.forEach((column, cellIndex) => {
        row[column] = decodeScalar(cells[cellIndex]);
      });
      openField.rows.push(row);
      continue;
    }
    if (line.startsWith("- ")) {
      if (openField === null || openField.kind !== "list") {
        malformed.push(`Dòng ${index + 1}: ${line}`);
        continue;
      }
      openField.items.push(decodeScalar(line.slice(2)));
      continue;
    }
    const match = SCALAR_LINE.exec(line);
    if (match === null) {
      malformed.push(`Dòng ${index + 1}: ${line}`);
      continue;
    }
    const [, name, raw = ""] = match;
    if (recordId === null) continue;
    if (raw === "" || raw === "[]") {
      const nextEntry: ParsedEntry =
        raw === "[]"
          ? { kind: "list", name, items: [] }
          : schema.fields.some(
                (field) => field.name === name && field.kind === "table",
              )
            ? { kind: "table", name, columns: [], rows: [] }
            : { kind: "list", name, items: [] };
      entries.push(nextEntry);
      openField = raw === "[]" ? null : nextEntry;
      tableColumns = null;
      continue;
    }
    entries.push({ kind: "scalar", name, raw });
    openField = null;
    tableColumns = null;
  }
  flushRecord();

  return {
    schema_version: schemaVersion,
    category: categoryMeta,
    records: recordViews,
    isCategoryMarkdown,
    errors,
  };
};
