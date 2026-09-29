import { memo, useMemo, useState } from "react";
import {
  ListBase,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
  useTranslate,
} from "ra-core";
import { Button } from "@/components/base/buttons/button";
import { InputBase } from "@/components/base/input/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ListPagination } from "@/components/admin/list-pagination";
import {
  BotMessageSquare,
  ChevronRight,
  Hash,
  Plus,
  Search,
} from "lucide-react";
import type { Persona } from "../types";
import { EmptyState } from "../kit";
import { activatePersona } from "./personaService";
import { PersonaWorkspaceShell } from "./PersonaWorkspaceShell";
import { PersonaStudioOverview } from "./presentation/PersonaStudioOverview";
import {
  getEffectiveAdapterLabels,
  getPersonaDerivedStats,
  getScopeLabel,
  numberFormatter,
} from "./presentation/persona-presentation";

type PersonaListProps = {
  embedded?: boolean;
};

type PersonaRowProps = {
  persona: Persona;
  isSelected: boolean;
  onSelect: (persona: Persona) => void;
};

const PersonaBubble = memo(
  ({ persona, isSelected, onSelect }: PersonaRowProps) => {
    const translate = useTranslate();
    const stats = getPersonaDerivedStats(persona);
    const scopeLabel = getScopeLabel(persona, stats, translate);

    return (
      <article
        className={`tt-list-row persona-directory-row ${persona.is_active ? "is-active" : ""} ${
          isSelected ? "is-selected" : ""
        }`}
      >
        <button
          type="button"
          className="persona-directory-main"
          aria-pressed={isSelected}
          onClick={() => onSelect(persona)}
        >
          <span className="persona-directory-avatar" aria-hidden="true">
            <BotMessageSquare className="size-3.5" />
          </span>
          <span className="persona-directory-copy">
            <span className="persona-directory-title-line">
              <span className="min-w-0">
                <span className="persona-directory-name">{persona.name}</span>
                <span className="persona-directory-slug">
                  <Hash className="size-3" />
                  {persona.slug}
                </span>
              </span>
            </span>
            <span className="persona-directory-scope">{scopeLabel}</span>
          </span>
          <ChevronRight className="persona-directory-chevron size-4" />
        </button>
      </article>
    );
  },
);
PersonaBubble.displayName = "PersonaBubble";

