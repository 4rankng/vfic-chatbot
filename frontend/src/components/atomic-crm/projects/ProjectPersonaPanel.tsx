import { useEffect, useMemo, useState } from "react";
import { useDataProvider, useGetList, useNotify, useRefresh } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Bot, Loader2 } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona, Project } from "../types";

const GLOBAL_DEFAULT_VALUE = "__global_default__";

interface ProjectPersonaPanelProps {
  project: Project;
}

export const ProjectPersonaPanel = ({ project }: ProjectPersonaPanelProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [selected, setSelected] = useState(
    project.default_persona_id ?? GLOBAL_DEFAULT_VALUE,
  );
  const [saving, setSaving] = useState(false);
  const { data: personas, isPending } = useGetList<Persona>("personas", {
    pagination: { page: 1, perPage: 50 },
    sort: { field: "name", order: "ASC" },
  });

  useEffect(() => {
    setSelected(project.default_persona_id ?? GLOBAL_DEFAULT_VALUE);
  }, [project.default_persona_id]);

  const globalPersona = useMemo(
    () => (personas ?? []).find((persona) => persona.is_active),
    [personas],
  );
  const selectedPersona = useMemo(
    () => (personas ?? []).find((persona) => persona.id === selected),
    [personas, selected],
  );
  const hasChanged =
    selected !== (project.default_persona_id ?? GLOBAL_DEFAULT_VALUE);

  const save = async () => {
    if (!hasChanged || saving) return;
    setSaving(true);
    try {
      await dataProvider.update("projects", {
        id: project.id,
        previousData: project,
        data: {
          default_persona_id:
            selected === GLOBAL_DEFAULT_VALUE ? null : selected,
        },
      });
      notify("Đã cập nhật Agent cho dự án.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="mt-4 max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span>Agent chatbot</span>
          <Badge variant="outline" className="gap-1">
            <Bot className="size-3.5" />
            {project.default_persona_id ? "Gán riêng" : "Theo mặc định"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-0">
        {isPending ? (
          <Skeleton className="h-9 w-full" />
        ) : (
          <>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="project-persona">Agent dùng cho dự án</Label>
              <Select value={selected} onValueChange={setSelected}>
                <SelectTrigger id="project-persona" className="w-full">
                  <SelectValue placeholder="Chọn Agent" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={GLOBAL_DEFAULT_VALUE}>
                    Mặc định toàn hệ thống
                    {globalPersona ? `: ${globalPersona.name}` : ""}
                  </SelectItem>
                  {(personas ?? []).map((persona) => (
                    <SelectItem key={persona.id} value={persona.id}>
                      {persona.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="text-sm text-muted-foreground">
              {selected === GLOBAL_DEFAULT_VALUE
                ? "Dự án này dùng Agent mặc định toàn hệ thống."
                : `Dự án này sẽ dùng "${selectedPersona?.name ?? "Agent đã chọn"}" thay cho mặc định.`}
            </div>
            <Button
              type="button"
              className="w-fit"
              onClick={save}
              disabled={!hasChanged || saving}
            >
              {saving && <Loader2 className="size-4 animate-spin" />}
              Lưu Agent dự án
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
};
