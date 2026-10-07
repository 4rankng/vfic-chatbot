import { useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";

import { Clipboard } from "@untitledui/icons";

import { Button } from "@/components/base/buttons/button";
import {
  parseProjectBrief,
  type ProjectBrief,
} from "../domain/project-brief-ingest";
import { PasteTextArea } from "./PasteTextArea";
import {
  PROJECT_TEXT_FILE_ACCEPT,
  readProjectBriefPreview,
} from "../project-knowledge-service";

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
  /** Reports the browser read so the parent's progress timeline covers it. */
  onReadingChange?: (reading: boolean) => void;
};

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
  onReadingChange,
}: Props) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [error, setError] = useState("");

  const read = async (file?: File) => {
    if (!file) return;
    setError("");
    setReading(true);
    onReadingChange?.(true);
    try {
      const text = await readProjectBriefPreview(file);
      // Preview can be empty/unsupported; the original file still goes to the
      // authoritative worker and is never replaced with a partial browser plan.
      const parsed = parseProjectBrief(text ?? "");
      onImported(parsed, file.name, file);
    } catch (readError) {
      setError((readError as Error).message);
    } finally {
      setReading(false);
      onReadingChange?.(false);
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
        <Button
          type="button"
          color="secondary"
          size="sm"
          className="uu-scope"
          iconLeading={Clipboard}
          isDisabled={reading || busy}
          aria-expanded={pasteOpen}
          onClick={() => setPasteOpen((open) => !open)}
        >
          Dán văn bản
        </Button>
        <input
          ref={inputRef}
          type="file"
          hidden
          accept={PROJECT_TEXT_FILE_ACCEPT}
          className="sr-only"
          aria-label="Chọn tệp phiếu thông tin dự án"
          disabled={reading || busy}
          onChange={(event) => void read(event.target.files?.[0])}
        />
      </div>
      <p className="text-helper text-muted-foreground">
        Một tệp văn bản (.txt, .md, .csv…) hoặc tệp Word (.docx), tối đa 20 MB —
        hoặc dán trực tiếp nội dung. Không cần theo mẫu. Hệ thống phân loại nội
        dung vào 12 danh mục. Kiểm tra kết quả trước khi bật tuyển dụng.
      </p>
      {pasteOpen && !reading && !busy ? (
        <PasteTextArea
          confirmLabel="Nạp văn bản đã dán"
          onSubmit={(file) => {
            setPasteOpen(false);
            void read(file);
          }}
          onClose={() => setPasteOpen(false)}
        />
      ) : null}
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
  return (
    <div
      className="project-brief-import-summary grid gap-1.5"
      role="status"
      data-testid="project-brief-summary"
    >
      <p className="flex items-center gap-2 text-helper text-foreground">
        <FileText className="size-4 shrink-0" aria-hidden="true" />
        <span className="project-brief-summary-copy">
          Đã chọn <strong>{filename}</strong>. Kết quả phân loại được xác nhận
          sau khi hệ thống xử lý toàn bộ tệp.
        </span>
      </p>
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
