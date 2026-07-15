import { useMemo, useState } from "react";
import { Plus, Send, Trash2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { useNotify } from "ra-core";
import {
  createBlankWorkflowVersion,
  listWorkflowVersions,
  publishWorkflowVersion,
  type WorkflowVersionDraft,
  type WorkflowVersionSummary,
} from "./workflow-authoring-client";
import { validateWorkflowGraph } from "./workflow-validation";

type AttributeDraft = {
  key: string;
  label: string;
  type: "" | "string" | "integer" | "number" | "boolean" | "date" | "datetime";
  required: boolean;
  maxLength: string;
  enumValues: string;
};

const parseEnumValues = (attribute: AttributeDraft): {
  valid: boolean;
  values?: Array<string | number | boolean>;
} => {
  const rawValues = attribute.enumValues.split("\n").map((value) => value.trim()).filter(Boolean);
  if (rawValues.length === 0) return { valid: true };
  let values: Array<string | number | boolean>;
  switch (attribute.type) {
    case "string":
      values = rawValues;
      break;
    case "integer":
      values = rawValues.map(Number);
      if (values.some((value) => typeof value !== "number" || !Number.isInteger(value))) return { valid: false };
      break;
    case "number":
      values = rawValues.map(Number);
      if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) return { valid: false };
      break;
    case "boolean":
      if (rawValues.some((value) => value !== "true" && value !== "false")) return { valid: false };
      values = rawValues.map((value) => value === "true");
      break;
    default:
      return { valid: false };
  }
  if (new Set(values.map((value) => `${typeof value}:${String(value)}`)).size !== values.length) {
    return { valid: false };
  }
  return { valid: true, values };
};

type WorkflowAuthoringPageProps = {
  packKey?: string;
  workflowKey?: string;
  embedded?: boolean;
  onPublished?: (version: WorkflowVersionSummary) => void | Promise<void>;
};

const blankFor = (packKey?: string, workflowKey?: string): WorkflowVersionDraft => ({
  ...createBlankWorkflowVersion(),
  pack_key: packKey ?? "",
  workflow_key: workflowKey ?? "",
});

