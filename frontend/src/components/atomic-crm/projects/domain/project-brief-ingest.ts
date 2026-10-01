import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  type ProjectKnowledgeCategory,
  type ProjectKnowledgeMode,
} from "./project-knowledge-policy";
import { slugifyVietnamese } from "./vietnamese-slug";

/**
 * project-brief-ingest — read ONE project brief (`.md` / `.txt`) and propose
 * everything `Tạo dự án` would otherwise ask the recruiter to retype.
 *
 * The recruiter's brief is a Q&A sheet: a PHẦN I overview table plus numbered
 * PHẦN II sections that each hold "Câu hỏi thường gặp" and "Thông tin phản
 * hồi". This maps that shape onto the product's own vocabulary — the six
 * discovery fields and the twelve knowledge categories — with no model call, so
 * the result is deterministic, instant, and reviewable before it is saved.
 *
 * NOTHING is dropped silently: a section this parser cannot classify is
 * returned in `unmappedSections` so the UI can show it, and every field is only
 * ever a PROPOSAL — the recruiter still reviews the form and presses save.
 */

/** One Q&A pair, only emitted when a section's question and answer counts line
 *  up; a section that does not pair still keeps its full transcript in the
 *  `faq` category body, so nothing is lost to a failed guess. */
export type ProjectBriefFaqEntry = Readonly<{
  question: string;
  answer: string;
}>;

export type ProjectBrief = Readonly<{
  /** Falsy when the brief carries no project name — the form then keeps the
   *  recruiter's own typing and nothing is overwritten. */
  name: string;
  slug: string;
  aliases: string[];
  summary: string;
  location: string;
  roles: string[];
  highlights: string[];
  knowledgeMode: ProjectKnowledgeMode;
  /** Knowledge body per category; a category the brief does not cover is
   *  simply absent, and `missingCategories` names it. */
  categories: Readonly<Partial<Record<ProjectKnowledgeCategory, string>>>;
  faqEntries: readonly ProjectBriefFaqEntry[];
  missingCategories: readonly ProjectKnowledgeCategory[];
  unmappedSections: readonly Readonly<{ title: string; body: string }>[];
  /** The brief verbatim, for DIRECT_CONTEXT single-page mode. */
  rawText: string;
}>;

export const EMPTY_PROJECT_BRIEF: ProjectBrief = Object.freeze({
  name: "",
  slug: "",
  aliases: [],
  summary: "",
  location: "",
  roles: [],
  highlights: [],
  knowledgeMode: "DIRECT_CONTEXT",
  categories: {},
  faqEntries: [],
  missingCategories: PROJECT_KNOWLEDGE_CATEGORIES,
  unmappedSections: [],
  rawText: "",
});

/** "Một nội dung" needs no category split; below this many sections a brief
 *  reads better as one page the agent sees whole. */
const CATEGORY_MODE_THRESHOLD = 3;

// ── text helpers ───────────────────────────────────────────────────────────

/** Diacritic-free lowercase, so a label matches whether or not the brief
 *  carries marks ("Địa điểm" ≡ "dia diem"). */
const fold = (value: string): string =>
  value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();

/** Strip the emphasis, code ticks and the `$$…$$` LaTeX the briefs use for
 *  process arrows, so the result is prose an agent can read verbatim. */
const toPlainText = (value: string): string =>
  value
    .replace(/\$\$([^$]*)\$\$/g, (_match, inner: string) =>
      inner
        .replace(/\\text\{([^}]*)\}/g, "$1")
        .replace(/\\longrightarrow|→/g, " → ")
        .replace(/\\[a-zA-Z]+/g, " ")
        .replace(/\s*([→])\s*/g, " $1 ")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/<br\s*\/?>/gi, "\n")
    .trim();

/** Overview cells arrive as one line joined by `<br>`, sometimes as
 *  `- item` runs; both become a list. */
const toList = (value: string): string[] =>
  value
    .split(/\n+/)
    .map((line) => line.replace(/^\s*[-*•]\s*/, "").trim())
    .filter(Boolean);

/** "4P Electronics / 4P Hải Phòng" → two aliases; commas inside a single
 *  alias stay put, because an alias is a name, not a list. */
const toAliasList = (value: string): string[] =>
  value
    .split(/\s*[/|]\s*/)
    .map((item) => item.trim())
    .filter(Boolean);

/** The short "Hải Phòng" the discovery card shows, taken from the last
 *  segment of a full address and stripped of its province prefix. */
const toShortLocation = (value: string): string => {
  const segments = value
    .split(",")
    .map((segment) => segment.trim())
    .filter(Boolean);
  const last = segments[segments.length - 1] ?? value;
  return last.replace(/^(TP|Thành phố|Tỉnh)\.?\s+/i, "").trim() || value.trim();
};

/** Split on commas that are NOT inside parentheses. The real brief writes
 *  "Công nhân sản xuất điện tử (SMT, PCBA, KHO (MAT, PPS), …)" — a plain
 *  comma split tears "KHO (MAT" and "PPS)" apart. */
const splitTopLevel = (value: string): string[] => {
  const parts: string[] = [];
  let depth = 0;
  let buffer = "";
  for (const char of value) {
    if (char === "(") depth += 1;
    else if (char === ")") depth = Math.max(0, depth - 1);
    if (char === "," && depth === 0) {
      parts.push(buffer);
      buffer = "";
      continue;
    }
    buffer += char;
  }
  parts.push(buffer);
  return parts.map((part) => part.trim()).filter(Boolean);
};

