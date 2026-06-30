import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useNotify } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";
import { importPersona } from "@/lib/vfic/knowledgeService";

const PERSONA_SECTIONS = [
  {
    title: "1. Vai trò của tôi",
    hint: "Mô tả agent là ai, phục vụ mục đích gì, và nên tạo cảm giác như thế nào.",
    aliases: ["Vai trò của tôi là gì?", "1. Vai trò của tôi (What's my job?)"],
  },
  {
    title: "2. Ai sẽ cần sự hỗ trợ của tôi?",
    hint: "Mô tả nhóm người dùng chính, bối cảnh, nhu cầu và mức độ quen công nghệ.",
    aliases: [
      "Ai cần tôi giúp?",
      "2. Ai sẽ cần sự hỗ trợ của tôi? (Who will need my help?)",
    ],
  },
  {
    title: "3. Tôi thực hiện công việc như thế nào?",
    hint: "Mô tả quy trình tư vấn, cách hỏi từng câu, nguyên tắc dùng công cụ và xử lý dữ liệu.",
    aliases: [
      "Tôi hoàn thành công việc thế nào?",
      "3. Tôi thực hiện công việc như thế nào? (How do I get things done?)",
    ],
  },
  {
    title: "4. Tôi nên tránh điều gì?",
    hint: "Liệt kê các giới hạn: không bịa dữ liệu, không lạc đề, không lộ thông tin, không dùng định dạng cấm.",
    aliases: ["Tôi nên tránh điều gì?", "4. Tôi nên tránh điều gì? (What should I avoid?)"],
  },
  {
    title: "5. Bạn muốn tôi theo dõi kết quả nào?",
    hint: "Mô tả các kết quả cần thúc đẩy: lưu liên hệ, nắm nguyện vọng, đề xuất phù hợp, ứng tuyển.",
    aliases: [
      "Kết quả nào cần theo dõi?",
      "5. Bạn muốn tôi theo dõi kết quả nào? (What results do you want me to track?)",
    ],
  },
  {
    title: "6. Tôi nên giao tiếp với mọi người như thế nào?",
    hint: "Mô tả ngôn ngữ, xưng hô, thái độ, độ dài, emoji và mẫu định dạng đầu ra.",
    aliases: [
      "Tôi nên giao tiếp thế nào?",
      "6. Tôi nên giao tiếp với mọi người như thế nào? (How should I talk to people?)",
    ],
  },
  {
    title: "7. Lưu ý thêm",
    hint: "Ghi các quy tắc bổ sung, edge cases, ngày giờ hệ thống, lịch trình hoặc nhắc giới hạn hỗ trợ.",
    aliases: ["Mẹo bổ sung?", "7. Lưu ý thêm (Any extra tips?)"],
  },
] as const;

type PersonaSectionValues = string[];

// 7-section persona scaffold (mirrors kb/ChatBotGuideline.md). Downloaded files
// keep the prompts, but in-app completion only counts user-authored answers.
export const PERSONA_TEMPLATE = PERSONA_SECTIONS.map(
  (section) => `### ${section.title}\n(${section.hint})`,
).join("\n\n");

const PERSONA_TEMPLATE_FILENAME = "mau-agent-vfic.md";

const emptyPersonaSections = (): PersonaSectionValues =>
  PERSONA_SECTIONS.map(() => "");

const normalizeSectionTitle = (value: string) =>
  value.trim().toLowerCase().replace(/\s+/g, " ");

const stripTemplateHint = (value: string, hint: string) => {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith("(") && trimmed.endsWith(")")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    return "";
  }
  return trimmed === `(${hint})` || trimmed === hint ? "" : trimmed;
};

