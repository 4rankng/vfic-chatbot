import { useEffect, useMemo, useState } from "react";
import {
  useDataProvider,
  useGetList,
  useGetOne,
  useNotify,
  useRefresh,
} from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Bot, Check, ChevronsUpDown, Loader2 } from "lucide-react";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona, Project } from "../types";
import { cn } from "@/lib/utils";

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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [personaSearch, setPersonaSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const { data: personas, isPending } = useGetList<Persona>("personas", {
    pagination: { page: 1, perPage: 25 },
    sort: { field: "name", order: "ASC" },
    filter: personaSearch.trim() ? { q: personaSearch.trim() } : {},
  });

  useEffect(() => {
    setSelected(project.default_persona_id ?? GLOBAL_DEFAULT_VALUE);
  }, [project.default_persona_id]);

  const { data: selectedPersonaRecord } = useGetOne<Persona>(
    "personas",
    { id: project.default_persona_id! },
    { enabled: !!project.default_persona_id },
  );

  const selectedPersona = useMemo(
    () =>
      selected === GLOBAL_DEFAULT_VALUE
        ? null
        : ((personas ?? []).find((persona) => persona.id === selected) ??
          selectedPersonaRecord),
    [personas, selected, selectedPersonaRecord],
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
        <CardTitle className="flex items-center justify-between gap-2 text-section-title">
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
              <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                <PopoverTrigger asChild>
                  <Button
                    id="project-persona"
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-expanded={pickerOpen}
                    className="w-full justify-between"
                  >
                    <span className="truncate">
                      {selected === GLOBAL_DEFAULT_VALUE
                        ? "System Default"
                        : (selectedPersona?.name ?? "Chọn Agent")}
                    </span>
                    <ChevronsUpDown className="size-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  className="w-[min(420px,calc(100vw-3rem))] p-0"
                >
                  <Command shouldFilter={false}>
                    <CommandInput
                      value={personaSearch}
                      onValueChange={setPersonaSearch}
                      placeholder="Tìm Agent..."
                    />
                    <CommandList>
                      <CommandGroup>
                        <CommandItem
                          value={GLOBAL_DEFAULT_VALUE}
                          onSelect={() => {
                            setSelected(GLOBAL_DEFAULT_VALUE);
                            setPickerOpen(false);
                            setPersonaSearch("");
                          }}
                        >
                          <Check
                            className={cn(
                              "size-4",
                              selected !== GLOBAL_DEFAULT_VALUE && "opacity-0",
                            )}
                          />
                          System Default
                        </CommandItem>
                        {(personas ?? []).map((persona) => (
                          <CommandItem
                            key={persona.id}
                            value={`${persona.name} ${persona.slug}`}
                            onSelect={() => {
                              setSelected(persona.id);
                              setPickerOpen(false);
                              setPersonaSearch("");
                            }}
                          >
                            <Check
                              className={cn(
                                "size-4",
                                selected !== persona.id && "opacity-0",
                              )}
                            />
                            <span className="min-w-0 flex-1 truncate">
                              {persona.name}
                            </span>
                            <span className="font-mono text-caption text-muted-foreground">
                              {persona.slug}
                            </span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
            <div className="text-body text-muted-foreground">
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