/** The recruiter's own comma list, with a parenthetical tail broken out so
 *  each skill stands on its own while its inner commas stay inside it. */
const toRoleList = (value: string): string[] =>
  toList(value)
    .flatMap((item) => {
      const open = item.indexOf("(");
      const close = item.lastIndexOf(")");
      if (open === -1 || close <= open) return splitTopLevel(item);
      const head = item.slice(0, open).trim();
      const tail = splitTopLevel(item.slice(open + 1, close));
      return [head, ...tail].filter(Boolean);
    })
    .filter(Boolean);

// ── raw-brief normalization: HTML tables and template samples ──────────────

/** The markers the intake template labels its own demonstration material with
 *  ("Nội dung mẫu tham khảo:", a "Ví dụ mẫu: …" column). Matching the marker
 *  text — never a file name — is what keeps the template's sample projects
 *  (LG Display, Rorze…) out of the knowledge a real project ships with. */
const EXAMPLE_MARKERS: readonly string[] = ["mau tham khao", "vi du mau"];

const carriesExampleMarker = (value: string): boolean => {
  const folded = fold(value);
  return EXAMPLE_MARKERS.some((marker) => folded.includes(marker));
};

const decodeEntities = (value: string): string =>
  value
    .replace(/&#(\d{1,7});/g, (_match, code: string) =>
      String.fromCodePoint(Number(code)),
    )
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");

/** One cell's text: tags become line breaks and bullets, entities decode, so a
 *  `.docx`-converted HTML table reads like markdown the recruiter typed. */
const unwrapHtmlCell = (html: string): string =>
  decodeEntities(
    html
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<li[^>]*>/gi, "\n- ")
      .replace(/<\/(?:p|div|li|tr|ul|ol|h[1-6])>/gi, "\n")
      // Bounded so a malformed tag cannot sweep the whole table into one match.
      .replace(/<[^>]{1,300}>/g, ""),
  )
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{2,}/g, "\n")
    .trim();

/** `<table>` markup → the pipe rows the table readers already understand. The
 *  lazy bounded patterns keep the pass linear in the brief's size. */
const unwrapHtmlTables = (text: string): string =>
  text.replace(/<table[\s\S]*?<\/table\s*>/gi, (tableHtml) => {
    const cellsOf = (row: string): string[] =>
      (row.match(/<t[dh][^>]*>[\s\S]*?<\/t[dh]>/gi) ?? []).map(unwrapHtmlCell);
    const rows = tableHtml.match(/<tr[\s\S]*?<\/tr\s*>/gi) ?? [];
    // A header cell naming an example column ("Ví dụ mẫu: …") starts the
    // demonstration columns: everything from there on is the form's sample,
    // so those cells are dropped wholesale before they can become data.
    let exampleFrom = -1;
    const [headerRow] = rows;
    if (headerRow) {
      cellsOf(headerRow).forEach((cell, index) => {
        if (exampleFrom === -1 && carriesExampleMarker(cell)) {
          exampleFrom = index;
        }
      });
    }
    const rendered = rows.map((row) => {
      const cells = cellsOf(row).filter(
        (_cell, index) => exampleFrom === -1 || index < exampleFrom,
      );
      if (cells.length === 0) return "";
      // Intra-cell line breaks ride as `<br>`, which the cell readers unfold.
      return `| ${cells
        .map((cell) => cell.replace(/\n+/g, "<br>"))
        .join(" | ")} |`;
    });
    return `\n${rendered.filter(Boolean).join("\n")}\n`;
  });

/** Removes the template's sample blockquotes (`> **Nội dung mẫu tham khảo:**`
 *  followed by `> - *LG Display:* …` lines): a `>`-quote run whose first
 *  content line names an example marker is demonstration material. */
const dropExampleBlocks = (text: string): string => {
  const kept: string[] = [];
  let inExample = false;
  for (const line of text.split(/\r?\n/)) {
    if (!/^\s*>/.test(line)) {
      inExample = false;
      kept.push(line);
      continue;
    }
    const content = toPlainText(line.replace(/^\s*>\s?/, ""));
    if (!inExample && carriesExampleMarker(content)) inExample = true;
    if (!inExample) kept.push(line);
  }
  return kept.join("\n");
};

/** The intake form's empty overview cells arrive filled with the template's
 *  own instruction ("Tên gọi phổ biến người lao động hay hỏi") — a description
 *  of WHAT to enter, not data. Reading one as a value would put an instruction
 *  into the knowledge, so it is treated as no-data (the field stays empty and
 *  is reported as needing a person) instead. */
const PLACEHOLDER_VALUE_PATTERNS: readonly RegExp[] = [
  /ten goi pho bien.*hay hoi/,
  /gioi thieu ngan gon.*cong viec/,
];

const isPlaceholderValue = (value: string): boolean => {
  const folded = fold(toPlainText(value));
  return PLACEHOLDER_VALUE_PATTERNS.some((pattern) => pattern.test(folded));
};

// ── section classification ─────────────────────────────────────────────────

/** Heading title → the category it owns. Matched on folded text so marks do
 *  not decide. `null` means "this brief has a section I do not recognise",
 *  which is surfaced rather than guessed at. */
