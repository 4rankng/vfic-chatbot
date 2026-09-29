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

// ── section classification ─────────────────────────────────────────────────

/** Heading title → the category it owns. Matched on folded text so marks do
 *  not decide. `null` means "this brief has a section I do not recognise",
 *  which is surfaced rather than guessed at. */
const CATEGORY_BY_HEADING: readonly (readonly [
  RegExp,
  ProjectKnowledgeCategory,
])[] = [
  [/vi tri (tuyen|tuyen dung)|cong viec cu the|dinh nghe/, "jobs"],
  [/yeu cau|doi voi ung vien|ho so giay to/, "requirements"],
  [/tien luong|phu cap|tang ca|thu nhap/, "compensation"],
  [/ca lam viec|lich kip|lam viec may gio/, "work_schedules"],
  [/an uong|cho o|ky tuc|thue tro/, "meals"],
  [/xe dua don|tuyen xe dua/, "transportation"],
  [/bao hiem|kham suc khoe/, "insurance"],
  [/moi truong lam viec|bao ho lao dong|phuc loi/, "benefits"],
  [/quy trinh phong van|ho so nhan viec|ung tuyen/, "application"],
  [/dau moi lien he|diem lien he|thu muc/, "contacts"],
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
  // "Môi trường làm việc & Bảo hộ lao động": the statutory schemes are insurance.
  ["benefits", /bao hiem xa hoi|bhxh|bhyt|bhtn|bao hiem tai nan/, "insurance"],
] as const;

// ── markdown walking ───────────────────────────────────────────────────────

const HEADING = /^#{1,6}\s+(.*)$/;
const BULLET = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/;

/** A heading plus every line under it, in document order. */
type BriefSection = { title: string; lines: string[] };

const splitSections = (text: string): BriefSection[] => {
  // Content before the first heading is a section too: a brief that is one
  // bare table carries no heading at all, and dropping the preamble would
  // silently lose every discovery field.
  const sections: BriefSection[] = [{ title: "", lines: [] }];
  let current = sections[0];
  for (const line of text.split(/\r?\n/)) {
    const heading = HEADING.exec(line);
    if (heading) {
      current = { title: toPlainText(heading[1]), lines: [] };
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
  [/^ten (viet tat|thuong goi|goi khac)/, "aliases"],
  [/^(dia chi noi lam viec|dia diem noi lam viec|dia diem)/, "address"],
  [/^vi tri tuyen dung/, "roles"],
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
 *  "Tên dự án phải dễ nhớ" from posing as a label. */
const bareLabelField = (line: string): BriefField | null => {
  const plain = toPlainText(line).trim();
  if (!plain || plain.length > 60) return null;
  const stripped = plain
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/[:：*\s]+$/, "")
    .trim();
  if (!stripped) return null;
  const folded = fold(stripped);
  if (!folded) return null;
  for (const [pattern, field] of OVERVIEW_LABELS) {
    if (pattern.test(folded) && folded.replace(pattern, "").trim() === "") {
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
 *  merged in later and win, so `??=` never fights the canonical reader. */
const applyLabeledValue = (
  into: Partial<Overview>,
  field: BriefField,
  rawValue: string,
): void => {
  const value = toPlainText(rawValue.split("\n")[0]).trim();
  if (!value) return;
  if (field === "name") {
    into.name ??= value;
    return;
  }
  if (field === "slug") {
    into.slug ??= value;
    return;
  }
  if (field === "summary") {
    into.summary ??= value;
    return;
  }
  if (field === "address") {
    into.address ??= value;
    return;
  }
  if (field === "aliases") into.aliases ??= toAliasList(value);
  if (field === "roles") into.roles ??= toRoleList(value);
  if (field === "highlights") into.highlights ??= toList(value);
  if (field === "mode") into.mode ??= modeFromText(value);
};

/** The value a bare label owns: the next content line within a short look
 *  ahead, unless it is itself a label or a table row. */
const labelValueLine = (
  lines: readonly string[],
  start: number,
): { value: string; index: number } | null => {
  for (let i = start; i < Math.min(start + 3, lines.length); i += 1) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (/^\s*\|/.test(line)) return null;
    if (inlineLabeledField(line) || bareLabelField(line)) return null;
    return { value: line.trim(), index: i };
  }
  return null;
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
        applyLabeledValue(found, inline.field, inline.value);
        continue;
      }
      const bare = bareLabelField(line);
      if (!bare) continue;
      const value = labelValueLine(lines, i + 1);
      if (!value) continue;
      applyLabeledValue(found, bare, value.value);
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

const QUESTION_MARKER = /cau hoi thuong gap|^\s*questions?\b/i;
const ANSWER_MARKER = /thong tin phan hoi|^\s*answers?\b/i;

/** One Q&A section split into its question list, its answer list and the
 *  plain body that goes into the category. */
const readSectionBody = (section: BriefSection) => {
  const questions: string[] = [];
  const answers: string[] = [];
  let bucket: "question" | "answer" | null = null;
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
    const foldedContent = fold(content);
    if (QUESTION_MARKER.test(foldedContent)) {
      bucket = "question";
      continue;
    }
    if (ANSWER_MARKER.test(foldedContent)) {
      bucket = "answer";
      continue;
    }
    const value = toPlainText(content);
    if (!value) continue;
    if (bucket === "question") questions.push(value);
    else if (bucket === "answer") answers.push(value);
  }
  return { questions, answers };
};

const categoryForHeading = (title: string): ProjectKnowledgeCategory | null => {
  const folded = fold(title);
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

export const parseProjectBrief = (text: string): ProjectBrief => {
  const rawText = text ?? "";
  if (!rawText.trim()) return EMPTY_PROJECT_BRIEF;

  const sections = splitSections(rawText);
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

  for (const section of sections) {
    const heading = section.title.replace(/^\s*\d+[.)]\s*/, "").trim();
    const primary =
      categoryForHeading(section.title) ?? categoryForHeading(heading);
    const { questions, answers } = readSectionBody(section);

    // The Q&A transcript is the `faq` category's body whether or not the
    // section's own heading mapped anywhere.
    if (questions.length > 0 || answers.length > 0) {
      const transcript: string[] = [`## ${section.title}`];
      const paired =
        questions.length > 0 && questions.length === answers.length;
      const rows = paired
        ? questions.map((question, index) => ({
            question,
            answer: answers[index],
          }))
        : questions.map((question, index) => ({
            question,
            answer: answers[index] ?? answers.join("\n"),
          }));
      for (const row of rows) {
        transcript.push(`**${row.question}**`, row.answer);
        faqEntries.push(row);
      }
      if (answers.length > questions.length) {
        // Answer lines beyond the paired ones still belong somewhere.
        transcript.push(...answers.slice(rows.length));
      }
      faqTranscript.push(transcript.join("\n\n"));
      push("faq", transcript.join("\n\n"));
    }

    if (!primary) {
      // Not recognised — unless this is the untitled preamble, which is the
      // overview table itself and is already read above.
      if (section.title) {
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
