import type { ProjectKnowledgeCategory } from "./project-knowledge-policy";
import type { ProjectBriefFaqEntry } from "./project-brief-ingest";

/**
 * project-knowledge-yaml — the one place a parsed brief becomes the YAML the
 * knowledge API accepts.
 *
 * The RAG categories are NOT free text: `PUT /categories/{key}` rejects
 * anything but `.yaml`/`.yml`, and each category has its own typed schema (the
 * `jobs` template wants vacancies and employment_type; `contacts` wants a
 * phone). A brief states none of those, so this module deliberately builds
 * YAML for the ONE category whose fields the brief actually carries —
 * `faq`, whose `question` and `answer` are verbatim from the file.
 *
 * The other eleven stay empty on purpose. Inventing a vacancy count or an
 * employment type would put invented facts into the knowledge the assistant
 * answers real candidates with; leaving them empty keeps the recruiter in
 * control of every field the brief did not state.
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

/** What a brief can seed without inventing anything, and what it cannot. */
export type BriefKnowledgePlan = Readonly<{
  /** Categories to write, in the order they should be written. */
  writes: readonly Readonly<{
    key: ProjectKnowledgeCategory;
    filename: string;
    content: string;
  }>[];
  /** Categories the brief covers in prose but whose typed fields a human must
   *  still supply — named so the recruiter is told, not left guessing. */
  needsHuman: readonly ProjectKnowledgeCategory[];
}>;

export const planBriefKnowledge = (
  entries: readonly ProjectBriefFaqEntry[],
): BriefKnowledgePlan => {
  // Only the FAQ: its question and answer are the one pair a prose brief
  // states in full. A `.md` body for any other category is rejected outright.
  const writes =
    entries.length > 0
      ? [
          {
            key: "faq" as const,
            filename: "faq.yaml",
            content: buildFaqYaml(entries),
          },
        ]
      : [];
  return {
    writes,
    // The eleven categories the brief does NOT fill: each wants typed fields
    // (vacancies, employment type, a phone) that a prose brief never states.
    needsHuman: [
      "jobs",
      "compensation",
      "requirements",
      "work_schedules",
      "benefits",
      "accommodation",
      "meals",
      "transportation",
      "insurance",
      "application",
      "contacts",
    ],
  };
};