const CATEGORY_BY_HEADING: readonly (readonly [
  RegExp,
  ProjectKnowledgeCategory,
])[] = [
  [
    /vi tri (tuyen( dung)?|cong viec)|cong viec cu the|mo ta cong viec|dinh nghe/,
    "jobs",
  ],
  [/yeu cau|doi voi ung vien|ho so giay to/, "requirements"],
  // No bare "tăng ca": a schedule section titled "…& Quy định tăng ca" is
  // still the schedule section; the old sheet's salary sections all say
  // "lương"/"phụ cấp" anyway.
  [/tien luong|phu cap|thu nhap|^luong\b/, "compensation"],
  [
    /ca lam viec|ca kip|lich kip|lich lam viec|thoi gian lam viec|lam viec may gio/,
    "work_schedules",
  ],
  [/an uong|cho o|ky tuc|thue tro|bua an/, "meals"],
  [/xe dua don|tuyen xe dua/, "transportation"],
  [/bao hiem|kham suc khoe/, "insurance"],
  [/moi truong lam viec|bao ho lao dong|phuc loi/, "benefits"],
  [
    /quy trinh (phong van|nhan viec|tuyen dung)|ho so nhan viec|ung tuyen|thu tuc nghi viec/,
    "application",
  ],
  [/lien he|dau moi ho tro|thu muc/, "contacts"],
  [/^faq$/, "faq"],
] as const;

/** Two sections genuinely straddle two categories. Routing only the matching
 *  bullets out — rather than re-classifying the whole section — keeps each
 *  section's primary meaning intact. */
const BULLET_OVERRIDES: readonly (readonly [
  ProjectKnowledgeCategory,
  RegExp,
  ProjectKnowledgeCategory,
])[] = [
  // "Chế độ ăn uống & Chỗ ở": housing answers are not meal answers.
  ["meals", /ky tuc|ktx|cho o|thue tro|tu tuc/, "accommodation"],
  // …and neither is a shuttle answer ("ăn uống, ký túc xá & xe đưa đón").
  ["meals", /xe dua don|xang xe|di lai/, "transportation"],
  // "Môi trường làm việc & Bảo hộ lao động": the statutory schemes are insurance.
  ["benefits", /bao hiem xa hoi|bhxh|bhyt|bhtn|bao hiem tai nan/, "insurance"],
  // …while a "Bảo hiểm & Môi trường làm việc" section's environment and
  // welfare bullets are benefits, not insurance answers.
  [
    "insurance",
    /moi truong|trang phuc|dong phuc|smock|phuc loi|cong doan|du lich/,
    "benefits",
  ],
] as const;

// ── markdown walking ───────────────────────────────────────────────────────

const HEADING = /^#{1,6}\s+(.*)$/;
const BULLET = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/;
/** Plain-text briefs need no Markdown. Restrict labels to short, named
 *  categories so sentences containing "lương" cannot become headings. */
const PLAIN_CATEGORY_LABEL =
  /^(?:tien luong|luong(?: va thuong)?|thu nhap|phu cap|yeu cau(?: tuyen dung)?|ca lam viec|lich lam viec|thoi gian lam viec|phuc loi|cho o|ky tuc xa|an uong|bua an|xe dua don|bao hiem|ung tuyen|quy trinh ung tuyen|lien he|faq|cau hoi thuong gap)$/;

/** A heading plus every line under it, in document order. `depth` is the
 *  heading's `#` count; a deeper section inherits its nearest shallower
 *  ancestor's category (a `####` sub-heading inside "Ca làm việc" is that
 *  section's content, not a new topic). */
type BriefSection = {
  title: string;
  lines: string[];
  depth: number;
  markdown: boolean;
};

const splitSections = (text: string): BriefSection[] => {
  // Content before the first heading is a section too: a brief that is one
  // bare table carries no heading at all, and dropping the preamble would
  // silently lose every discovery field.
  const sections: BriefSection[] = [
    { title: "", lines: [], depth: 0, markdown: false },
  ];
  let current = sections[0];
  for (const line of text.split(/\r?\n/)) {
    const heading = HEADING.exec(line);
    if (heading) {
      current = {
        title: toPlainText(heading[1]),
        lines: [],
        depth: /#{1,6}/.exec(heading[0])?.[0].length ?? 1,
        markdown: true,
      };
      sections.push(current);
      continue;
    }
    const labeled = /^\s*(?:\d+[.)]\s*)?([^:：]{1,60})[:：]\s*(.*)$/.exec(
      toPlainText(line),
    );
    // Within a named section, a one-line label is a fact belonging to that
    // section (contact working hours, an allowance, a FAQ marker). Bare labels
    // still delimit a plain-text brief; inline sections are read at top level.
    if (
      labeled &&
      PLAIN_CATEGORY_LABEL.test(fold(labeled[1])) &&
      (!labeled[2] || !current.markdown || !categoryForHeading(current.title))
    ) {
      current = {
        title: labeled[1],
        lines: labeled[2] ? [labeled[2]] : [],
        depth: 2,
        markdown: false,
      };
      sections.push(current);
      continue;
    }
    current.lines.push(line);
  }
  return sections.filter((section) =>
    section.title !== "" ? true : section.lines.some((line) => line.trim()),
  );
};

type BriefField =
  | "name"
  | "aliases"
  | "address"
  | "roles"
  | "summary"
  | "highlights"
  | "slug"
  | "mode";

