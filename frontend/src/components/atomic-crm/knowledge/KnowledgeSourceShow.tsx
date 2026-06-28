import { type ReactNode } from "react";
import {
  ShowBase,
  useGetList,
  useNotify,
  useRecordContext,
  useRedirect,
  useRefresh,
} from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Archive, BookOpen, Pencil, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { KnowledgeSource, Project } from "../types";
import { formatDateTime } from "../automation/botRunMeta";
import { stageLabel, stageTone } from "./stageTone";
import { archiveKnowledge, reindexKnowledge } from "@/lib/vfic/knowledgeService";
import { DeleteButton } from "@/components/admin";

const Field = ({ label, value }: { label: string; value?: ReactNode }) => (
  <div className="flex flex-col gap-1 border-b py-3 last:border-0">
    <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
      {label}
    </span>
    <span className="text-sm">{value ?? "—"}</span>
  </div>
);

const KnowledgeSourceShowContent = () => {
  const source = useRecordContext<KnowledgeSource>();
  const notify = useNotify();
  const refresh = useRefresh();
  const redirect = useRedirect();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
  });
  if (!source) return null;

  const projectName =
    source.project_id &&
    (projects ?? []).find((p) => p.id === source.project_id)?.name;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      notify(ok, { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  const flagged = source.digest_meta?.flagged_unit_indexes?.length ?? 0;

  return (
    <div className="mx-auto mt-4 max-w-3xl">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b px-4 py-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="size-4 text-muted-foreground" />
            {source.file_name}
          </CardTitle>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
                stageTone(source.stage, source.status),
              )}
            >
              {stageLabel(source.stage ?? source.status)}
            </span>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col px-4 py-2">
          <Field label="Tên tài liệu" value={source.file_name} />
          <Field label="Nguồn" value={source.source} />
          <Field label="Dự án" value={projectName ?? source.project_id} />
          <Field label="Loại tệp" value={source.mime_type} />
          <Field
            label="Giai đoạn huấn luyện"
            value={stageLabel(source.stage)}
          />
          {source.digest_summary && (
            <Field label="Tóm tắt (LLM)" value={source.digest_summary} />
          )}
          {source.digest_meta?.unit_count != null && (
            <Field
              label="Số đơn vị kiến thức"
              value={`${source.digest_meta.unit_count} (cần xem lại: ${flagged})`}
            />
          )}
          {source.error && (
            <Field
              label="Lỗi"
              value={<span className="text-rose-600">{source.error}</span>}
            />
          )}
          <Field label="Ngày tạo" value={formatDateTime(source.created_at)} />
          <Field
            label="Ngày cập nhật"
            value={formatDateTime(source.updated_at)}
          />

          <div className="flex flex-wrap gap-2 py-3">
            <Button
              size="sm"
              variant="outline"
              onClick={() => redirect("edit", "knowledge_sources", source.id)}
            >
              <Pencil className="size-4" />
              Sửa
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                run(
                  () => reindexKnowledge(source.id),
                  "Đã đưa vào hàng huấn luyện lại.",
                )
              }
            >
              <RefreshCw className="size-4" />
              Huấn luyện lại
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                run(
                  () => archiveKnowledge(source.id),
                  "Đã lưu trữ. Agent sẽ không dùng nguồn này nữa.",
                )
              }
            >
              <Archive className="size-4" />
              Lưu trữ
            </Button>
            <DeleteButton
              label="Xóa"
              size="sm"
              successMessage="Đã xóa tài liệu."
              redirect="list"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export const KnowledgeSourceShow = () => (
  <ShowBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Cơ sở kiến thức</h2>
    </TopToolbar>
    <KnowledgeSourceShowContent />
  </ShowBase>
);
