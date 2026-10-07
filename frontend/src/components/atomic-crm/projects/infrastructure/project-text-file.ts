/** The backend owns file decoding and category extraction. Browser reading is
 * only an optional, bounded preview; a failed preview must keep the source intact. */
export const PROJECT_TEXT_FILE_ACCEPT =
  ".txt,.text,.md,.markdown,.csv,.tsv,.log,.json,.rst,.docx,text/plain,text/markdown,text/csv,text/tab-separated-values,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const MAX_SOURCE_BYTES = 20 * 1024 * 1024;
const MAX_PREVIEW_BYTES = 2 * 1024 * 1024;
// .docx is a supported knowledge source (the backend parses the OOXML
// container), so it is absent here; legacy .doc, .xlsx and everything else
// binary stay rejected client-side.
const BINARY_NAME =
  /\.(pdf|doc|xlsx|pptx?|odt|ods|odp|png|jpe?g|gif|bmp|tiff?|ico|webp|mp3|mp4|mov|avi|wav|ogg|flac|zip|rar|7z|tar|gz|exe|dmg|apk|bin|ya?ml)$/i;
const BINARY_TYPE =
  /^(image|audio|video|font)\/|^application\/(pdf|zip|gzip|x-tar|x-rar-compression|x-7z-compressed|msword|vnd\.ms-|vnd\.openxmlformats-(?!officedocument\.wordprocessingml\.document)|vnd\.oasis\.|yaml)|^text\/yaml/i;

export const assertProjectTextFile = (file: File): void => {
  if (BINARY_NAME.test(file.name) || BINARY_TYPE.test(file.type))
    throw new Error(
      "Chỉ chấp nhận tệp văn bản (.txt, .md, .csv, .json…) hoặc tệp Word (.docx).",
    );
  if (file.size > MAX_SOURCE_BYTES)
    throw new Error("Tệp quá lớn. Hãy tải lên tệp dưới 20 MB.");
  if (file.size === 0) throw new Error("Tệp chưa có nội dung văn bản.");
};

/** The stored filename a pasted source carries through the ingest chain. */
export const PASTED_TEXT_FILENAME = "van-ban-dan.md";

/** Wrap pasted text as the markdown source file the brief chain already
 *  accepts, so a paste rides the exact same upload-and-classify path as a
 *  picked file — the backend stays the single authority on content. */
export const pastedTextFile = (text: string): File =>
  new File([text], PASTED_TEXT_FILENAME, { type: "text/markdown" });

export const readProjectBriefPreview = async (
  file: File,
): Promise<string | null> => {
  assertProjectTextFile(file);
  // A DOCX is a zip container: there is no browser text preview to have, and
  // decoding its bytes as text would only see mojibake. The backend parses
  // the original through the OOXML branch instead.
  if (/\.docx$/i.test(file.name)) return null;
  if (file.size > MAX_PREVIEW_BYTES) return null;

  const bytes = new Uint8Array(await file.arrayBuffer());
  // Web TextDecoder does not support UTF-32. The backend does, so skip preview.
  if (
    (bytes[0] === 0xff &&
      bytes[1] === 0xfe &&
      bytes[2] === 0 &&
      bytes[3] === 0) ||
    (bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 0xfe && bytes[3] === 0xff)
  )
    return null;
  const declared = /charset\s*=\s*["']?([^;"'\s]+)/i.exec(file.type)?.[1];
  const encoding =
    bytes[0] === 0xff && bytes[1] === 0xfe
      ? "utf-16le"
      : bytes[0] === 0xfe && bytes[1] === 0xff
        ? "utf-16be"
        : bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf
          ? "utf-8"
          : (declared ?? "utf-8");
  try {
    const text = new TextDecoder(encoding, { fatal: true }).decode(bytes);
    return /[^\P{Cc}\t\n\r\f\u0085]/u.test(text) ? null : text;
  } catch {
    return null;
  }
};
