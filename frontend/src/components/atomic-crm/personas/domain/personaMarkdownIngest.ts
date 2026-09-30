import {
  PERSONA_SECTIONS,
  stripTemplateHint,
  type PersonaSectionValues,
} from "./personaMarkdown";

/** A persona file is a document a person wrote; anything wildly past that is a
 *  mis-drop, and reading it would freeze the tab. Mirrors the brief guard in
 *  ProjectKnowledgePanel. */
export const MAX_PERSONA_FILE_BYTES = 2 * 1024 * 1024;

/** Clearly non-text shapes — binary documents, images, media, archives — by
 *  extension or by MIME type. A .md/.txt file, one with no extension, or one
 *  with an unknown extension is text the parser gets to judge. Same rules as
 *  the brief import, so a recruiter meets one text-file contract everywhere. */
const BINARY_NAME =
  /\.(pdf|docx?|xlsx?|pptx?|odt|ods|odp|png|jpe?g|gif|bmp|tiff?|ico|webp|mp3|mp4|mov|avi|wav|ogg|flac|zip|rar|7z|tar|gz|exe|dmg|apk|bin)$/i;
const BINARY_TYPE =
  /^(image|audio|video|font)\/|^application\/(pdf|zip|gzip|x-tar|x-rar-compression|x-7z-compressed|msword|vnd\.ms-|vnd\.openxmlformats-|vnd\.oasis\.)/i;

/** The file facts the upload guard judges, so tests need no real File. */
export interface PersonaUploadFileMeta {
  name: string;
  type: string;
  size: number;
}

/** Vietnamese rejection message for a non-text or oversized pick, or null when
 *  the file may be read. */
export const validatePersonaFileUpload = (
  file: PersonaUploadFileMeta,
): string | null => {
  if (BINARY_NAME.test(file.name) || BINARY_TYPE.test(file.type)) {
    return "Chỉ chấp nhận tệp văn bản.";
  }
  if (file.size > MAX_PERSONA_FILE_BYTES) {
    return "Tệp quá lớn. Hãy tải lên tệp dưới 2 MB.";
  }
  return null;
};

export interface PersonaMarkdownIngestResult {
  /** Extracted content keyed by PERSONA_SECTIONS order. A section with no
   *  material stays "" — never invented. */
  sections: PersonaSectionValues;
  /** Unrecognized top-level headings, as written in the file. */
  unknownHeadings: string[];
  /** Display labels of the seven sections that received no material. */
  emptySections: string[];
  /** Content under unrecognized headings (and any leading preamble), so a
   *  fill never silently drops recruiter content. */
  extraMarkdown: string;
}

const ATX_HEADING_LINE = /^#{1,6}\s+(.+?)\s*$/;
/** A whole line that is one bold span, optionally colon-suffixed: the plain
 *  text way people mark a section when writing by hand. */
const BOLD_HEADING_LINE = /^\*\*(.+?)\*\*:?\s*$/;

/** One comparison key: lowercase, separator- and punctuation-insensitive, free
 *  of a leading "1."/"1)" numbering, so "Vai trò của tôi:", "**1. VAI TRÒ CỦA
 *  TÔI**" and "vai-trò-của-tôi" all land on the same key. Vietnamese diacritics
 *  are letters and survive. */
const headingKey = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .replace(/\s+/g, " ")
    .replace(/^\d+\s*/, "");

/** Candidate keys per section: the numbered title and every known alias,
 *  compared through the same tolerant key. */
const PERSONA_SECTION_KEYS = PERSONA_SECTIONS.map(
  (section) =>
    new Set(
      [section.title, ...section.aliases].map((candidate) =>
        headingKey(candidate),
      ),
    ),
);

const sectionDisplayLabel = (title: string) => title.replace(/^\d+\.\s*/, "");

/** The heading text of a top-level heading line (ATX any level, or a bold
 *  line), or null when the line is content. */
const matchHeadingLine = (line: string): string | null => {
  const trimmed = line.trim();
  const atx = ATX_HEADING_LINE.exec(trimmed);
  if (atx) return atx[1] ?? null;
  const bold = BOLD_HEADING_LINE.exec(trimmed);
  if (bold) return bold[1] ?? null;
  return null;
};

/**
 * Deterministic ingestion of a recruiter-authored persona file: every heading
 * that tolerantly matches one of the seven Prompt Agent sections claims the
 * lines under it up to the next heading; anything else is reported, never
 * squeezed into a section. Duplicate section headings append — a fill never
 * drops content a person wrote.
 */
export const parsePersonaMarkdownFile = (
  text: string,
): PersonaMarkdownIngestResult => {
  const sections: PersonaSectionValues = PERSONA_SECTIONS.map(() => "");
  const unknownHeadings: string[] = [];
  const extraBlocks: string[] = [];

  const blocks: { heading: string | null; lines: string[] }[] = [];
  let current: { heading: string | null; lines: string[] } | null = null;
  for (const line of text.split(/\r\n|\r|\n/)) {
    const heading = matchHeadingLine(line);
    if (heading !== null) {
      current = { heading, lines: [] };
      blocks.push(current);
      continue;
    }
    if (!current) {
      current = { heading: null, lines: [] };
      blocks.push(current);
    }
    current.lines.push(line);
  }

  for (const block of blocks) {
    const content = block.lines.join("\n").trim();
    if (block.heading === null) {
      // Lines before the first heading carry no section claim; keep them.
      if (content) extraBlocks.push(content);
      continue;
    }
    const key = headingKey(block.heading);
    const sectionIndex = PERSONA_SECTION_KEYS.findIndex((keys) =>
      keys.has(key),
    );
    if (sectionIndex < 0) {
      unknownHeadings.push(block.heading.trim());
      // Re-emit at the same `###` level the editor's own parse and compose
      // round-trip, so the kept block stays readable in the extra field.
      extraBlocks.push(
        content
          ? `### ${block.heading.trim()}\n${content}`
          : `### ${block.heading.trim()}`,
      );
      continue;
    }
    if (content) {
      sections[sectionIndex] = sections[sectionIndex]
        ? `${sections[sectionIndex]}\n\n${content}`
        : content;
    }
  }

  // The shipped template carries its hint in parentheses under each heading;
  // a re-uploaded untouched template has no material, so strip it like the
  // editor's own parse does.
  const material = sections.map((content, index) =>
    stripTemplateHint(content, PERSONA_SECTIONS[index].hint),
  );
  const emptySections = PERSONA_SECTIONS.filter(
    (_, index) => !material[index].trim(),
  ).map((section) => sectionDisplayLabel(section.title));

  return {
    sections: material,
    unknownHeadings,
    emptySections,
    extraMarkdown: extraBlocks.join("\n\n"),
  };
};