const OVERVIEW_LABELS: readonly (readonly [RegExp, BriefField])[] = [
  [/^ten du an/, "name"],
  [/^ten (viet tat|thuong goi|goi khac|doanh nghiep tiep nhan)/, "aliases"],
  [/^(dia chi(?: noi lam viec)?|dia diem noi lam viec|dia diem)/, "address"],
  [/^vi tri (tuyen dung|tuyen dung chinh)/, "roles"],
  [/^tom tat/, "summary"],
  [/diem noi bat/, "highlights"],
  [/^ma (du an|project)/, "slug"],
  [/^cach quan ly kien thuc/, "mode"],
] as const;

/** True when a stored overview field carries a value worth keeping. */
const overviewFieldHasValue = (value: unknown): boolean =>
  typeof value === "string"
    ? value.trim().length > 0
    : Array.isArray(value)
      ? value.length > 0
      : value !== undefined && value !== null && value !== "";

/** The mode names a brief writes, folded so marks never decide. */
const modeFromText = (value: string): ProjectKnowledgeMode | undefined => {
  const folded = fold(value);
  if (/mot noi dung/.test(folded)) return "DIRECT_CONTEXT";
  if (/theo danh muc/.test(folded)) return "RAG";
  return undefined;
};

/** `**Tên dự án**`, `Tên dự án *`, `Tên dự án:` — decorations stripped, what
 *  remains must be exactly a known label: the folded line matches a pattern
 *  and nothing is left over. The leftover rule is what keeps prose like
 *  "Tên dự án phải dễ nhớ" from posing as a label — unless the line itself is
 *  colon-terminated, which is how the sheets write a descriptive label whose
 *  value follows on the next lines ("Các điểm nổi bật thu hút người lao
 *  động:"). */
const bareLabelField = (line: string): BriefField | null => {
  const plain = toPlainText(line).trim();
  if (!plain || plain.length > 60) return null;
  const isLabelLine = /[:：]\s*$/.test(plain);
  const stripped = plain
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/[:：*\s]+$/, "")
    .trim();
  if (!stripped) return null;
  const folded = fold(stripped);
  if (!folded) return null;
  for (const [pattern, field] of OVERVIEW_LABELS) {
    if (
      pattern.test(folded) &&
      (isLabelLine || folded.replace(pattern, "").trim() === "")
    ) {
      return field;
    }
  }
  return null;
};

/** `Tên dự án: LG` — label and value on one line, optionally bulleted. */
const inlineLabeledField = (
  line: string,
): { field: BriefField; value: string } | null => {
  const plain = toPlainText(line)
    .replace(/^\s*[-*+]\s+/, "")
    .trim();
  const match = /^([^:：]{1,60})[:：]\s*(.+)$/.exec(plain);
  if (!match) return null;
  const label = match[1].replace(/[*_]/g, "").trim();
  const folded = fold(label);
  if (!folded) return null;
  for (const [pattern, field] of OVERVIEW_LABELS) {
    if (pattern.test(folded)) return { field, value: match[2].trim() };
  }
  return null;
};

/** Write one labeled value into the accumulator; table-found values are
 *  merged in later and win, so `??=` never fights the canonical reader.
 *  Scalar fields keep the first line; list fields read the whole block. A
 *  template instruction is rejected before either. */
const applyLabeledValue = (
  into: Partial<Overview>,
  field: BriefField,
  rawValue: string,
): void => {
  if (isPlaceholderValue(rawValue)) return;
  const value = toPlainText(rawValue).trim();
  if (!value) return;
  if (field === "name") {
    into.name ??= value.split("\n")[0].trim();
    return;
  }
  if (field === "slug") {
    into.slug ??= value.split("\n")[0].trim();
    return;
  }
  if (field === "summary") {
    into.summary ??= value.split("\n")[0].trim();
    return;
  }
  if (field === "address") {
    into.address ??= value.split("\n")[0].trim();
    return;
  }
  if (field === "aliases") into.aliases ??= toAliasList(value);
  if (field === "roles") into.roles ??= toRoleList(value);
  if (field === "highlights") into.highlights ??= toList(value);
  if (field === "mode") into.mode ??= modeFromText(value);
};

/** How far past a bare label the value block may run: one value line, or a
 *  short run of bullets ("Điểm nổi bật:" followed by its bullets). */
const MAX_LABEL_VALUE_LINES = 8;

/** The value a bare label owns: every content line until the next label, a
 *  table row or a rule — not just the first one, or a bulleted value would
 *  lose everything after its first bullet. */
const labelValueBlock = (
  lines: readonly string[],
  start: number,
): { value: string[]; index: number } | null => {
  const collected: string[] = [];
  let lastIndex = start - 1;
  const end = Math.min(start + MAX_LABEL_VALUE_LINES, lines.length);
  for (let i = start; i < end; i += 1) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (/^\s*\|/.test(line) || /^[-*_]{3,}\s*$/.test(line.trim())) break;
    if (inlineLabeledField(line) || bareLabelField(line)) break;
    collected.push(line.trim());
    lastIndex = i;
  }
  if (collected.length === 0) return null;
  return { value: collected, index: lastIndex };
};

/** Read the plain `label` → `value` shape briefs write when they are not a
 *  table: one label per line with the value on the following line, or the
 *  `Label: value` one-liner. Only fills what the overview table left empty. */
