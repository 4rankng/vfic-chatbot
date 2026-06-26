import { useState, type ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Markdown } from "../misc/Markdown";

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

export const PersonaForm = ({
  initial,
  submitLabel,
  onSubmit,
  extraActions,
}: PersonaFormProps) => {
  const [name, setName] = useState(initial.name);
  const [bodyMd, setBodyMd] = useState(initial.body_md || PERSONA_TEMPLATE);
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ name, body_md: bodyMd, notes });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="mt-4 max-w-4xl">
      <CardContent className="flex flex-col gap-4 pt-6">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="persona-name">Tên persona</Label>
          <Input
            id="persona-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="VD: Trợ lý tuyển dụng LG Display"
          />
        </div>

        <div className="flex items-center justify-between">
          <Label htmlFor="persona-body">Nội dung persona (markdown)</Label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setBodyMd(PERSONA_TEMPLATE)}
          >
            Dùng mẫu 7 phần
          </Button>
        </div>
        <Textarea
          id="persona-body"
          value={bodyMd}
          onChange={(e) => setBodyMd(e.target.value)}
          rows={18}
          className="font-mono text-xs"
        />

        <Card className="border-dashed">
          <CardHeader className="py-3">
            <CardTitle className="text-xs uppercase tracking-wide text-muted-foreground">
              Xem trước
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-sm">
            <Markdown>{bodyMd}</Markdown>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="persona-notes">Ghi chú (riêng tư, không gửi cho LLM)</Label>
          <Input
            id="persona-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2">
          <Button type="button" onClick={submit} disabled={submitting || !name.trim()}>
            {submitting ? "Đang lưu..." : submitLabel}
          </Button>
          {extraActions}
        </div>
      </CardContent>
    </Card>
  );
};
