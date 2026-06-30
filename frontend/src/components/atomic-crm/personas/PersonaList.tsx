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
import { Plus, Sparkles, Zap } from "lucide-react";
import { TopToolbar } from "../layout/TopToolbar";
import type { Persona } from "../types";
import { activatePersona } from "@/lib/vfic/knowledgeService";

const PersonaRow = ({ persona }: { persona: Persona }) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();

  const onActivate = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await activatePersona(persona.id);
      notify("Đã đặt làm mặc định.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  const assignedLabel =
    persona.assigned_projects && persona.assigned_projects.length > 0
      ? persona.assigned_projects.map((p) => p.name).join(", ")
      : null;

  return (
    <button
      type="button"
      onClick={() => redirect("edit", "personas", persona.id)}
      className="flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none"
    >
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Sparkles className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold">{persona.name}</span>
          <div className="flex shrink-0 items-center gap-1.5">
            {persona.is_active && (
              <Badge
                variant="outline"
                className="border-primary/20 bg-primary/5 text-[10px] text-primary"
              >
                Mặc định
              </Badge>
            )}
            {assignedLabel && (
              <Badge variant="outline" className="text-[10px]">
                Gán: {assignedLabel}
              </Badge>
            )}
          </div>
        </div>
        <p className="mt-0.5 line-clamp-1 font-mono text-xs text-muted-foreground">
          {persona.slug}
        </p>
      </div>
      {!persona.is_active && (
        <div onClick={(e) => e.stopPropagation()}>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={onActivate}
          >
            <Zap className="size-3.5" />
            Đặt mặc định
          </Button>
        </div>
      )}
    </button>
  );
};

const PersonaListContent = () => {
  const { data, isPending } = useListContext<Persona>();
  const redirect = useRedirect();

  return (
    <div className="px-4 py-5 md:px-0 md:py-0">
      <TopToolbar>
        <h2 className="mr-auto font-display text-2xl font-extrabold uppercase tracking-wide text-foreground sm:text-4xl">
          Agent
        </h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="bg-card text-foreground hover:bg-muted"
          onClick={() => redirect("create", "personas")}
        >
          <Plus className="size-4 text-primary" />
          Tạo Agent
        </Button>
      </TopToolbar>
      <Card className="mt-4 overflow-hidden p-0 py-0">
        <div className="flex h-[min(620px,calc(100dvh-160px))] min-h-[400px] flex-col overflow-hidden rounded-[inherit] lg:h-[calc(100vh-220px)]">
          {isPending ? (
            <div className="flex flex-col">
              {Array.from({ length: 4 }).map((_, i) => (
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
              <Sparkles className="size-10 opacity-50" />
              <p className="text-sm font-medium">Chưa có Agent nào</p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {data.map((p) => (
                <PersonaRow key={p.id} persona={p} />
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
};

export const PersonaList = () => (
  <ListBase perPage={100} sort={{ field: "name", order: "ASC" }}>
    <PersonaListContent />
  </ListBase>
);