const readLabeledFields = (
  sections: readonly BriefSection[],
): Partial<Overview> => {
  const found: Partial<Overview> = {};
  for (const section of sections) {
    const { lines } = section;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (!line.trim() || /^\s*\|/.test(line)) continue;
      const inline = inlineLabeledField(line);
      if (inline) {
        // An inline label whose value is just a colon ("Vị trí tuyển dụng
        // chính:") introduces a bullet list — the bullets are the value, so
        // the label takes the block path instead of the stub.
        if (/[:：]\s*$/.test(inline.value)) {
          const value = labelValueBlock(lines, i + 1);
          if (value) {
            applyLabeledValue(found, inline.field, value.value.join("\n"));
            i = value.index;
          }
          continue;
        }
        applyLabeledValue(found, inline.field, inline.value);
        continue;
      }
      const bare = bareLabelField(line);
      if (!bare) continue;
      const value = labelValueBlock(lines, i + 1);
      if (!value) continue;
      applyLabeledValue(found, bare, value.value.join("\n"));
      i = value.index;
    }
  }
  return found;
};

type Overview = {
  name: string;
  aliases: string[];
  address: string;
  roles: string[];
  summary: string;
  highlights: string[];
  slug: string;
  mode: ProjectKnowledgeMode | undefined;
};

/** The structured header the newer briefs open with (`---` fenced YAML). It is
 *  machine-authored truth about the SAME facts the prose body states, so where
 *  it speaks it wins over prose interpretation — the roles list, the address,
 *  the project name. Mapped keys only: a field the header does not carry is
 *  still read from the body. */
const FRONTMATTER_KEYS: readonly (readonly [RegExp, BriefField])[] = [
  [/^project_?name$/, "name"],
  [/^workplace_?location$/, "address"],
  [/^target_?positions$/, "roles"],
];

const parseFrontmatter = (text: string): Partial<Overview> => {
  const fence = /^---\r?\n([\s\S]{0,40000}?)\r?\n---(?:\s*$|\r?\n)/.exec(text);
  if (!fence) return {};
  const found: Partial<Overview> = {};
  let listKey: BriefField | null = null;
  for (const raw of fence[1].split(/\r?\n/)) {
    const item = /^\s*-\s+"?([^"]+)"?\s*$/.exec(raw);
    if (item && listKey) {
      const current = found[listKey];
      const list = Array.isArray(current)
        ? [...current, item[1].trim()]
        : [item[1].trim()];
      found[listKey] = list as never;
      continue;
    }
    listKey = null;
    const pair = /^([A-Za-z][A-Za-z0-9_]*):\s*(.*)$/.exec(raw);
    if (!pair) continue;
    const field = FRONTMATTER_KEYS.find(([pattern]) =>
      pattern.test(pair[1].toLowerCase()),
    )?.[1];
    if (!field) continue;
    const value = pair[2]
      .trim()
      .replace(/^"(.*)"$/, "$1")
      .trim();
    if (!value || value === "[]") {
      listKey = field;
      continue;
    }
    const inlineList = /^\[(.+)\]$/.exec(value);
    if (inlineList) {
      found[field] = toRoleList(inlineList[1].replace(/"/g, "")) as never;
      continue;
    }
    if (field === "roles") {
      found.roles = toRoleList(value) as never;
      continue;
    }
    if (field === "address" || field === "name") {
      found[field] = value as never;
    }
  }
  return found;
};

/** Read the `| **Nhãn** | giá trị |` rows of the overview table. A label this
 *  parser does not know is ignored here — the section pass still keeps its
 *  body, so an unfamiliar label never costs the user their content. */
const readOverview = (sections: readonly BriefSection[]): Overview => {
  const overview: Overview = {
    name: "",
    aliases: [],
    address: "",
    roles: [],
    summary: "",
    highlights: [],
    slug: "",
    mode: undefined,
  };
  for (const section of sections) {
    for (const line of section.lines) {
      const row = /^\s*\|(.+)\|\s*$/.exec(line);
      if (!row) continue;
      const cells = row[1].split("|").map((cell) => cell.trim());
      if (cells.length < 2) continue;
      const label = toPlainText(cells[0])
        .replace(/[:：]$/, "")
        .trim();
      const value = toPlainText(cells.slice(1).join("|"));
      if (!label || !value) continue;
      // A `| :--- |` alignment row and the header row are not data.
      if (/^[:\- ]+$/.test(value) || fold(label).includes("mo ta noi dung"))
        continue;
      // The form's own instruction in a value cell is a request for data, not
      // the data itself.
      if (isPlaceholderValue(value)) continue;
      for (const [pattern, field] of OVERVIEW_LABELS) {
        if (pattern.test(fold(label))) {
          if (field === "name") overview.name = value;
          if (field === "aliases") overview.aliases = toAliasList(value);
          if (field === "address") overview.address = value;
          if (field === "roles") overview.roles = toRoleList(value);
          if (field === "summary") overview.summary = value;
          if (field === "highlights") overview.highlights = toList(value);
          if (field === "slug") overview.slug = value;
          if (field === "mode") overview.mode ??= modeFromText(value);
          break;
        }
      }
    }
  }
  return overview;
};

/** The real sheets write the markers several ways: "Câu hỏi thường gặp",
 *  "Câu hỏi người lao động thường hỏi", "Thông tin phản hồi", "Thông tin tư
 *  vấn / Giải đáp", "Thông tin tư vấn dự án …" — and the newer briefs pair
 *  every Q&A inline as `- **Hỏi:** …` / `- **Trả lời:** …`. The short
 *  variants are anchored at the line start so "phản hồi:" (which ends in
 *  "hoi:") can never read as a question marker. Matched on folded bullet
 *  content so the variant decides nothing. */
