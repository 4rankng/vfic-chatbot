import { useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import {
  parseProjectBrief,
  type ProjectBrief,
} from "../domain/project-brief-ingest";
import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";
import { planBriefKnowledge } from "../domain/project-knowledge-markdown";

type Props = {
  /** Fired with the parsed brief AND the file itself. The parent fills the
   *  form from `brief` and hands `file` to the ingest pipeline — the parse
   *  proposes, the pipeline writes, and the recruiter still reviews. */
  onImported: (brief: ProjectBrief, filename: string, file: File) => void;
  /** What the last import actually produced, so the recruiter reviews rather
   *  than trusts. `null` until a file has been read. */
  brief: ProjectBrief | null;
  filename: string;
  /** True while the parent is creating the draft and running the pipeline. */
  busy?: boolean;
};

/** Guard rail, not a parser: a brief is a document a person typed, so anything
 *  wildly past a brief's size is a mis-drop, and reading it would freeze the
 *  tab. Any text shape is accepted; markdown is the recommended format. */
const MAX_BYTES = 2 * 1024 * 1024;

/** Clearly non-text shapes — binary documents, images, media, archives — by
 *  extension or by MIME type. A .md/.txt file, one with no extension, or one
 *  with an unknown extension is text the parser gets to judge. */
const BINARY_NAME =
  /\.(pdf|docx?|xlsx?|pptx?|odt|ods|odp|png|jpe?g|gif|bmp|tiff?|ico|webp|mp3|mp4|mov|avi|wav|ogg|flac|zip|rar|7z|tar|gz|exe|dmg|apk|bin)$/i;
const BINARY_TYPE =
  /^(image|audio|video|font)\/|^application\/(pdf|zip|gzip|x-tar|x-rar-compression|x-7z-compressed|msword|vnd\.ms-|vnd\.openxmlformats-|vnd\.oasis\.)/i;

/**
 * ProjectBriefImport — the recruiter's "I already wrote it down" path.
 *
 * Uploads ONE project brief, reads it in the browser, and hands both the parsed
 * result and the file up. Picking the file is what STARTS the pipeline: the
 * parent creates the draft project and writes its knowledge categories, so the
 * recruiter never waits on a save to learn whether the file was usable. The
 * `Tạo dự án` button is still theirs, and it is still the thing that makes the
 * project visible.
 */
export const ProjectBriefImport = ({
  onImported,
  brief,
  filename,
  busy = false,
}: Props) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");

  const read = async (file?: File) => {
    if (!file) return;
    setError("");
    // Text files only, by product ruling: every text shape is parsed —
    // markdown is just the recommended format — while a clearly binary pick
    // (pdf, image, office) is rejected before any read.
    if (BINARY_NAME.test(file.name) || BINARY_TYPE.test(file.type)) {
      setError("Chỉ chấp nhận tệp văn bản.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Tệp quá lớn. Hãy tải lên phiếu thông tin dưới 2 MB.");
      return;
    }
    setReading(true);
    try {
      const text = await file.text();
      const parsed = parseProjectBrief(text);
      if (!parsed.name && planBriefKnowledge(parsed).writes.length === 0) {
        setError(
          "Không đọc được nội dung dự án từ tệp này. Hãy kiểm tra lại tệp văn bản.",
        );
        return;
      }
      onImported(parsed, file.name, file);
    } catch {
      setError("Không đọc được tệp. Hãy thử lại với tệp văn bản.");
    } finally {
      setReading(false);
      // Allow re-picking the same file after an edit.
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <section
      className="project-brief-import grid gap-2"
      aria-labelledby="project-brief-import-title"
    >
      <div className="project-brief-import-heading">
        <h2
          id="project-brief-import-title"
          className="text-helper font-medium text-foreground"
        >
          Thông tin dự án
        </h2>
        {/*
          The file affordance is a Untitled UI button plus a visually hidden
          input, not a `<label>` wrapped in a button: the library's `Button` is
          a React Aria button with no `asChild`, and the picker is opened by
          `click()` on the input so the control's role, name and disabled state
          stay the button's.
        */}
        <Button
          type="button"
          color="secondary"
          size="sm"
          className="uu-scope"
          iconLeading={Upload}
          isLoading={reading || busy}
          showTextWhileLoading
          isDisabled={reading || busy}
          onClick={() => inputRef.current?.click()}
        >
          {reading ? "Đang đọc tệp…" : busy ? "Đang nạp…" : "Nhập từ tệp"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          hidden
          accept=".md,.txt,.markdown,text/plain,text/markdown"
          className="sr-only"
          aria-label="Chọn tệp phiếu thông tin dự án"
          disabled={reading || busy}
          onChange={(event) => void read(event.target.files?.[0])}
        />
      </div>
      <p className="text-helper text-muted-foreground">
        Một tệp .txt hoặc .md, tối đa 2 MB. Hệ thống tạo bản nháp và nạp kiến
        thức từ nội dung trong tệp. Kiểm tra kết quả trước khi bật tuyển dụng.
      </p>
      {error ? (
        <p role="alert" className="text-helper text-destructive">
          {error}
        </p>
      ) : null}
      {brief ? <ImportSummary brief={brief} filename={filename} /> : null}
    </section>
  );
};

const ImportSummary = ({
  brief,
  filename,
}: {
  brief: ProjectBrief;
  filename: string;
}) => {
  const filled = Object.keys(
    brief.categories,
  ) as (keyof typeof brief.categories)[];
  const missing = brief.missingCategories;
  return (
    <div
      className="project-brief-import-summary grid gap-1.5"
      role="status"
      data-testid="project-brief-summary"
    >
      <p className="flex items-center gap-2 text-helper text-foreground">
        <FileText className="size-4 shrink-0" aria-hidden="true" />
        <span className="project-brief-summary-copy">
          Đã đọc <strong>{filename}</strong> — nhận diện {filled.length}/12 phần
          kiến thức
          {brief.faqEntries.length > 0
            ? ` và ${brief.faqEntries.length} câu hỏi thường gặp`
            : ""}
          .
        </span>
      </p>
      {missing.length > 0 ? (
        <p className="text-helper text-muted-foreground">
          Chưa có trong tệp (bạn có thể thêm sau):{" "}
          {missing
            .map((key) => PROJECT_KNOWLEDGE_CATEGORY_LABELS[key])
            .join(", ")}
          .
        </p>
      ) : null}
      {brief.unmappedSections.length > 0 ? (
        <details className="text-helper">
          <summary className="cursor-pointer text-muted-foreground">
            {brief.unmappedSections.length} phần trong tệp chưa nhận diện được —
            xem để không bỏ sót
          </summary>
          <ul className="mt-1 grid gap-1">
            {brief.unmappedSections.map((section) => (
              <li key={section.title} className="text-muted-foreground">
                <strong className="text-foreground">{section.title}</strong>
                <pre className="mt-0.5 whitespace-pre-wrap font-sans text-helper">
                  {section.body}
                </pre>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
};
