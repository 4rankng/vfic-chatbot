import { useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  parseProjectBrief,
  type ProjectBrief,
} from "../domain/project-brief-ingest";
import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";

type Props = {
  /** Fired with the parsed brief; the form owner applies it to the fields. */
  onImported: (brief: ProjectBrief, filename: string) => void;
  /** What the last import actually produced, so the recruiter reviews rather
   *  than trusts. `null` until a file has been read. */
  brief: ProjectBrief | null;
  filename: string;
};

/** Guard rail, not a parser: a brief is a document a person typed, so anything
 *  wildly past a brief's size is a mis-drop, and reading it would freeze the
 *  tab. `.md`/`.txt` is what the console already accepts elsewhere. */
const MAX_BYTES = 2 * 1024 * 1024;

/**
 * ProjectBriefImport — the recruiter's "I already wrote it down" path.
 *
 * Uploads ONE project brief, reads it in the browser, and hands the parsed
 * result up. Nothing is saved here: the form still shows every value and the
 * recruiter still presses `Tạo dự án`. The import only removes the retyping.
 */
export const ProjectBriefImport = ({ onImported, brief, filename }: Props) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const read = async (file?: File) => {
    if (!file) return;
    setError("");
    if (file.size > MAX_BYTES) {
      setError("Tệp quá lớn. Hãy tải lên phiếu thông tin dưới 2 MB.");
      return;
    }
    setBusy(true);
    try {
      const text = await file.text();
      const parsed = parseProjectBrief(text);
      if (!parsed.name && !parsed.categories.jobs) {
        setError(
          "Không đọc được nội dung dự án từ tệp này. Hãy kiểm tra lại tệp .md hoặc .txt.",
        );
        return;
      }
      onImported(parsed, file.name);
    } catch {
      setError("Không đọc được tệp. Hãy thử lại với tệp .md hoặc .txt.");
    } finally {
      setBusy(false);
      // Allow re-picking the same file after an edit.
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <section
      className="project-brief-import grid gap-2"
      aria-labelledby="project-brief-import-title"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2
          id="project-brief-import-title"
          className="text-helper font-medium text-foreground"
        >
          Đã có sẵn phiếu thông tin?
        </h2>
        <Button type="button" variant="outline" size="sm" asChild>
          <label>
            <Upload className="size-4" aria-hidden="true" />
            {busy ? "Đang đọc…" : "Nhập từ file"}
            <input
              ref={inputRef}
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              className="sr-only"
              aria-label="Chọn tệp phiếu thông tin dự án"
              disabled={busy}
              onChange={(event) => void read(event.target.files?.[0])}
            />
          </label>
        </Button>
      </div>
      <p className="text-helper text-muted-foreground">
        Tải lên tệp .md hoặc .txt của phiếu thu thập thông tin. Hệ thống điền
        sẵn tên, mã, tên gọi khác, tóm tắt, địa điểm, vị trí, điểm nổi bật và
        các phần kiến thức — bạn vẫn xem lại trước khi lưu.
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
        <span className="truncate">
          Đã đọc <strong>{filename}</strong> — điền sẵn {filled.length}/12 phần
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