const QUESTION_MARKER =
  /cau hoi.*thuong (gap|hoi)|^\*{0,2}\s*hoi\s*:|^\s*questions?\b/i;
const ANSWER_MARKER =
  /thong tin (phan hoi|tu van)|^\*{0,2}\s*(giai dap|tra loi)\s*[:：]|^\s*answers?\b/i;

/** The text a marker line carries after its colon ("Hỏi: Bên công ty…" →
 *  "Bên công ty…"); empty for the bare variant ("Câu hỏi thường gặp:"). */
const markerPayload = (content: string): string => {
  const colon = content.search(/[:：]/);
  return colon >= 0 ? content.slice(colon + 1).trim() : "";
};

/** The cells of a markdown pipe-table row (`| a | b |` → ["a", "b"]); null
 *  when the line is not a table row. */
const pipeCells = (line: string): string[] | null => {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return null;
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
};

/** One Q&A section split into its question list, its answer list and the
 *  plain body that goes into the category. */
const readSectionBody = (section: BriefSection) => {
  const questions: string[] = [];
  const answers: string[] = [];
  const inlinePairs: { question: string; answer: string }[] = [];
  let inlinePair: { question: string; answer: string } | null = null;
  let bucket: "question" | "answer" | null = null;
  // A markdown pipe FAQ table ("Bảng tổng hợp câu hỏi thường gặp"): its
  // header row names the question and answer COLUMNS, and each row below is
  // one Q&A pair. Handled before the marker buckets — without this a row
  // lands whole in the question bucket, its `| q | a |` text becomes the
  // "question", and the answer is the empty string the backend contract
  // rejects (`FaqItem.answer` is `NonEmptyText`).
  let questionColumn = -1;
  let answerColumn = -1;
  for (const raw of section.lines) {
    const line = raw.trim();
    if (!line || line === "---") continue;
    // The briefs write these markers as bullets of their own
    // (`* **Câu hỏi thường gặp:**`), so the marker is recognised on the
    // bullet's CONTENT, not on a line that happens to lack a bullet glyph —
    // otherwise the bucket never switches and the whole section is dumped in
    // as one prose blob.
    const bullet = BULLET.exec(raw);
    const content = bullet ? bullet[1] : line;

    const cells = pipeCells(content);
    if (cells) {
      const headerQuestion = cells.findIndex((cell) =>
        /cau hoi/i.test(fold(cell)),
      );
      const headerAnswer = cells.findIndex((cell) =>
        /cau tra loi/i.test(fold(cell)),
      );
      if (headerQuestion >= 0 && headerAnswer >= 0) {
        questionColumn = headerQuestion;
        answerColumn = headerAnswer;
        continue;
      }
      // A separator or skeleton row (`| :--- | :--- |`) carries no knowledge.
      if (cells.every((cell) => !cell || /^:?-{2,}:?$/.test(cell))) continue;
      if (questionColumn >= 0 && answerColumn >= 0) {
        const question = toPlainText(cells[questionColumn] ?? "").trim();
        if (question) {
          questions.push(question);
          // A question whose answer cell is empty travels with an empty
          // answer, so the plan can drop the pair and name the gap — never
          // so a record with an empty `answer` reaches the API.
          answers.push(toPlainText(cells[answerColumn] ?? "").trim());
        }
        continue;
      }
      // Not a FAQ table — a data table. Falls through to the marker buckets
      // below: the overview table sits in a section with no bucket and stays
      // untouched, exactly as before.
    }

    const foldedContent = fold(content);
    if (QUESTION_MARKER.test(foldedContent)) {
      bucket = "question";
      // A bold marker's closing `**` sits after the colon; strip it so the
      // bare-marker variant contributes no phantom payload.
      const payload = toPlainText(markerPayload(content))
        .replace(/^[*_\s]+|[*_\s]+$/g, "")
        .trim();
      if (payload) questions.push(payload);
      if (payload && /^\*{0,2}\s*hoi\s*:/.test(foldedContent)) {
        inlinePair = { question: payload, answer: "" };
        inlinePairs.push(inlinePair);
      }
      continue;
    }
    if (ANSWER_MARKER.test(foldedContent)) {
      bucket = "answer";
      const payload = toPlainText(markerPayload(content))
        .replace(/^[*_\s]+|[*_\s]+$/g, "")
        .trim();
      if (payload) answers.push(payload);
      if (payload && inlinePair)
        inlinePair.answer += (inlinePair.answer ? "\n" : "") + payload;
      continue;
    }
    const value = toPlainText(content);
    if (!value) continue;
    if (bucket === "question") questions.push(value);
    else if (bucket === "answer") {
      answers.push(value);
      if (inlinePair)
        inlinePair.answer += (inlinePair.answer ? "\n" : "") + value;
    }
  }
  return { questions, answers, inlinePairs };
};

const categoryForHeading = (title: string): ProjectKnowledgeCategory | null => {
  const folded = fold(title);
  if (/^(cho o|ky tuc xa|thue tro)(?:\s*[:：])?$/.test(folded))
    return "accommodation";
  for (const [pattern, category] of CATEGORY_BY_HEADING) {
    if (pattern.test(folded)) return category;
  }
  return null;
};

const overrideFor = (
  section: ProjectKnowledgeCategory,
  text: string,
): ProjectKnowledgeCategory => {
  const folded = fold(text);
  for (const [from, pattern, to] of BULLET_OVERRIDES) {
    if (from === section && pattern.test(folded)) return to;
  }
  return section;
};