const PersonaListContent = ({ embedded = false }: PersonaListProps) => {
  const { data, isPending, total } = useListContext<Persona>();
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
  const translate = useTranslate();
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(
    null,
  );
  const [searchQuery, setSearchQuery] = useState("");
  const personas = useMemo(() => data ?? [], [data]);
  const filteredPersonas = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) return personas;
    return personas.filter((persona) => {
      const searchable = [
        persona.name,
        persona.slug,
        persona.notes ?? "",
        ...getEffectiveAdapterLabels(persona),
      ]
        .join(" ")
        .toLowerCase();
      return searchable.includes(normalizedQuery);
    });
  }, [personas, searchQuery]);
  const defaultPersona = useMemo(
    () => personas.find((persona) => persona.is_active) ?? personas[0] ?? null,
    [personas],
  );
  const selectedPersona = useMemo(() => {
    if (!searchQuery.trim()) {
      return (
        personas.find((persona) => persona.id === selectedPersonaId) ??
        defaultPersona
      );
    }
    return (
      filteredPersonas.find((persona) => persona.id === selectedPersonaId) ??
      filteredPersonas.find((persona) => persona.is_active) ??
      filteredPersonas[0] ??
      null
    );
  }, [
    defaultPersona,
    filteredPersonas,
    personas,
    searchQuery,
    selectedPersonaId,
  ]);
  const selectedPersonaStats = selectedPersona
    ? getPersonaDerivedStats(selectedPersona)
    : null;
  const totalCount = total ?? personas.length;
  const isEmpty = !isPending && personas.length === 0;
  const onActivatePersona = async (persona: Persona) => {
    try {
      await activatePersona(persona.id);
      notify("Đã đặt làm mặc định.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  const content = (
    <div className="persona-workspace-content">
      <div className="persona-page-shell">
        {isEmpty ? (
          <EmptyState
            icon={<BotMessageSquare className="size-6" aria-hidden="true" />}
            title="Tạo giọng Agent đầu tiên"
            description="Thiết lập một hồ sơ để chatbot biết cách chào hỏi, hỏi thông tin và chuyển cuộc trò chuyện cho đội tuyển dụng khi cần."
            action={
              <Button
                type="button"
                data-slot="button"
                className="uu-scope h-9 rounded-[8px]"
                onClick={() => redirect("create", "personas")}
                iconLeading={Plus}
              >
                {translate("personas.create_agent")}
              </Button>
            }
          />
        ) : (
          <>
            <div className="persona-studio-layout persona-agent-stack">
              <section
                className="persona-agent-picker"
                aria-label="Danh sách Agent"
              >
                <div className="persona-panel-header">
                  {/* `a-c-tables-08` header block: the title, then the muted
                      count line. The 224px embedded rail has no room for the
                      two side by side, so the count sits beneath the title. */}
                  <div className="persona-panel-heading">
                    <div className="min-w-0">
                      <h2>Agent</h2>
                      {!isPending ? (
                        <p className="text-[length:var(--text-body-sm)] font-medium whitespace-nowrap tabular-nums text-[var(--workspace-ink-muted)]">
                          {numberFormatter.format(totalCount)} hồ sơ
                        </p>
                      ) : null}
                    </div>
                  </div>
                  <Button
                    type="button"
                    data-slot="button"
                    className="persona-create-action tt-btn-touch uu-scope"
                    onClick={() => redirect("create", "personas")}
                    iconLeading={Plus}
                  >
                    {translate("personas.create_agent")}
                  </Button>
                </div>

                <label className="persona-studio-command">
                  <Search className="size-4" aria-hidden="true" />
                  <InputBase
                    type="search"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder="Tìm Agent"
                    aria-label="Tìm Agent"
                    wrapperClassName="min-w-0 flex-1 rounded-none bg-transparent! shadow-none! ring-0!"
                  />
                </label>

                {isPending ? (
                  <div className="persona-directory-loading">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="persona-directory-skeleton">
                        <Skeleton className="size-10 rounded-[10px]" />
                        <div className="flex-1 space-y-2">
                          <Skeleton className="h-4 w-1/3" />
                          <Skeleton className="h-3 w-1/2" />
                          <Skeleton className="h-3 w-2/3" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  /* `a-c-tables-08` treats the list as one framed surface. The
                     Agent rail is a card list, not a table, so the frame holds
                     the cards instead of the rows carrying their own boxes. */
                  <div className="persona-directory-surface overflow-hidden rounded-sm border border-[var(--workspace-border)] bg-[var(--card)] p-1.5">
                    <div className="tt-list persona-directory-list persona-agent-bubbles">
                      {filteredPersonas.length > 0 ? (
                        filteredPersonas.map((p) => (
                          <PersonaBubble
                            key={p.id}
                            persona={p}
                            isSelected={selectedPersona?.id === p.id}
                            onSelect={(persona) =>
                              setSelectedPersonaId(persona.id)
                            }
                          />
                        ))
                      ) : (
                        <p className="persona-empty-results text-[length:var(--text-body-sm)] text-[var(--workspace-ink-muted)]">
                          Không tìm thấy Agent phù hợp.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </section>

              <div className="persona-studio-body">
                <PersonaStudioOverview
                  persona={selectedPersona}
                  stats={selectedPersonaStats}
                  onActivate={onActivatePersona}
                  onEdit={(persona) => redirect("edit", "personas", persona.id)}
                />
              </div>
            </div>

            {totalCount > 25 ? (
              <ListPagination
                rowsPerPageOptions={[10, 25, 50, 100]}
                className="persona-pagination"
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );

  if (embedded) return content;

  return <PersonaWorkspaceShell>{content}</PersonaWorkspaceShell>;
};

export const PersonaList = ({ embedded = false }: PersonaListProps) => (
  <ListBase
    resource="personas"
    perPage={25}
    sort={{ field: "name", order: "ASC" }}
  >
    <PersonaListContent embedded={embedded} />
  </ListBase>
);
