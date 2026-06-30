import { useState, type ReactNode } from "react";
import { useNotify } from "ra-core";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Loader2, Plus, Trash2, Wand2 } from "lucide-react";
import { Markdown } from "../misc/Markdown";
import {
  generatePersona,
  expandPersonaRule,
} from "@/lib/vfic/knowledgeService";

// 7-section persona scaffold (mirrors kb/ChatBotGuideline.md). Seeds the editor
// so new personas "follow the format"; the admin edits/extends each section and
// the body is re-saved in place whenever instructions change.
export const PERSONA_TEMPLATE = `### Vai trò của tôi là gì?
(Tôi là ai, phục vụ mục đích gì?)

### Ai cần tôi giúp?
(Đối tượng người dùng tôi hỗ trợ?)

### Tôi hoàn thành công việc thế nào?
(Các bước quy trình, quy tắc dùng công cụ, mỗi tin nhắn một câu hỏi...)

### Tôi nên tránh điều gì?
(Nội dung không được làm, không bịa thông tin...)

### Kết quả nào cần theo dõi?
(Thước đo thành công: nắm liên hệ, phân loại ý định...)

### Tôi nên giao tiếp thế nào?
(Giọng điệu, đại từ, độ dài, ngôn ngữ...)

### Mẹo bổ sung?
(Sự kiên nhẫn, đồng cảm, xử lý ngoài phạm vi...)
`;

export interface PersonaValues {
  name: string;
  body_md: string;
  notes: string;
}

interface PersonaFormProps {
  initial: PersonaValues;
  submitLabel: string;
  onSubmit: (values: PersonaValues) => Promise<void>;
  extraActions?: ReactNode;
}

interface RuleItem {
  id: number;
  raw: string;
  expanded: string;
  expanding: boolean;
  expanded_at: number; // timestamp to track freshness
}

let _nextRuleId = 0;