// ── entry point ────────────────────────────────────────────────────────────

/** The sheet's own scaffolding: company masthead, form title, PHẦN containers,
 *  the overview section, the chatbot Q&A bank. What sits directly under them
 *  is overview or per-question sections the readers already consumed, so
 *  reporting the container as unrecognised would be noise, not signal. */
const STRUCTURAL_HEADING =
  /^(cong ty|phieu thu thap|phan [0-9ivxl]+|phu luc|tai lieu|thong tin tong quan|ngan hang cau hoi)\b/;

/** The chatbot Q&A bank writes every entry as its own question heading. */
const QUESTION_TITLE = /(?:^❓)|\?\s*$/;

const cleanQuestionTitle = (title: string): string =>
  title
    .replace(/^❓\s*/, "")
    .replace(/^\*\*\s*câu hỏi\s*\*\*\s*[:：]?\s*/i, "")
    .replace(/^câu hỏi\s*[:：]\s*/i, "")
    .trim();

/** A question-titled section's answer: the body lines with the `*Chủ đề:*`
 *  theme tag dropped and the answer marker ("Trả lời:", "Câu trả lời chuẩn:")
 *  stripped, so the entry carries exactly the question and the answer the
 *  sheet wrote. */
const readQuestionAnswer = (
  section: BriefSection,
): { question: string; answer: string } | null => {
  const question = cleanQuestionTitle(section.title);
  if (!question) return null;
  const lines: string[] = [];
  for (const raw of section.lines) {
    const plain = toPlainText(BULLET.exec(raw)?.[1] ?? raw.trim());
    if (!plain) continue;
    if (/^\*{0,2}\s*chủ đề\s*\*{0,2}\s*[:：]/i.test(plain)) continue;
    const stripped = plain.replace(
      /^\s*\*{0,2}\s*(câu trả lời( chuẩn)?|trả lời)\s*\*{0,2}\s*[:：]\s*/i,
      "",
    );
    if (stripped) lines.push(stripped);
  }
  // No answer in the file, no answer proposed — the question alone is not
  // something the assistant may quote an answer to.
  if (lines.length === 0) return null;
  return { question, answer: lines.join("\n") };
};

