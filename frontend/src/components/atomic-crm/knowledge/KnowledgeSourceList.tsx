import { useState } from "react";
import { ListBase, useListContext, useRedirect, useRefresh } from "ra-core";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BookOpen, FileText, RefreshCw, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { TopToolbar } from "../layout/TopToolbar";
import { getRelativeTimeString } from "../leads/leadUtils";
import type { KnowledgeSource } from "../types";
import { stageLabel, stageTone } from "./stageTone";
import { KnowledgeUpload } from "./KnowledgeUpload";

const flaggedCount = (s: KnowledgeSource): number =>
  s.digest_meta?.flagged_unit_indexes?.length ?? 0;

const KnowledgeSourceRow = ({ source }: { source: KnowledgeSource }) => {
  const redirect = useRedirect();
  return (
    <button
      type="button"
      onClick={() => redirect("show", "knowledge_sources", source.id)}
      className="flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none"
    >
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <FileText className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold">
            {source.file_name}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {getRelativeTimeString(source.updated_at ?? source.created_at)}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              stageTone(source.stage, source.status),
            )}
          >
            {stageLabel(source.stage ?? source.status)}
          </span>
          {source.source && (
            <Badge variant="outline" className="text-[10px]">
              {source.source}
            </Badge>
          )}
          {source.digest_meta?.unit_count != null && (
            <span className="text-[10px] text-muted-foreground">
              {source.digest_meta.unit_count} đơn vị
            </span>
          )}
          {flaggedCount(source) > 0 && (
            <Badge variant="destructive" className="text-[10px]">
              {flaggedCount(source)} cần xem lại
            </Badge>
          )}
        </div>
      </div>
    </button>
  );
};

const KnowledgeSourceListContent = () => {
  const { data, isPending } = useListContext<KnowledgeSource>();
  const refresh = useRefresh();
  const [uploadOpen, setUploadOpen] = useState(false);

  return (
    <>
      <TopToolbar>
        <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground mr-auto">
          Cơ sở kiến thức
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refresh()}
          title="Làm mới (xem tiến trình huấn luyện)"
        >
          <RefreshCw className="size-4" />
        </Button>
        <Button size="sm" onClick={() => setUploadOpen(true)}>
          <Upload className="size-4" />
          Tải lên
        </Button>
      </TopToolbar>
      <KnowledgeUpload open={uploadOpen} onOpenChange={setUploadOpen} />
      <Card className="mt-4 overflow-hidden p-0 py-0">
        <div className="flex h-[calc(100vh-220px)] min-h-[400px] flex-col rounded-[inherit] overflow-hidden">
          {isPending ? (
            <div className="flex flex-col">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-start gap-3 border-b p-4">
                  <Skeleton className="size-8 rounded-md" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-1/2" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                </div>
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
              <BookOpen className="size-10 opacity-50" />
              <p className="text-sm font-medium">Chưa có cơ sở kiến thức</p>
              <p className="text-xs">
                Tải lên tài liệu (PDF, DOCX, XLSX...) để huấn luyện chatbot.
              </p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {data.map((source) => (
                <KnowledgeSourceRow key={source.id} source={source} />
              ))}
            </div>
          )}
        </div>
      </Card>
    </>
  );
};

// ListBase provides the ListContext; the consumer that calls useListContext
// must be a child of ListBase, not a sibling rendered alongside it.
export const KnowledgeSourceList = () => (
  <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
