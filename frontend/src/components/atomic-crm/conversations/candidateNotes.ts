const NOTE_PREFIX = /^(?:(?:[-*\u2022\u2013\u2014])|(?:\d+[.)]))\s*/u;
const TRAILING_PUNCTUATION = /[.!?;:,]+$/u;

const noteIdentity = (note: string) =>
  note
    .toLocaleLowerCase("vi-VN")
    .replace(TRAILING_PUNCTUATION, "")
    .replace(/\s+/gu, " ")
    .trim();

export const formatCandidateNotes = (
  notes: string | null | undefined,
): string[] => {
  if (!notes) return [];

  const seen = new Set<string>();

  return notes.split(/\r?\n/u).flatMap((line) => {
    const note = line
      .trim()
      .replace(NOTE_PREFIX, "")
      .replace(/\s+/gu, " ")
      .trim();
    const identity = noteIdentity(note);

    if (!identity || seen.has(identity)) return [];
    seen.add(identity);
    return [note];
  });
};
