import { useMemo, useState } from "react";
import { useDataProvider, useGetList, useNotify, useRefresh } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Globe2, Loader2, Sparkles } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona, Project } from "../types";
import { activatePersona } from "@/lib/vfic/knowledgeService";

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
  const { data: projects, isPending } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 50 },
    sort: { field: "name", order: "ASC" },
  });

  const assignedProjects = useMemo(
    () =>
      (projects ?? []).filter(
        (project) => project.default_persona_id === persona.id,
      ),
    [persona.id, projects],
  );

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
    const rows = projects ?? [];
    if (rows.length === 0 || bulkSaving) return;
    setBulkSaving(true);
    try {
      const results = await Promise.allSettled(
        rows.map((project) =>
          dataProvider.update("projects", {
            id: project.id,
            previousData: project,
            data: { default_persona_id: persona.id },
          }),
        ),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = results.length - ok;
      if (fail === 0) {
        notify(`Đã gán Agent cho ${ok} dự án.`, { type: "success" });
      } else {
        notify(
          `Đã gán ${ok}/${results.length} dự án. ${fail} dự án thất bại.`,
          { type: "warning" },
        );
      }
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
    <Card className="mt-4 max-w-4xl">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span>Phạm vi sử dụng Agent</span>
          <div className="flex flex-wrap gap-2">
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
              disabled={
                bulkSaving || isPending || (projects ?? []).length === 0
              }
            >
              {bulkSaving ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              Gán tất cả dự án
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-0">
        <div className="text-sm text-muted-foreground">
          {assignedProjects.length > 0
            ? `${assignedProjects.length} dự án đang dùng Agent này.`
            : "Chưa có dự án nào gán riêng Agent này."}
        </div>

        <div className="overflow-hidden rounded-md border">
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
      </CardContent>
    </Card>
  );
};
