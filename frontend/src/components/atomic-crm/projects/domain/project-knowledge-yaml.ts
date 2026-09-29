import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  type ProjectKnowledgeCategory,
} from "./project-knowledge-policy";
import type {
  ProjectBrief,
  ProjectBriefFaqEntry,
} from "./project-brief-ingest";

/**
 * project-knowledge-yaml — the one place a parsed brief becomes the YAML the
 * knowledge API accepts.
 *
 * The RAG categories are NOT free text: `PUT /categories/{key}` rejects
 * anything but `.yaml`/`.yml`, and each category has its own typed schema. A
 * brief carries two categories in a form the schema actually accepts:
 *
 * - `jobs` — every row is a role the recruiter's own overview listed, and the
 *   row carries ONLY the fields the brief stated (title, plus the project
 *   location when the brief gives one). `vacancies` is deliberately never
 *   written: the recruiter does not manage headcount, and a number invented
 *   here would be quoted back to a candidate as fact.
 * - `faq` — question and answer verbatim from the file.
 *
 * Every other category stays empty on purpose. A typed field the brief never
 * stated (an employment type, a phone number, a benefit) has no honest value,
 * and inventing one puts a fabrication into the knowledge the assistant answers
 * real candidates with. The plan names them in `needsHuman` instead, so the
 * recruiter sees what still needs a person rather than meeting a silent gap.
 */

/** A YAML double-quoted scalar: escape the backslash, the quote and the
 *  newline, and refuse anything else that would break the YAML. */
const yamlString = (value: string): string => {
  const escaped = value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\r?\n/g, " ")
    // A raw control character is illegal inside a YAML quoted scalar.
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  return `"${escaped}"`;
};

/** A stable, ASCII, unique-enough id — same rule the project's own slugs use. */
const toEntryId = (value: string, index: number): string => {
  const base = value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/g, "");
  return base || `cau-hoi-${index + 1}`;
};

/** The `faq` category document: every question the brief paired with an answer,
 *  with the fields the template declares and the brief does not supply left as
 *  empty lists rather than guessed at. */
export const buildFaqYaml = (
  entries: readonly ProjectBriefFaqEntry[],
): string => {
  const lines = ['schema_version: "1.0"', "category: faq"];
  if (entries.length === 0) {
    lines.push("faq: []");
    return `${lines.join("\n")}\n`;
  }
  lines.push("faq:");
  const used = new Map<string, number>();
  entries.forEach((entry, index) => {
    // Two questions can fold to the same slug; the suffix keeps ids unique
    // rather than letting the API reject the whole submission.
    const base = toEntryId(entry.question, index);
    const seen = used.get(base) ?? 0;
    used.set(base, seen + 1);
    const id = seen === 0 ? base : `${base}-${seen + 1}`;
    lines.push(
      `  - id: ${id}`,
      `    question: ${yamlString(entry.question)}`,
      `    answer: ${yamlString(entry.answer)}`,
      "    tags: []",
      "    question_variants: []",
      "    required_terms: []",
      "    forbidden_terms: []",
    );
  });
  return `${lines.join("\n")}\n`;
};

/** The `jobs` category document: one row per role the brief's overview listed.
 *
 *  `vacancies` is intentionally absent. The recruiter does not manage headcount
 *  for these roles, and the schema makes the field optional precisely so an
 *  unknown count stays unknown instead of becoming a confident wrong number in
 *  an answer a candidate will read. */
export const buildJobsYaml = (
  roles: readonly string[],
  location = "",
): string => {
  const lines = ['schema_version: "1.0"', "category: jobs"];
  const cleaned = roles.map((role) => role.trim()).filter(Boolean);
  if (cleaned.length === 0) {
    lines.push("jobs: []");
    return `${lines.join("\n")}\n`;
  }
  lines.push("jobs:");
  const used = new Map<string, number>();
  cleaned.forEach((role, index) => {
    // Two roles can fold to the same slug ("Nhân viên kho" / "Nhan vien kho");
    // the suffix keeps ids unique rather than letting the API reject the batch.
    const base = toEntryId(role, index);
    const seen = used.get(base) ?? 0;
    used.set(base, seen + 1);
    const id = seen === 0 ? base : `${base}-${seen + 1}`;
    lines.push(`  - id: ${id}`, `    title: ${yamlString(role)}`);
    // The project address genuinely covers every role in it, so carrying it
    // across is transcription rather than invention.
    if (location) lines.push(`    location: ${yamlString(location)}`);
    lines.push("    aliases: []", "    keywords: []");
  });
  return `${lines.join("\n")}\n`;
};

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

export const planBriefKnowledge = (brief: ProjectBrief): BriefKnowledgePlan => {
  const writes: {
    key: ProjectKnowledgeCategory;
    filename: string;
    content: string;
  }[] = [];

  // `jobs` goes FIRST and always. Every other category's rows may reference
  // `job_ids`, and the API rejects a write whose references do not resolve
  // against the jobs that are active at that moment — so activating jobs first
  // is what makes the rest of the batch writable. It is also the category
  // activation itself requires, so a brief with no role at all has nothing to
  // activate and the form asks the recruiter for one title instead.
  if (brief.roles.length > 0) {
    writes.push({
      key: "jobs",
      filename: "jobs.yaml",
      content: buildJobsYaml(brief.roles, brief.location),
    });
  }

  if (brief.faqEntries.length > 0) {
    writes.push({
      key: "faq",
      filename: "faq.yaml",
      content: buildFaqYaml(brief.faqEntries),
    });
  }

  const written = new Set(writes.map((write) => write.key));
  return {
    writes,
    // Every category this batch did NOT write. Computed from the full list
    // rather than a fixed remainder so a category that is skipped because the
    // brief had nothing to say about it — `jobs` above all — is still named as
    // needing a person instead of vanishing from the report.
    needsHuman: PROJECT_KNOWLEDGE_CATEGORIES.filter((key) => !written.has(key)),
  };
};