const parsePersonaMarkdown = (markdown: string) => {
  const sections = emptyPersonaSections();
  let extraMarkdown = "";
  const matches = [...markdown.matchAll(/^###\s+(.+?)\s*$/gm)];

  if (matches.length === 0) {
    return {
      sections,
      extraMarkdown: markdown.trim(),
    };
  }

  const leading = markdown.slice(0, matches[0].index).trim();
  if (leading) extraMarkdown = leading;

  matches.forEach((match, index) => {
    const title = match[1] ?? "";
    const start = (match.index ?? 0) + match[0].length;
    const end =
      index + 1 < matches.length ? (matches[index + 1].index ?? markdown.length) : markdown.length;
    const content = markdown.slice(start, end).trim();
    const normalizedTitle = normalizeSectionTitle(title);
    const sectionIndex = PERSONA_SECTIONS.findIndex((section) =>
      [section.title, ...section.aliases].some(
        (candidate) => normalizeSectionTitle(candidate) === normalizedTitle,
      ),
    );

    if (sectionIndex >= 0) {
      sections[sectionIndex] = stripTemplateHint(
        content,
        PERSONA_SECTIONS[sectionIndex].hint,
      );
      return;
    }

    const block = `### ${title}\n${content}`.trim();
    extraMarkdown = [extraMarkdown, block].filter(Boolean).join("\n\n");
  });

  return { sections, extraMarkdown };
};

const composePersonaMarkdown = (
  sections: PersonaSectionValues,
  extraMarkdown = "",
) =>
  [
    ...PERSONA_SECTIONS.map(
      (section, index) =>
        `### ${section.title}\n\n${(sections[index] ?? "").trim()}`,
    ),
    extraMarkdown.trim(),
  ]
    .filter(Boolean)
    .join("\n\n");

export const getCompletedPersonaSectionCount = (markdown: string) =>
  parsePersonaMarkdown(markdown).sections.filter((section) => section.trim())
    .length;

export const getPersonaAuthoredContentLength = (markdown: string) => {
  const parsed = parsePersonaMarkdown(markdown);
  return [...parsed.sections, parsed.extraMarkdown]
    .join("\n")
    .trim().length;
};

export interface PersonaValues {
  name: string;
  body_md: string;
  notes: string;
}

interface PersonaFormProps {
  initial: PersonaValues;
  submitLabel: string;
  onSubmit: (values: PersonaValues) => Promise<void>;
  onImported?: () => void;
  extraActions?: ReactNode;
}

const PersonaForm = ({
  initial,
  submitLabel,
  onSubmit,
  onImported,
  extraActions,
}: PersonaFormProps) => {
  const notify = useNotify();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(initial.name);
  const [sectionValues, setSectionValues] = useState<PersonaSectionValues>(
    () => parsePersonaMarkdown(initial.body_md).sections,
  );
  const [extraMarkdown, setExtraMarkdown] = useState(
    () => parsePersonaMarkdown(initial.body_md).extraMarkdown,
  );
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [importing, setImporting] = useState(false);
  const bodyMd = useMemo(
    () => composePersonaMarkdown(sectionValues, extraMarkdown),
    [extraMarkdown, sectionValues],
  );

  const updateSectionValue = (index: number, value: string) => {
    setSectionValues((current) =>
      current.map((section, sectionIndex) =>
        sectionIndex === index ? value : section,
      ),
    );
  };

  const submit = async () => {
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit({ name, body_md: bodyMd, notes });
    } finally {
      setSubmitting(false);
    }
  };

  const downloadTemplate = () => {
    const blob = new Blob([PERSONA_TEMPLATE], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = PERSONA_TEMPLATE_FILENAME;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const onPersonaFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    const fileName = file.name.toLowerCase();
    if (!fileName.endsWith(".md") && !fileName.endsWith(".txt")) {
      notify("Vui lòng tải lên file .md hoặc .txt.", { type: "warning" });
      return;
    }

    setImporting(true);
    try {
      const persona = await importPersona(file);
      const parsed = parsePersonaMarkdown(persona.body_md);
      // Populate form with imported data
      setName(persona.name);
      setSectionValues(parsed.sections);
      setExtraMarkdown(parsed.extraMarkdown);
      if (persona.notes != null) setNotes(persona.notes);
      notify(
        `Đã nhập Agent "${persona.name}" thành công. Hãy rà soát trước khi lưu.`,
        { type: "success" },
      );
      onImported?.();
    } catch (e: unknown) {
      const message =
        (e as Error)?.message ??
        "Không nhập được file Agent. Vui lòng thử lại.";
      // Extract friendly message from API error if possible
      notify(message, { type: "error" });
    } finally {
      setImporting(false);
    }
  };

  const completedSectionCount = sectionValues.filter((section) => section.trim()).length;
  const contentLength = [...sectionValues, extraMarkdown].join("\n").trim().length;

  return (
    <Card className="w-full overflow-hidden rounded-xl py-0 shadow-sm">
      <CardHeader className="border-b bg-muted/20 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="size-4 text-primary" />
              Cấu hình Agent
            </CardTitle>
          </div>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            <Badge variant="secondary" className="gap-1.5">
              <FileText className="size-3" />
              {completedSectionCount}/7 phần
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <FileText className="size-3" />
              {contentLength.toLocaleString("vi-VN")} ký tự
            </Badge>
            <Badge
              variant={name.trim() ? "secondary" : "outline"}
              className="gap-1.5"
            >
              <CheckCircle2 className="size-3" />
              {name.trim() ? "Có tên Agent" : "Chưa đặt tên"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-0 py-0">
        <form
          className="flex flex-col"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="border-b bg-background px-4 py-4 sm:px-5">
            <section className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_auto] lg:items-end">
              <div className="grid gap-2">
                <Label htmlFor="persona-name" className="text-sm font-semibold">
                  Tên Agent
                </Label>
                <Input
                  id="persona-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="VD: Trợ lý tuyển dụng LG Display"
                  className="h-11 text-base sm:text-sm lg:max-w-xl"
                />
              </div>

              <div className="flex flex-wrap gap-2 lg:justify-end">
                <Button
                  type="button"
                  variant="outline"
                  className="h-11"
                  onClick={downloadTemplate}
                >
                  <Download className="size-4" />
                  Tải mẫu
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-11"
                  disabled={importing}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {importing ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Upload className="size-4" />
                  )}
                  {importing ? "Đang nhập..." : "Nhập file"}
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".md,.txt,text/markdown,text/plain"
                  className="hidden"
                  onChange={onPersonaFileChange}
                />
              </div>
            </section>
          </div>

          <section className="px-4 py-4 sm:px-5">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="size-4 text-primary" />
              Nội dung Agent
            </div>

            <div className="mt-4 grid gap-4">
              <div className="grid gap-3 md:grid-cols-2">
                {PERSONA_SECTIONS.map((section, index) => {
                  const value = sectionValues[index] ?? "";
                  const completed = value.trim().length > 0;

                  return (
                    <div
                      key={section.title}
                      className="rounded-lg border bg-background p-4"
                    >
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs font-medium uppercase text-muted-foreground">
                            Phần {index + 1}
                          </div>
                          <Label
                            htmlFor={`persona-section-${index}`}
                            className="mt-1 block text-sm font-semibold"
                          >
                            {section.title}
                          </Label>
                        </div>
                        <Badge
                          variant={completed ? "secondary" : "outline"}
                          className="shrink-0"
                        >
                          {completed ? "Đã điền" : "Trống"}
                        </Badge>
                      </div>
                      <Textarea
                        id={`persona-section-${index}`}
                        value={value}
                        onChange={(event) =>
                          updateSectionValue(index, event.target.value)
                        }
                        placeholder={section.hint}
                        rows={6}
                        className="min-h-[132px] resize-y bg-transparent text-sm leading-6 shadow-none"
                      />
                    </div>
                  );
                })}

                {extraMarkdown && (
                  <div className="rounded-lg border bg-background p-4 md:col-span-2">
                    <div className="mb-3 text-sm font-semibold">
                      Nội dung ngoài mẫu
                    </div>
                    <Textarea
                      value={extraMarkdown}
                      onChange={(event) => setExtraMarkdown(event.target.value)}
                      rows={5}
                      className="min-h-[120px] resize-y bg-transparent font-mono text-xs leading-5 shadow-none"
                    />
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="border-t bg-muted/10 px-4 py-4 sm:px-5">
            <div className="grid gap-2">
              <Label htmlFor="persona-notes" className="text-sm font-semibold">
                Ghi chú riêng tư
              </Label>
              <Input
                id="persona-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="h-10"
              />
            </div>
          </section>

          <div className="sticky bottom-[72px] z-10 flex flex-col-reverse gap-2 border-t bg-card/95 px-4 py-3 backdrop-blur sm:flex-row sm:items-center sm:justify-end sm:px-5 md:bottom-0">
            {extraActions}
            <Button
              type="submit"
              className="sm:min-w-32"
              disabled={submitting || !name.trim()}
            >
              {submitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Đang lưu...
                </>
              ) : (
                submitLabel
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};

export { PersonaForm };
