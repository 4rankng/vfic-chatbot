import { type ReactNode } from "react";
import { ShowBase, useRecordContext } from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import type { KnowledgeSource } from "../types";
import { formatDateTime } from "../automation/botRunMeta";
import { statusTone } from "./statusTone";

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
  if (!source) return null;

  return (
    <div className="mx-auto mt-4 max-w-3xl">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b px-4 py-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="size-4 text-muted-foreground" />
            {source.file_name}
          </CardTitle>
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
              statusTone(source.status),
            )}
          >
            {source.status || "—"}
          </span>
        </CardHeader>
        <CardContent className="flex flex-col px-4 py-2">
          <Field label="Tên tài liệu" value={source.file_name} />
          <Field label="Nguồn" value={source.source} />
          <Field
            label="Drive file ID"
            value={
              source.drive_file_id ? (
                <span className="font-mono text-xs break-all">
                  {source.drive_file_id}
                </span>
              ) : null
            }
          />
          <Field label="Phiên bản" value={source.version || "—"} />
          <Field label="Ngày tạo" value={formatDateTime(source.created_at)} />
          <Field
            label="Ngày cập nhật"
            value={formatDateTime(source.updated_at)}
          />
        </CardContent>
      </Card>
    </div>
  );
};

export const KnowledgeSourceShow = () => (
  <ShowBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Nguồn kiến thức</h2>
    </TopToolbar>
    <KnowledgeSourceShowContent />
  </ShowBase>
);
