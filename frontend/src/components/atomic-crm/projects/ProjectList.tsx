import {
  ListBase,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
} from "ra-core";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Boxes, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { TopToolbar } from "../layout/TopToolbar";
import type { Project } from "../types";
import { reindexProject } from "@/lib/vfic/knowledgeService";

const ProjectRow = ({ project }: { project: Project }) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();

  const onReindex = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await reindexProject(project.id);
      notify("Đã làm mới thẻ danh mục dự án.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <button
      type="button"
      onClick={() => redirect("edit", "projects", project.id)}
      className="flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none"
    >
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Boxes className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold">{project.name}</span>
          <Badge
            variant={project.is_active ? "default" : "outline"}
            className="text-[10px]"
          >
            {project.is_active ? "Đang hoạt động" : "Tắt"}
          </Badge>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span className="font-mono">{project.slug}</span>
          {project.index_card?.location && (
            <span>• {project.index_card.location}</span>
          )}
        </div>
        {project.summary && (
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {project.summary}
          </p>
        )}
        <div className="mt-1.5" onClick={(e) => e.stopPropagation()}>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={onReindex}
          >
            <RefreshCw className="size-3.5" />
            Làm mới thẻ
          </Button>
        </div>
      </div>
    </button>
  );
};

const ProjectListContent = () => {
  const { data, isPending } = useListContext<Project>();
  const refresh = useRefresh();

  return (
    <>
      <TopToolbar>
        <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground mr-auto">
          Dự án
        </h2>
        <Button variant="outline" size="sm" onClick={() => refresh()}>
          <RefreshCw className="size-4" />
        </Button>
      </TopToolbar>
      <Card className="mt-4 overflow-hidden p-0 py-0">
        <div
          className={cn(
            "flex h-[calc(100vh-220px)] min-h-[400px] flex-col rounded-[inherit] overflow-hidden",
          )}
        >
          {isPending ? (
            <div className="flex flex-col">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-start gap-3 border-b p-4">
                  <Skeleton className="size-8 rounded-md" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-1/3" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                </div>
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
              <Boxes className="size-10 opacity-50" />
              <p className="text-sm font-medium">Chưa có dự án nào</p>
              <p className="text-xs">
                Tạo một dự án (sản phẩm) để tải cơ sở kiến thức lên.
              </p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {data.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </div>
          )}
        </div>
      </Card>
    </>
  );
};

export const ProjectList = () => (
  <ListBase perPage={100} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