const PersonaForm = ({
  initial,
  submitLabel,
  onSubmit,
  extraActions,
}: PersonaFormProps) => {
  const notify = useNotify();
  const [name, setName] = useState(initial.name);
  const [bodyMd, setBodyMd] = useState(initial.body_md || PERSONA_TEMPLATE);
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [genDesc, setGenDesc] = useState("");
  const [generating, setGenerating] = useState(false);
  const [rules, setRules] = useState<RuleItem[]>([]);

  const submit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ name, body_md: bodyMd, notes });
    } finally {
      setSubmitting(false);
    }
  };

  const onGenerate = async () => {
    const desc = genDesc.trim();
    if (!desc || generating) return;
    setGenerating(true);
    try {
      const ruleTexts = rules.map((r) => r.expanded || r.raw).filter(Boolean);
      const res = await generatePersona(desc, ruleTexts);
      setBodyMd(res.body_md);
      notify("Đã tạo Agent bằng AI. Hãy rà soát và chỉnh sửa trước khi lưu.", {
        type: "success",
      });
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setGenerating(false);
    }
  };

  const addRule = () => {
    setRules((prev) => [
      ...prev,
      {
        id: _nextRuleId++,
        raw: "",
        expanded: "",
        expanding: false,
        expanded_at: 0,
      },
    ]);
  };

  const removeRule = (id: number) => {
    setRules((prev) => prev.filter((r) => r.id !== id));
  };

  const updateRuleRaw = (id: number, raw: string) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, raw } : r)));
  };

  const expandRule = async (id: number) => {
    const rule = rules.find((r) => r.id === id);
    if (!rule || !rule.raw.trim() || rule.expanding) return;
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, expanding: true } : r)),
    );
    try {
      const res = await expandPersonaRule(rule.raw.trim());
      setRules((prev) =>
        prev.map((r) =>
          r.id === id
            ? {
                ...r,
                expanded: res.expanded,
                expanding: false,
                expanded_at: Date.now(),
              }
            : r,
        ),
      );
    } catch (e) {
      notify((e as Error).message, { type: "error" });
      setRules((prev) =>
        prev.map((r) => (r.id === id ? { ...r, expanding: false } : r)),
      );
    }
  };

  const updateRuleExpanded = (id: number, expanded: string) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, expanded } : r)));
  };

  return (
    <Card className="mt-4 w-full overflow-hidden py-0">
      <CardHeader className="border-b bg-muted/20 px-5 py-4 sm:px-6">
        <CardTitle className="text-base">Cấu hình Agent</CardTitle>
        <CardDescription>
          Thiết lập vai trò, luật trả lời và nội dung hướng dẫn cho chatbot.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-5 px-5 py-5 sm:px-6">
        <section className="grid gap-2">
          <Label htmlFor="persona-name" className="text-sm font-semibold">
            Tên Agent
          </Label>
          <Input
            id="persona-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="VD: Trợ lý tuyển dụng LG Display"
            className="h-10"
          />
        </section>

        <section className="rounded-lg border border-dashed bg-muted/10 p-4">
          <div className="grid gap-3">
            <div>
              <Label htmlFor="persona-gen-desc" className="text-sm font-semibold">
                Tạo nhanh bằng AI
              </Label>
              <p className="mt-1 text-xs text-muted-foreground">
                Mô tả ngắn gọn Agent cần tạo.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="persona-gen-desc"
                value={genDesc}
                onChange={(e) => setGenDesc(e.target.value)}
                placeholder="VD: Trợ lý tuyển dụng LG Display, thân thiện, cho lao động phổ thông"
                disabled={generating}
                className="h-10"
              />
              <Button
                type="button"
                variant="secondary"
                onClick={onGenerate}
                disabled={generating || !genDesc.trim()}
                className="h-10 shrink-0"
              >
                {generating ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Đang tạo
                  </>
                ) : (
                  <>
                    <Wand2 className="size-4" />
                    Tạo bằng AI
                  </>
                )}
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-lg border bg-card/60 p-4">
          <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">Luật bổ sung</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Quy tắc ngắn để AI đưa vào hướng dẫn trả lời.
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 shrink-0 text-xs"
                onClick={addRule}
              >
                <Plus className="size-3.5" />
                Thêm luật
              </Button>
            </div>
            {rules.length === 0 ? (
              <p className="rounded-md border border-dashed bg-muted/20 px-3 py-3 text-center text-xs text-muted-foreground">
                Chưa có luật bổ sung.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {rules.map((rule) => (
                  <div
                    key={rule.id}
                    className="flex flex-col gap-2 rounded-md border bg-background/70 p-2.5"
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                      <Input
                        value={rule.raw}
                        onChange={(e) => updateRuleRaw(rule.id, e.target.value)}
                        placeholder="Nhập quy tắc ngắn..."
                        className="h-9 text-xs"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-9 shrink-0 text-xs"
                        onClick={() => expandRule(rule.id)}
                        disabled={rule.expanding || !rule.raw.trim()}
                      >
                        {rule.expanding ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Wand2 className="size-3.5" />
                        )}
                        Mở rộng
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-9 shrink-0 text-xs text-destructive"
                        onClick={() => removeRule(rule.id)}
                        aria-label="Xóa luật"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                    {rule.expanded && (
                      <Textarea
                        value={rule.expanded}
                        onChange={(e) =>
                          updateRuleExpanded(rule.id, e.target.value)
                        }
                        rows={2}
                        className="text-xs"
                        placeholder="Hướng dẫn đã mở rộng (có thể chỉnh sửa)..."
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="grid gap-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <Label htmlFor="persona-body" className="text-sm font-semibold">
                Nội dung Agent
              </Label>
              <p className="mt-1 text-xs text-muted-foreground">Markdown</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 text-xs"
              onClick={() => setBodyMd(PERSONA_TEMPLATE)}
            >
              Dùng mẫu 7 phần
            </Button>
          </div>
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.82fr)]">
            <Textarea
              id="persona-body"
              value={bodyMd}
              onChange={(e) => setBodyMd(e.target.value)}
              rows={22}
              className="min-h-[520px] resize-y rounded-lg font-mono text-xs leading-5"
            />
            <div className="min-h-[520px] overflow-hidden rounded-lg border bg-background/70">
              <div className="border-b bg-muted/20 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Xem trước
              </div>
              <div className="max-h-[680px] overflow-y-auto px-4 py-4 text-sm">
                <Markdown>{bodyMd}</Markdown>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-2">
          <Label htmlFor="persona-notes">
            Ghi chú (riêng tư, không gửi cho LLM)
          </Label>
          <Input
            id="persona-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </section>

        <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-end">
          {extraActions}
          <Button
            type="button"
            variant="outline"
            className="bg-foreground text-background hover:bg-foreground/90 hover:text-background sm:min-w-28"
            onClick={submit}
            disabled={submitting || !name.trim()}
          >
            {submitting ? "Đang lưu..." : submitLabel}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export { PersonaForm };