export const WorkflowAuthoringPage = ({
  packKey,
  workflowKey,
  embedded = false,
  onPublished,
}: WorkflowAuthoringPageProps) => {
  const notify = useNotify();
  const [draft, setDraft] = useState<WorkflowVersionDraft>(() => blankFor(packKey, workflowKey));
  const [attributes, setAttributes] = useState<AttributeDraft[]>([]);
  const [publishing, setPublishing] = useState(false);
  const validationIssues = useMemo(
    () => validateWorkflowGraph(draft, attributes.map((attribute) => attribute.key)),
    [attributes, draft],
  );
  const checklist = [
    { label: "Có đúng một giai đoạn bắt đầu", codes: ["INITIAL_COUNT"] },
    { label: "Có ít nhất một giai đoạn kết thúc", codes: ["TERMINAL_REQUIRED"] },
    { label: "Mã và thứ tự không trùng nhau", codes: ["STAGE_KEY_DUPLICATE", "STAGE_POSITION_DUPLICATE", "TAG_KEY_DUPLICATE", "TAG_POSITION_DUPLICATE", "ATTRIBUTE_KEY_DUPLICATE"] },
    { label: "Các luồng chuyển hợp lệ", codes: ["TRANSITION_REQUIRED", "TRANSITION_ENDPOINT", "TRANSITION_SELF", "TRANSITION_DUPLICATE", "TERMINAL_OUTGOING"] },
    { label: "Mọi giai đoạn đều đi được từ điểm bắt đầu", codes: ["STAGE_UNREACHABLE"] },
  ];

  if (!packKey || !workflowKey) {
    return (
      <div className={embedded ? "" : "mx-auto w-full max-w-4xl p-4 md:p-8"}>
        <Alert>
          <AlertTitle>Hãy chọn gói và quy trình trước</AlertTitle>
          <AlertDescription>
            Mở phần thiết lập quy trình để tạo phiên bản mới; hệ thống sẽ tự liên kết đúng gói và quy trình.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const updateLabel = (value: string) =>
    setDraft((current) => ({ ...current, label: value }));
  const addStage = () =>
    setDraft((current) => ({
      ...current,
      stages: [
        ...current.stages,
        {
          key: "",
          label: "",
          position: current.stages.length,
          is_initial: current.stages.length === 0,
          is_terminal: false,
        },
      ],
    }));
  const updateStage = (
    index: number,
    field: "key" | "label" | "is_initial" | "is_terminal",
    value: string | boolean,
  ) =>
    setDraft((current) => ({
      ...current,
      stages: current.stages.map((stage, stageIndex) => {
        if (field === "is_initial" && value === true) {
          return { ...stage, is_initial: stageIndex === index };
        }
        return stageIndex === index ? { ...stage, [field]: value } : stage;
      }),
    }));
  const removeStage = (index: number) =>
    setDraft((current) => {
      const removedKey = current.stages[index]?.key;
      return {
        ...current,
        stages: current.stages
          .filter((_, stageIndex) => stageIndex !== index)
          .map((stage, position) => ({ ...stage, position })),
        transitions: current.transitions.filter(
          (transition) =>
            transition.from_stage_key !== removedKey && transition.to_stage_key !== removedKey,
        ),
      };
    });
  const addTransition = () =>
    setDraft((current) => ({
      ...current,
      transitions: [
        ...current.transitions,
        { from_stage_key: "", to_stage_key: "" },
      ],
    }));
  const updateTransition = (
    index: number,
    field: "from_stage_key" | "to_stage_key",
    value: string,
  ) =>
    setDraft((current) => ({
      ...current,
      transitions: current.transitions.map((transition, transitionIndex) =>
        transitionIndex === index ? { ...transition, [field]: value } : transition,
      ),
    }));
  const removeTransition = (index: number) =>
    setDraft((current) => ({
      ...current,
      transitions: current.transitions.filter((_, transitionIndex) => transitionIndex !== index),
    }));
  const addTag = () =>
    setDraft((current) => ({
      ...current,
      tags: [
        ...current.tags,
        {
          key: "",
          label: "",
          tone: "",
          position: current.tags.length,
        },
      ],
    }));
  const updateTag = (
    index: number,
    field: "key" | "label" | "tone",
    value: string,
  ) =>
    setDraft((current) => ({
      ...current,
      tags: current.tags.map((tag, tagIndex) =>
        tagIndex === index ? { ...tag, [field]: value } : tag,
      ),
    }));
  const removeTag = (index: number) =>
    setDraft((current) => ({
      ...current,
      tags: current.tags
        .filter((_, tagIndex) => tagIndex !== index)
        .map((tag, position) => ({ ...tag, position })),
    }));

  const addAttribute = () =>
    setAttributes((current) => [
      ...current,
      { key: "", label: "", type: "", required: false, maxLength: "", enumValues: "" },
    ]);
  const updateAttribute = <Key extends keyof AttributeDraft>(
    index: number,
    field: Key,
    value: AttributeDraft[Key],
  ) =>
    setAttributes((current) =>
      current.map((attribute, attributeIndex) =>
        attributeIndex === index ? { ...attribute, [field]: value } : attribute,
      ),
    );
  const updateAttributeType = (index: number, type: AttributeDraft["type"]) =>
    setAttributes((current) =>
      current.map((attribute, attributeIndex) =>
        attributeIndex === index
          ? { ...attribute, type, maxLength: "", enumValues: "" }
          : attribute,
      ),
    );
  const removeAttribute = (index: number) =>
    setAttributes((current) => current.filter((_, attributeIndex) => attributeIndex !== index));

  const publish = async () => {
    setPublishing(true);
    try {
      const existingVersions = await listWorkflowVersions();
      const previousVersion = existingVersions
        .filter(
          (version) =>
            version.pack_key === packKey && version.workflow_key === workflowKey,
        )
        .sort((left, right) => right.version_no - left.version_no)[0];
      const caseAttributeSchema = Object.fromEntries(
        attributes.map((attribute) => {
          const parsedEnum = parseEnumValues(attribute);
          return [
            attribute.key.trim(),
            {
              type: attribute.type as Exclude<AttributeDraft["type"], "">,
              label: attribute.label.trim(),
              required: attribute.required,
              ...(attribute.type === "string" && attribute.maxLength
                ? { max_length: Number(attribute.maxLength) }
                : {}),
              ...(parsedEnum.values ? { enum: parsedEnum.values } : {}),
            },
          ];
        }),
      );
      const version = await publishWorkflowVersion({
        ...draft,
        ...(previousVersion
          ? { expected_previous_version_no: previousVersion.version_no }
          : {}),
        case_attribute_schema: caseAttributeSchema,
      });
      notify("Đã xuất bản phiên bản quy trình bất biến.", { type: "success" });
      setDraft(blankFor(packKey, workflowKey));
      setAttributes([]);
      await onPublished?.(version);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className={embedded ? "w-full" : "mx-auto w-full max-w-4xl p-4 md:p-8"}>
      <header className="mb-6">
        <h1 className="text-page-title font-bold">Tạo phiên bản quy trình</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Bắt đầu từ biểu mẫu trống. Sau khi xuất bản, phiên bản không thể sửa hoặc xoá.
        </p>
      </header>
      <Card className="space-y-5 p-5">
        <label className="space-y-2 text-sm font-medium">
          Tên hiển thị
          <Input value={draft.label} onChange={(event) => updateLabel(event.target.value)} />
        </label>
        <section className="grid gap-3 rounded-md border p-4" aria-label="Kiểm tra cấu trúc quy trình">
          <h2 className="font-semibold">Kiểm tra cấu trúc</h2>
          <ul className="grid gap-2 text-sm">
            {checklist.map((item) => {
              const passed = !validationIssues.some((issue) => item.codes.includes(issue.code));
              return <li key={item.label} className={passed ? "text-foreground" : "text-muted-foreground"}>{passed ? "Đạt" : "Chưa đạt"} — {item.label}</li>;
            })}
          </ul>
          {validationIssues.length > 0 ? (
            <Alert variant="destructive">
              <AlertTitle>Cần hoàn tất cấu trúc quy trình</AlertTitle>
              <AlertDescription>
                <ul className="list-disc space-y-1 pl-4">
                  {validationIssues.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>)}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}
        </section>
        <section className="space-y-3" aria-label="Các giai đoạn">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">Giai đoạn</h2>
            <Button type="button" variant="outline" onClick={addStage}>
              <Plus className="size-4" /> Thêm giai đoạn
            </Button>
          </div>
          {draft.stages.length === 0 ? (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              Chưa có giai đoạn. Quy trình phải có đúng một giai đoạn bắt đầu.
            </p>
          ) : null}
          {draft.stages.map((stage, index) => (
            <div key={index} className="grid gap-3 rounded-md border p-3 md:grid-cols-2">
              <Input
                aria-label={`Mã giai đoạn ${index + 1}`}
                placeholder="ma-giai-doan"
                value={stage.key}
                onChange={(event) => updateStage(index, "key", event.target.value)}
              />
              <Input
                aria-label={`Tên giai đoạn ${index + 1}`}
                placeholder="Tên giai đoạn"
                value={stage.label}
                onChange={(event) => updateStage(index, "label", event.target.value)}
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="workflow-initial-stage"
                  checked={stage.is_initial}
                  onChange={(event) =>
                    updateStage(index, "is_initial", event.target.checked)
                  }
                />
                Giai đoạn bắt đầu
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={stage.is_terminal}
                  onChange={(event) =>
                    updateStage(index, "is_terminal", event.target.checked)
                  }
                />
                Giai đoạn kết thúc
              </label>
              <Button type="button" variant="ghost" onClick={() => removeStage(index)}>
                <Trash2 className="size-4" /> Xoá giai đoạn
              </Button>
            </div>
          ))}
        </section>
        <section className="space-y-3" aria-label="Luồng chuyển giai đoạn">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">Luồng chuyển</h2>
            <Button type="button" variant="outline" onClick={addTransition}>
              <Plus className="size-4" /> Thêm luồng chuyển
            </Button>
          </div>
          {draft.transitions.map((transition, index) => (
            <div key={index} className="grid gap-3 rounded-md border p-3 md:grid-cols-3">
              <select
                aria-label={`Từ giai đoạn ${index + 1}`}
                className="min-h-10 rounded-md border bg-background px-3"
                value={transition.from_stage_key}
                onChange={(event) =>
                  updateTransition(index, "from_stage_key", event.target.value)
                }
              >
                <option value="">Chọn giai đoạn bắt đầu</option>
                {draft.stages.filter((stage) => stage.key).map((stage) => (
                  <option key={stage.key} value={stage.key}>{stage.label || stage.key}</option>
                ))}
              </select>
              <select
                aria-label={`Đến giai đoạn ${index + 1}`}
                className="min-h-10 rounded-md border bg-background px-3"
                value={transition.to_stage_key}
                onChange={(event) =>
                  updateTransition(index, "to_stage_key", event.target.value)
                }
              >
                <option value="">Chọn giai đoạn tiếp theo</option>
                {draft.stages.filter((stage) => stage.key).map((stage) => (
                  <option key={stage.key} value={stage.key}>{stage.label || stage.key}</option>
                ))}
              </select>
              <Button type="button" variant="ghost" onClick={() => removeTransition(index)}>
                <Trash2 className="size-4" /> Xoá luồng chuyển
              </Button>
            </div>
          ))}
        </section>
        <section className="space-y-3" aria-label="Nhãn quy trình">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">Nhãn</h2>
            <Button type="button" variant="outline" onClick={addTag}>
              <Plus className="size-4" /> Thêm nhãn
            </Button>
          </div>
          {draft.tags.map((tag, index) => (
            <div key={index} className="grid gap-3 rounded-md border p-3 md:grid-cols-2">
              <Input
                aria-label={`Mã nhãn ${index + 1}`}
                placeholder="ma-nhan"
                value={tag.key}
                onChange={(event) => updateTag(index, "key", event.target.value)}
              />
              <Input
                aria-label={`Tên nhãn ${index + 1}`}
                placeholder="Tên nhãn"
                value={tag.label}
                onChange={(event) => updateTag(index, "label", event.target.value)}
              />
              <label className="grid gap-2 text-sm font-medium">
                Màu nhãn
                <select
                  aria-label={`Màu nhãn ${index + 1}`}
                  className="min-h-10 rounded-md border bg-background px-3"
                  value={tag.tone}
                  onChange={(event) => updateTag(index, "tone", event.target.value)}
                >
                  <option value="">Chọn màu nhãn</option>
                  <option value="neutral">Trung tính</option>
                  <option value="info">Thông tin</option>
                  <option value="success">Thành công</option>
                  <option value="warning">Cảnh báo</option>
                  <option value="danger">Nguy hiểm</option>
                </select>
              </label>
              <Button type="button" variant="ghost" onClick={() => removeTag(index)}>
                <Trash2 className="size-4" /> Xoá nhãn
              </Button>
            </div>
          ))}
        </section>
        <section className="space-y-3" aria-label="Thuộc tính hồ sơ">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">Thuộc tính hồ sơ</h2>
              <p className="text-sm text-muted-foreground">Chỉ thêm các thông tin riêng mà quy trình cần thu thập.</p>
            </div>
            <Button type="button" variant="outline" onClick={addAttribute}>
              <Plus className="size-4" /> Thêm thuộc tính
            </Button>
          </div>
          {attributes.length === 0 ? (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              Chưa có thuộc tính bổ sung.
            </p>
          ) : null}
          {attributes.map((attribute, index) => (
            <div key={index} className="grid gap-3 rounded-md border p-3 md:grid-cols-2">
              <Input
                aria-label={`Mã thuộc tính ${index + 1}`}
                placeholder="ma-thuoc-tinh"
                value={attribute.key}
                onChange={(event) => updateAttribute(index, "key", event.target.value)}
              />
              <Input
                aria-label={`Tên thuộc tính ${index + 1}`}
                placeholder="Tên hiển thị"
                value={attribute.label}
                onChange={(event) => updateAttribute(index, "label", event.target.value)}
              />
              <label className="grid gap-2 text-sm font-medium">
                Kiểu dữ liệu
                <select
                  aria-label={`Kiểu thuộc tính ${index + 1}`}
                  className="min-h-10 rounded-md border bg-background px-3"
                  value={attribute.type}
                  onChange={(event) =>
                    updateAttributeType(index, event.target.value as AttributeDraft["type"])
                  }
                >
                  <option value="">Chọn kiểu dữ liệu</option>
                  <option value="string">Văn bản</option>
                  <option value="integer">Số nguyên</option>
                  <option value="number">Số</option>
                  <option value="boolean">Có / Không</option>
                  <option value="date">Ngày</option>
                  <option value="datetime">Ngày và giờ</option>
                </select>
              </label>
              {attribute.type === "string" ? (
                <Input
                  aria-label={`Độ dài tối đa ${index + 1}`}
                  type="number"
                  min="1"
                  max="2000"
                  placeholder="Độ dài tối đa (không bắt buộc)"
                  value={attribute.maxLength}
                  onChange={(event) => updateAttribute(index, "maxLength", event.target.value)}
                />
              ) : null}
              {(["string", "integer", "number", "boolean"] as const).includes(
                attribute.type as "string" | "integer" | "number" | "boolean",
              ) ? (
                <label className="grid gap-2 text-sm font-medium md:col-span-2">
                  Các lựa chọn (không bắt buộc, mỗi dòng một giá trị)
                  <Textarea
                    aria-label={`Các lựa chọn thuộc tính ${index + 1}`}
                    value={attribute.enumValues}
                    onChange={(event) => updateAttribute(index, "enumValues", event.target.value)}
                    placeholder={attribute.type === "boolean" ? "true\nfalse" : "Mỗi dòng một lựa chọn"}
                  />
                  {!parseEnumValues(attribute).valid ? (
                    <span className="text-xs text-destructive">Giá trị lựa chọn không đúng kiểu dữ liệu hoặc bị trùng.</span>
                  ) : null}
                </label>
              ) : null}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={attribute.required}
                  onChange={(event) => updateAttribute(index, "required", event.target.checked)}
                />
                Bắt buộc nhập
              </label>
              <Button type="button" variant="ghost" onClick={() => removeAttribute(index)}>
                <Trash2 className="size-4" /> Xoá thuộc tính
              </Button>
            </div>
          ))}
        </section>
        <Button
          type="button"
          disabled={
            publishing ||
            !draft.label.trim() ||
            validationIssues.length > 0 ||
            draft.tags.some((tag) => !tag.key.trim() || !tag.label.trim() || !tag.tone) ||
            attributes.some(
              (attribute) =>
                !attribute.key.trim() ||
                !attribute.label.trim() ||
                !attribute.type ||
                !parseEnumValues(attribute).valid ||
                (attribute.maxLength !== "" &&
                  (!Number.isInteger(Number(attribute.maxLength)) ||
                    Number(attribute.maxLength) < 1 ||
                    Number(attribute.maxLength) > 2000)),
            )
          }
          onClick={() => void publish()}
        >
          <Send className="size-4" />
          {publishing ? "Đang xuất bản" : "Xuất bản phiên bản"}
        </Button>
      </Card>
    </div>
  );
};
