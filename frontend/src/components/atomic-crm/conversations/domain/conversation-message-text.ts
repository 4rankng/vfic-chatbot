// Text layout rules for a message bubble.
//
// Pure: no React, no IO. Blank lines become vertical spacers and an over-long
// line is chunked (preferring a sentence boundary) so a wall of text stays
// readable inside a bubble instead of stretching it.

/** Longest run of characters one rendered text block may hold. */
export const MESSAGE_TEXT_CHUNK_CHARS = 320;

export const splitLongTextLine = (line: string) => {
  if (line.length <= MESSAGE_TEXT_CHUNK_CHARS) return [line];

  const chunks: string[] = [];
  let remaining = line;
  while (remaining.length > MESSAGE_TEXT_CHUNK_CHARS) {
    const windowText = remaining.slice(0, MESSAGE_TEXT_CHUNK_CHARS);
    const sentenceBreak = Math.max(
      windowText.lastIndexOf(". "),
      windowText.lastIndexOf("! "),
      windowText.lastIndexOf("? "),
      windowText.lastIndexOf("; "),
      windowText.lastIndexOf(", "),
    );
    const splitAt =
      sentenceBreak > MESSAGE_TEXT_CHUNK_CHARS * 0.55
        ? sentenceBreak + 1
        : MESSAGE_TEXT_CHUNK_CHARS;
    chunks.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
};

export const splitMessageTextBlocks = (content: string) => {
  const blocks = content
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .flatMap((line) => {
      const trimmed = line.trim();
      return trimmed ? splitLongTextLine(trimmed) : [""];
    });

  return blocks.length > 0 ? blocks : [""];
};
