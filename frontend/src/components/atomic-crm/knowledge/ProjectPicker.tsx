import { useMemo, useState } from "react";
import {
  useDataProvider,
  useGetList,
  useGetOne,
  useNotify,
  useRefresh,
} from "ra-core";
import { Check, ChevronsUpDown, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { Project } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { normalizeSearch, slugifyProject } from "./projectPickerUtils";
export const ProjectPicker = ({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [localProjects, setLocalProjects] = useState<Project[]>([]);
  const trimmedSearch = search.trim();
  const { data: selectedProjectRecord } = useGetOne<Project>(
    "projects",
    { id: value! },
    { enabled: !!value },
  );
  const { data: searchedProjects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 25 },
    sort: { field: "name", order: "ASC" },
    filter: trimmedSearch ? { q: trimmedSearch } : {},
  });

  const availableProjects = useMemo(() => {
    const map = new Map<string, Project>();
    for (const project of searchedProjects ?? []) {
      map.set(String(project.id), project);
    }
    if (!trimmedSearch && selectedProjectRecord) {
      map.set(String(selectedProjectRecord.id), selectedProjectRecord);
    }
    for (const project of localProjects) map.set(String(project.id), project);
    return Array.from(map.values()).sort((a, b) =>
      a.name.localeCompare(b.name, "vi"),
    );
  }, [localProjects, searchedProjects, selectedProjectRecord, trimmedSearch]);

  const selectedProject = availableProjects.find(
    (project) => String(project.id) === value,
  );
  const normalizedSearch = normalizeSearch(trimmedSearch);
  const exactMatch = availableProjects.some(
    (project) => normalizeSearch(project.name) === normalizedSearch,
  );
  const canCreate = trimmedSearch.length > 0 && !exactMatch;
  const createHelpText = !trimmedSearch
    ? "Nhập tên dự án để tạo mới."
    : exactMatch
      ? "Dự án này đã tồn tại."
      : `Tạo dự án "${trimmedSearch}"`;

  const selectProject = (projectId: string) => {
    onChange(projectId);
    setOpen(false);
    setSearch("");
  };

  const createProject = async () => {
    if (!canCreate || creating) return;
    setCreating(true);
    try {
      const response = await dataProvider.create("projects", {
        data: {
          name: trimmedSearch,
          slug: slugifyProject(trimmedSearch),
          is_active: true,
        },
      });
      const project = response.data as Project;
      setLocalProjects((current) => [...current, project]);
      onChange(String(project.id));
      notify("Đã tạo dự án.", { type: "success" });
      setOpen(false);
      setSearch("");
      refresh();
    } catch (err) {
      notify(`Tạo dự án thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setCreating(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-10 w-full justify-between rounded-[9px] border-border bg-background px-3 text-sm font-normal"
        >
          <span className="truncate">
            {selectedProject?.name ?? "Chọn dự án"}
          </span>
          <ChevronsUpDown className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[min(420px,calc(100vw-3rem))] p-0"
      >
        <Command
          shouldFilter={false}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              canCreate &&
              availableProjects.length === 0
            ) {
              event.preventDefault();
              void createProject();
            }
          }}
        >
          <CommandInput
            value={search}
            onValueChange={setSearch}
            placeholder="Tìm hoặc tạo dự án..."
          />
          <CommandList>
            {(availableProjects.length > 0 || trimmedSearch) && (
              <CommandGroup>
                {availableProjects.length > 0 ? (
                  availableProjects.map((project) => (
                    <CommandItem
                      key={project.id}
                      value={`${project.name} ${project.slug}`}
                      onSelect={() => selectProject(String(project.id))}
                    >
                      <Check
                        className={cn(
                          "size-4",
                          value !== String(project.id) && "opacity-0",
                        )}
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {project.name}
                      </span>
                      <span className="kb-mono shrink-0 text-caption text-muted-foreground">
                        {project.slug}
                      </span>
                    </CommandItem>
                  ))
                ) : (
                  <div className="px-2 py-3 text-sm text-muted-foreground">
                    Không tìm thấy dự án.
                  </div>
                )}
              </CommandGroup>
            )}
            {canCreate && (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value={`create-${trimmedSearch}`}
                    onSelect={createProject}
                    disabled={creating}
                  >
                    {creating ? (
                      <RefreshCw className="size-4 animate-spin" />
                    ) : (
                      <Plus className="size-4" />
                    )}
                    <span className="truncate">
                      Tạo dự án "{trimmedSearch}"
                    </span>
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
        <div className="border-t border-border p-2">
          <Button
            type="button"
            variant={canCreate ? "default" : "ghost"}
            className="h-9 w-full justify-start rounded-[8px] px-2 text-sm"
            disabled={!canCreate || creating}
            onClick={() => void createProject()}
          >
            {creating ? (
              <RefreshCw className="size-4 animate-spin" />
            ) : (
              <Plus className="size-4" />
            )}
            <span className="truncate">{createHelpText}</span>
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