export const parseProjectBrief = (text: string): ProjectBrief => {
  const rawText = text ?? "";
  if (!rawText.trim()) return EMPTY_PROJECT_BRIEF;

  // Template samples and `.docx`-converted HTML tables are normalized away
  // before sectioning; `rawText` itself stays verbatim.
  const sections = splitSections(dropExampleBlocks(unwrapHtmlTables(rawText)));
  const overview = readOverview(sections);

  const bodies = new Map<ProjectKnowledgeCategory, string[]>();
  const faqEntries: ProjectBriefFaqEntry[] = [];
  const faqTranscript: string[] = [];
  const unmappedSections: { title: string; body: string }[] = [];

  const push = (category: ProjectKnowledgeCategory, line: string) => {
    const bucket = bodies.get(category) ?? [];
    bucket.push(line);
    bodies.set(category, bucket);
  };

  // Each section's category: its own heading match first; otherwise — when it
  // is a sub-heading like `#### 1. Ca Ngày` inside a mapped section — the
  // nearest strictly shallower ancestor's category. Question-titled sections
  // stay unclaimed so the Q&A branch below owns them.
  const primaryOf = new Array<ProjectKnowledgeCategory | null>(
    sections.length,
  ).fill(null);
  const inherited = new Array<boolean>(sections.length).fill(false);
  for (let index = 0; index < sections.length; index += 1) {
    const section = sections[index];
    const heading = section.title.replace(/^\s*\d+[.)]\s*/, "").trim();
    const own =
      categoryForHeading(section.title) ?? categoryForHeading(heading);
    primaryOf[index] = own;
    if (own || QUESTION_TITLE.test(section.title.trim())) continue;
    for (let j = index - 1; j >= 0; j -= 1) {
      if (sections[j].depth < section.depth) {
        if (primaryOf[j]) {
          primaryOf[index] = primaryOf[j];
          inherited[index] = true;
          break;
        }
      }
    }
  }

  for (
    let sectionIndex = 0;
    sectionIndex < sections.length;
    sectionIndex += 1
  ) {
    const section = sections[sectionIndex];
    const primary = primaryOf[sectionIndex];
    const { questions, answers, inlinePairs } = readSectionBody(section);

    // The Q&A transcript is the `faq` category's body whether or not the
    // section's own heading mapped anywhere.
    if (questions.length > 0 || answers.length > 0) {
      const transcript: string[] = [`## ${section.title}`];
      const paired =
        questions.length > 0 && questions.length === answers.length;
      const rows =
        inlinePairs.length > 0
          ? inlinePairs
          : questions.length === 1
            ? [{ question: questions[0], answer: answers.join("\n") }]
            : paired
              ? questions.map((question, index) => ({
                  question,
                  answer: answers[index],
                }))
              : questions.map((question) => ({
                  question,
                  // Unequal grouped lists provide no reliable Q/A association.
                  // Keep the transcript and request review rather than guess.
                  answer: "",
                }));
      for (const row of rows) {
        transcript.push(`**${row.question}**`, row.answer);
        faqEntries.push(row);
      }
      if (!paired && inlinePairs.length === 0 && questions.length !== 1) {
        transcript.push(...answers);
      } else if (
        answers.length > questions.length &&
        inlinePairs.length === 0
      ) {
        // Answer lines beyond the paired ones still belong somewhere.
        transcript.push(...answers.slice(rows.length));
      }
      faqTranscript.push(transcript.join("\n\n"));
      push("faq", transcript.join("\n\n"));
    }

    if (!primary) {
      // A question-titled section is the Q&A bank's own entry format: the
      // heading is the question, the body the answer.
      if (section.title && QUESTION_TITLE.test(section.title.trim())) {
        const entry = readQuestionAnswer(section);
        if (entry) {
          const transcript = [
            `## ${entry.question}`,
            `**${entry.question}**`,
            entry.answer,
          ].join("\n\n");
          faqEntries.push(entry);
          faqTranscript.push(transcript);
          push("faq", transcript);
        }
        continue;
      }
      // Not recognised — unless this is the untitled preamble, which is the
      // overview table itself and is already read above, or a structural
      // container (masthead, form title, PHẦN…) whose content the labeled
      // readers already consumed.
      if (
        section.title &&
        !STRUCTURAL_HEADING.test(
          fold(section.title).replace(/^\s*\d+[.)]\s*/, ""),
        )
      ) {
        // A container heading ("PHẦN I: …") holds only structure — its table
        // rows are read above and its children are their own sections — so
        // reporting it as unrecognised content would be noise, not signal.
        const body = section.lines
          .map((line) => line.trim())
          .filter(
            (line) =>
              line && !/^\|.*\|$/.test(line) && !/^[-*_]{3,}$/.test(line),
          )
          .join("\n");
        if (body) unmappedSections.push({ title: section.title, body });
      }
      continue;
    }

    // A line that an override routes elsewhere belongs ONLY to the category it
    // was routed to — pushing it to the section's primary as well is what put
    // the housing answers into the meals category.
    const place = (value: string) => {
      const target = overrideFor(primary, value);
      push(target, value);
    };

    // A sub-heading that inherited its parent's category carries its own title
    // as content ("Lương cơ bản: 6.300.000 VNĐ / tháng" IS the salary fact).
    if (inherited[sectionIndex]) {
      const titleLine = section.title
        .replace(/^\s*\d+[.)]\s*/, "")
        .replace(/[:：]\s*$/, "")
        .trim();
      if (titleLine) place(titleLine);
    }

    // A heading with no Q&A structure is plain prose — keep all of it.
    if (answers.length === 0 && questions.length === 0) {
      for (const raw of section.lines) {
        const value = toPlainText(BULLET.exec(raw)?.[1] ?? raw.trim());
        if (value) place(value);
      }
      continue;
    }

    for (const answer of answers) place(answer);
  }

  // Plain label lines (and `Label: value` one-liners) fill whatever the
  // overview table did not state; the table stays canonical when both exist.
  const merged: Overview = {
    name: "",
    aliases: [],
    address: "",
    roles: [],
    summary: "",
    highlights: [],
    slug: "",
    mode: undefined,
    ...readLabeledFields(sections),
  };
  const preferOverview = <K extends keyof Overview>(field: K): void => {
    if (overviewFieldHasValue(overview[field])) merged[field] = overview[field];
  };
  preferOverview("name");
  preferOverview("aliases");
  preferOverview("address");
  preferOverview("roles");
  preferOverview("summary");
  preferOverview("highlights");
  preferOverview("slug");
  preferOverview("mode");

  // The brief's own structured header outranks every prose reading of the
  // same facts (see parseFrontmatter).
  const frontmatter = parseFrontmatter(rawText);
  for (const field of ["name", "address", "roles"] as const) {
    if (overviewFieldHasValue(frontmatter[field])) {
      merged[field] = frontmatter[field] as never;
    }
  }

  const categories: Partial<Record<ProjectKnowledgeCategory, string>> = {};
  for (const [category, lines] of bodies) {
    const body = dedupe(lines).join("\n");
    if (body.trim()) categories[category] = body;
  }
  // The FAQ transcript is assembled per section, so it never needs the dedupe
  // pass that the per-answer buckets do.
  if (faqTranscript.length > 0) {
    categories.faq = faqTranscript.join("\n\n---\n\n");
  }

  const filledCount = Object.keys(categories).length;

  const name = merged.name;
  const explicitSlug = merged.slug.trim();
  return {
    name,
    // An explicit `Mã dự án` is trusted verbatim only when it is already
    // slug-shaped; anything else is normalized like the derived slug is.
    slug: /^[a-z0-9-]+$/.test(explicitSlug)
      ? explicitSlug
      : name
        ? slugifyVietnamese(explicitSlug || name)
        : "",
    aliases: merged.aliases,
    summary: merged.summary,
    location: toShortLocation(merged.address),
    roles: merged.roles,
    highlights: merged.highlights,
    // The brief's own `Cách quản lý kiến thức` line outranks the section-count
    // heuristic; without one, the count decides as before.
    knowledgeMode:
      merged.mode ??
      (filledCount >= CATEGORY_MODE_THRESHOLD ? "RAG" : "DIRECT_CONTEXT"),
    categories,
    faqEntries,
    missingCategories: PROJECT_KNOWLEDGE_CATEGORIES.filter(
      (category) => !categories[category],
    ),
    unmappedSections,
    rawText,
  };
};

/** A bullet routed to two categories on purpose (a section's primary AND an
 *  override) lands twice in the same bucket; keep the first, drop the repeat. */
const dedupe = (lines: readonly string[]): string[] => {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const line of lines) {
    const key = line.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(key);
  }
  return result;
};
