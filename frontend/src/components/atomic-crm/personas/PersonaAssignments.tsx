import { useState } from "react";
import { useDataProvider, useGetList, useNotify, useRefresh } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChevronLeft,
  ChevronRight,
  Globe2,
  Loader2,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona, Project } from "../types";
import {
  activatePersona,
  assignPersonaToAllProjects,
} from "@/lib/vfic/knowledgeService";

interface PersonaAssignmentsProps {
  persona: Persona;
}

export const PersonaAssignments = ({ persona }: PersonaAssignmentsProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [savingProjectId, setSavingProjectId] = useState<string | null>(null);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [activating, setActivating] = useState(false);
  const [page, setPage] = useState(1);
  const perPage = 25;
  const {
    data: projects,
    isPending,
    total = 0,
  } = useGetList<Project>("projects", {
    pagination: { page, perPage },
    sort: { field: "name", order: "ASC" },
  });
  const totalPages = Math.max(1, Math.ceil(total / perPage));

  const updateProjectPersona = async (
    project: Project,
    defaultPersonaId: string | null,
  ) => {
    setSavingProjectId(project.id);
    try {
      await dataProvider.update("projects", {
        id: project.id,
        previousData: project,
        data: { default_persona_id: defaultPersonaId },
      });
      notify("Đã cập nhật Agent cho dự án.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSavingProjectId(null);
    }
  };

  const assignToAllProjects = async () => {
    if (bulkSaving) return;
    setBulkSaving(true);
    try {
      const result = await assignPersonaToAllProjects(persona.id);
      notify(`Đã gán Agent cho tất cả dự án (${result.updated} cập nhật).`, {
        type: "success",
      });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setBulkSaving(false);
    }
  };

  const setGlobalDefault = async () => {
    if (activating || persona.is_active) return;
    setActivating(true);
    try {
      await activatePersona(persona.id);
      notify("Đã đặt làm Agent mặc định toàn hệ thống.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setActivating(false);
    }
  };

  return (
    <Card className="mt-1 w-full rounded-lg py-0 shadow-sm">
      <CardHeader className="border-b px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Workflow className="size-4 text-primary" />
              Phạm vi sử dụng Agent
            </CardTitle>
            <CardDescription className="mt-1.5">
              Chọn dự án dùng Agent này hoặc đặt làm mặc định toàn hệ thống.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {persona.is_active ? (
              <Badge
                variant="outline"
                className="gap-1 border-primary/20 bg-primary/5 text-primary"
              >
                <Globe2 className="size-3.5" />
                Mặc định toàn hệ thống
              </Badge>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={setGlobalDefault}
                disabled={activating}
              >
                {activating ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Globe2 className="size-4" />
                )}
                Đặt mặc định
              </Button>
            )}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={assignToAllProjects}
              disabled={bulkSaving || total === 0}
            >
              {bulkSaving ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              Gán tất cả dự án
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 px-4 py-4 sm:px-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="rounded-lg border bg-muted/15 p-4">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            Tổng dự án
          </div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">
            {total}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Danh sách bên phải được phân trang từ backend. Dùng nút gán tất cả
            để áp dụng cho toàn bộ dự án.
          </p>
        </div>

        <div className="overflow-hidden rounded-lg border bg-background/70">
          <div className="flex h-10 items-center justify-between border-b bg-muted/20 px-4">
            <span className="text-xs font-semibold uppercase text-muted-foreground">
              Dự án
            </span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {(projects ?? []).length} mục trên trang
            </span>
          </div>
          <div className="max-h-[360px] overflow-y-auto">
            {isPending ? (
              <div className="space-y-3 p-4">
                {Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-8 w-full" />
                ))}
              </div>
            ) : (projects ?? []).length === 0 ? (
              <div className="p-4 text-sm text-muted-foreground">
                Chưa có dự án để gán Agent.
              </div>
            ) : (
              <div className="divide-y">
                {(projects ?? []).map((project) => {
                  const checked = project.default_persona_id === persona.id;
                  const saving = savingProjectId === project.id;
                  return (
                    <label
                      key={project.id}
                      className="flex min-h-12 items-center gap-3 px-4 py-3 text-sm"
                    >
                      <Checkbox
                        checked={checked}
                        disabled={saving || bulkSaving}
                        onCheckedChange={(value) =>
                          updateProjectPersona(
                            project,
                            value === true ? persona.id : null,
                          )
                        }
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">
                          {project.name}
                        </span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {project.slug}
                        </span>
                      </span>
                      {saving && <Loader2 className="size-4 animate-spin" />}
                      {checked && (
                        <Badge variant="outline" className="shrink-0">
                          Đang gán
                        </Badge>
                      )}
                    </label>
                  );
                })}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between gap-3 border-t bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
            <span className="tabular-nums">
              Trang {page} / {totalPages} ({total} dự án)
            </span>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-7"
                disabled={isPending || page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-7"
                disabled={isPending || page >= totalPages}
                onClick={() =>
                  setPage((value) => Math.min(totalPages, value + 1))
                }
              >
                <ChevronRight className="size-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
