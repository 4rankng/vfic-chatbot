import { useEffect, useState } from "react";
import { useNotify } from "ra-core";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createProjectFaq,
  deleteProjectFaq,
  getProjectFaq,
  updateProjectFaq,
  type ProjectFaq,
} from "@/lib/vfic/knowledgeService";

type FaqDraft = {
  question: string;
  answer: string;
  question_variants: string[];
  required_terms: string[];
  forbidden_terms: string[];
};

const emptyDraft = (): FaqDraft => ({
  question: "",
  answer: "",
  question_variants: [],
  required_terms: [],
  forbidden_terms: [],
});

const draftFromItem = (item: ProjectFaq): FaqDraft => ({
  question: item.question,
  answer: item.answer,
  question_variants: [...(item.question_variants ?? [])],
  required_terms: [...(item.required_terms ?? [])],
  forbidden_terms: [...(item.forbidden_terms ?? [])],
});

/** Tag/chip input for a list of strings (comma- or Enter-separated). */
const TermListInput = ({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) => {
  const [text, setText] = useState("");
  const commit = () => {
    const parts = text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    const merged = [...values];
    for (const part of parts) {
      if (!merged.some((v) => v.toLowerCase() === part.toLowerCase())) {
        merged.push(part);
      }
    }
    onChange(merged);
    setText("");
  };
  return (
    <div className="grid gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">
        {label}
      </span>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((value, idx) => (
            <span
              key={`${value}-${idx}`}
              className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px]"
            >
              {value}
              <button
                type="button"
                aria-label={`Xóa ${value}`}
                onClick={() => onChange(values.filter((_, i) => i !== idx))}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
        placeholder={placeholder}
      />
    </div>
  );
};

/** Shared question + answer + optional FAQ-bypass fields for the new/edit forms. */
const FaqFields = ({
  draft,
  setDraft,
}: {
  draft: FaqDraft;
  setDraft: (updater: (prev: FaqDraft) => FaqDraft) => void;
}) => (
  <>
    <Input
      value={draft.question}
      onChange={(event) =>
        setDraft((prev) => ({ ...prev, question: event.target.value }))
      }
      placeholder="Câu hỏi"
    />
    <Textarea
      value={draft.answer}
      onChange={(event) =>
        setDraft((prev) => ({ ...prev, answer: event.target.value }))
      }
      rows={3}
      placeholder="Câu trả lời"
    />
    <details className="rounded-md border bg-muted/10 p-2">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Tùy chọn trả lời nhanh (FAQ bypass)
      </summary>
      <div className="mt-2 grid gap-2">
        <TermListInput
          label="Biến thể câu hỏi"
          values={draft.question_variants}
          onChange={(values) =>
            setDraft((prev) => ({ ...prev, question_variants: values }))
          }
          placeholder="Thêm biến thể rồi Enter"
        />
        <TermListInput
          label="Từ bắt buộc (Required Terms)"
          values={draft.required_terms}
          onChange={(values) =>
            setDraft((prev) => ({ ...prev, required_terms: values }))
          }
          placeholder="Từ PHẢI có trong câu hỏi"
        />
        <TermListInput
          label="Từ cấm (Forbidden Terms)"
          values={draft.forbidden_terms}
          onChange={(values) =>
            setDraft((prev) => ({ ...prev, forbidden_terms: values }))
          }
          placeholder="Từ KHÔNG được xuất hiện"
        />
      </div>
    </details>
  </>
);

export const ProjectFaqEditor = ({
  projectId,
  editable = false,
  embedded = false,
}: {
  projectId: string;
  editable?: boolean;
  embedded?: boolean;
}) => {
  const notify = useNotify();
  const [items, setItems] = useState<ProjectFaq[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [savingNew, setSavingNew] = useState(false);
  const [newDraft, setNewDraft] = useState<FaqDraft>(emptyDraft);

  const load = async () => {
    setLoading(true);
    try {
      const res = await getProjectFaq(projectId, 50);
      setItems(res.data);
    } catch (err) {
      notify(`Không tải được FAQ: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const createFaq = async () => {
    const question = newDraft.question.trim();
    const answer = newDraft.answer.trim();
    if (!question || !answer) {
      notify("Vui lòng nhập cả câu hỏi và câu trả lời.", { type: "warning" });
      return;
    }
    setSavingNew(true);
    try {
      const created = await createProjectFaq(projectId, {
        question,
        answer,
        question_variants: newDraft.question_variants,
        required_terms: newDraft.required_terms,
        forbidden_terms: newDraft.forbidden_terms,
      });
      setItems((prev) => [created, ...prev]);
      setNewDraft(emptyDraft());
      setAdding(false);
      notify("Đã thêm FAQ.", { type: "success" });
    } catch (err) {
      notify(`Thêm FAQ thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setSavingNew(false);
    }
  };

  const updateItem = (updated: ProjectFaq) => {
    setItems((prev) =>
      prev.map((item) => (item.id === updated.id ? updated : item)),
    );
  };

  const removeItem = (id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-base font-semibold">FAQ dự án</h3>
      <div className="flex items-center gap-2">
        {editable && !adding && (
          <Button
            size="sm"
            onClick={() => setAdding(true)}
            title="Thêm câu hỏi FAQ mới"
          >
            <Plus className="size-4" />
            Thêm
          </Button>
        )}
      </div>
    </div>
  );

  const body = (
    <div className="flex flex-col gap-4">
      {editable && adding && (
        <div className="rounded-md border border-dashed bg-muted/20 p-3">
          <div className="grid gap-2">
            <FaqFields draft={newDraft} setDraft={setNewDraft} />
            <div className="flex justify-end gap-1">
              <Button
                size="sm"
                variant="ghost"
                aria-label="Hủy thêm FAQ"
                onClick={() => {
                  setNewDraft(emptyDraft());
                  setAdding(false);
                }}
                disabled={savingNew}
              >
                <X className="size-4" />
              </Button>
              <Button size="sm" onClick={createFaq} disabled={savingNew}>
                <Plus className="size-4" />
                {savingNew ? "Đang thêm..." : "Thêm"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="grid gap-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-20 w-full" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="grid gap-3">
          {items.map((item) => (
            <FaqRow
              key={item.id}
              projectId={projectId}
              item={item}
              editable={editable}
              onUpdate={updateItem}
              onDelete={removeItem}
            />
          ))}
        </div>
      ) : (
        <p className="rounded-md border border-dashed bg-muted/20 px-3 py-4 text-center text-sm text-muted-foreground">
          Chưa có FAQ cho dự án này.
        </p>
      )}
    </div>
  );

  if (embedded) {
    return (
      <section className="space-y-3">
        {header}
        {body}
      </section>
    );
  }

  return (
    <Card className="mt-4 overflow-hidden">
      <CardHeader>
        <CardTitle>{header}</CardTitle>
      </CardHeader>
      <CardContent className="pt-2">{body}</CardContent>
    </Card>
  );
};

const FaqRow = ({
  projectId,
  item,
  editable,
  onUpdate,
  onDelete,
}: {
  projectId: string;
  item: ProjectFaq;
  editable: boolean;
  onUpdate: (item: ProjectFaq) => void;
  onDelete: (id: string) => void;
}) => {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<FaqDraft>(() => draftFromItem(item));
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const cancel = () => {
    setDraft(draftFromItem(item));
    setEditing(false);
  };

  const save = async () => {
    const question = draft.question.trim();
    const answer = draft.answer.trim();
    if (!question || !answer) {
      notify("Vui lòng nhập cả câu hỏi và câu trả lời.", { type: "warning" });
      return;
    }
    setSaving(true);
    try {
      const updated = await updateProjectFaq(projectId, item.id, {
        question,
        answer,
        question_variants: draft.question_variants,
        required_terms: draft.required_terms,
        forbidden_terms: draft.forbidden_terms,
      });
      onUpdate(updated);
      setEditing(false);
      notify("Đã lưu FAQ.", { type: "success" });
    } catch (err) {
      notify(`Lưu FAQ thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Xóa câu hỏi FAQ này?")) return;
    setDeleting(true);
    try {
      await deleteProjectFaq(projectId, item.id);
      onDelete(item.id);
      notify("Đã xóa FAQ.", { type: "success" });
    } catch (err) {
      notify(`Xóa FAQ thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="rounded-md border bg-card p-3">
      {editing ? (
        <div className="grid gap-2">
          <FaqFields draft={draft} setDraft={setDraft} />
          <div className="flex justify-end gap-1">
            <Button
              size="sm"
              variant="ghost"
              aria-label="Hủy chỉnh sửa FAQ"
              onClick={cancel}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? "Đang lưu..." : "Lưu"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold leading-5">{item.question}</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-5 text-muted-foreground">
              {item.answer}
            </p>
            {(item.source_name || item.source_anchor) && (
              <p className="mt-2 text-[11px] text-muted-foreground">
                {item.source_name ?? "FAQ"}
                {item.source_anchor ? ` • ${item.source_anchor}` : ""}
              </p>
            )}
          </div>
          {editable && (
            <div className="flex shrink-0 gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(true)}
                title="Chỉnh sửa FAQ"
                aria-label="Chỉnh sửa FAQ"
              >
                <Pencil className="size-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={remove}
                disabled={deleting}
                title="Xóa FAQ"
                aria-label="Xóa FAQ"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
