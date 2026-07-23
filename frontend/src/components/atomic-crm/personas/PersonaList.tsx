import { memo, useMemo, useState } from "react";
import {
  ListBase,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
} from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ListPagination } from "@/components/admin/list-pagination";
import {
  BotMessageSquare,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Hash,
  Pencil,
  Plus,
  Search,
  Zap,
} from "lucide-react";
import { ADAPTER_PROVIDER_LABELS, type Persona } from "../types";
import { activatePersona } from "./personaService";
import { PersonaWorkspaceShell } from "./PersonaWorkspaceShell";
import {
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
  getPersonaSectionSummaries,
} from "./domain/personaMarkdown";
import {
  PERSONA_SECTION_TOTAL,
  getPersonaReadinessPercent,
} from "./domain/personaReadiness";
const FOLLOWUP_TOTAL = 3;
const FOLLOWUP_KEYS = ["hot", "warm", "not_interested"] as const;
const FOLLOWUP_LABELS: Record<(typeof FOLLOWUP_KEYS)[number], string> = {
  hot: "Hot",
  warm: "Warm",
  not_interested: "Cold",
};

type PersonaDerivedStats = {
  adapterCount: number;
  adapterLabels: string[];
  contentLength: number;
  followupEnabledCount: number;
  sectionCount: number;
};

type PersonaListProps = {
  embedded?: boolean;
};

const numberFormatter = new Intl.NumberFormat("vi-VN");
const dateFormatter = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const getEffectiveAdapterLabels = (persona: Persona) =>
  (persona.effective_adapter_providers ?? []).map(
    (provider) => ADAPTER_PROVIDER_LABELS[provider],
  );

const getPersonaDerivedStats = (persona: Persona): PersonaDerivedStats => ({
  adapterCount: getEffectiveAdapterLabels(persona).length,
  adapterLabels: getEffectiveAdapterLabels(persona),
  contentLength: getPersonaAuthoredContentLength(persona.body_md),
  followupEnabledCount: FOLLOWUP_KEYS.filter(
    (key) => persona.followup_rules?.[key]?.enabled,
  ).length,
  sectionCount: getCompletedPersonaSectionCount(persona.body_md),
});

const getScopeLabel = (persona: Persona, stats: PersonaDerivedStats) => {
  if (stats.adapterCount > 0) {
    return `${stats.adapterCount} adapter`;
  }
  if (persona.is_active) {
    return "Mặc định";
  }
  return "Dự phòng";
};

const getAdapterScopeSummary = (
  persona: Persona,
  stats: PersonaDerivedStats,
) => {
  if (stats.adapterCount > 0) {
    return stats.adapterLabels.join(", ");
  }
  if (persona.is_active) {
    return "Chưa có adapter gán riêng, sẽ kế thừa Agent mặc định này.";
  }
  return "Chưa adapter nào dùng Agent này.";
};

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Chưa rõ";
  return dateFormatter.format(date);
};

const splitPersonaRuleItems = (content: string) =>
  content
    .trim()
    .replace(/\s+/g, " ")
    .split(/(?:^|(?<=[.:?])\s+)-\s+/u)
    .map((item) => item.trim())
    .filter(Boolean);

const PersonaFormattedContent = ({
  content,
  emptyText,
}: {
  content: string;
  emptyText: string;
}) => {
  const items = splitPersonaRuleItems(content);
  const hasListMarkers = /(?:^|\n)\s*-\s+/u.test(content);

  if (items.length === 0) {
    return <p>{emptyText}</p>;
  }

  if (items.length === 1 && !hasListMarkers) {
    return <p>{items[0]}</p>;
  }

  return (
    <ul className="persona-rule-list">
      {items.map((item, index) => {
        const separatorIndex = item.indexOf(":");
        const hasLeadLabel = separatorIndex > 0 && separatorIndex <= 72;
        const label = hasLeadLabel ? item.slice(0, separatorIndex + 1) : null;
        const detail = hasLeadLabel
          ? item.slice(separatorIndex + 1).trim()
          : item;

        return (
          <li key={`${index}-${item}`}>
            {label ? <strong>{label}</strong> : null}
            {detail ? <span>{detail}</span> : null}
          </li>
        );
      })}
    </ul>
  );
};

const getContentPreview = (content: string) =>
  content
    .split("\n")
    .map((line) => line.trim().replace(/^[-*#\d.)\s]+/, ""))
    .find(Boolean) ?? "Chưa có nội dung";

type PersonaRowProps = {
  persona: Persona;
  isSelected: boolean;
  onSelect: (persona: Persona) => void;
};

const PersonaBubble = memo(
  ({ persona, isSelected, onSelect }: PersonaRowProps) => {
    const stats = getPersonaDerivedStats(persona);
    const scopeLabel = getScopeLabel(persona, stats);

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

const PersonaStudioOverview = ({
  persona,
  stats,
  onActivate,
  onEdit,
}: {
  persona: Persona | null;
  stats: PersonaDerivedStats | null;
  onActivate: (persona: Persona) => void;
  onEdit: (persona: Persona) => void;
}) => {
  if (!persona || !stats) {
    return null;
  }

  const readinessPercent = getPersonaReadinessPercent(stats.sectionCount);
  const hasCompleteContent = stats.sectionCount >= PERSONA_SECTION_TOTAL;
  const hasCompleteFollowups = stats.followupEnabledCount >= FOLLOWUP_TOTAL;
  const hasAssignedScope = persona.is_active || stats.adapterCount > 0;
  const hasAuthoredContent = stats.contentLength > 0;
  const updatedAt = formatDate(persona.updated_at);
  const createdAt = formatDate(persona.created_at);
  const sections = getPersonaSectionSummaries(persona.body_md);
  const adapterScopeSummary = getAdapterScopeSummary(persona, stats);
  const adapterModeLabel = persona.is_active
    ? "Mặc định toàn hệ thống"
    : stats.adapterCount > 0
      ? "Đang dùng theo adapter"
      : "Hồ sơ dự phòng";
  const adapterActivitySummary = persona.is_active
    ? "Kế thừa cho adapter chưa gán Agent riêng"
    : stats.adapterCount > 0
      ? `Đang hiệu lực trên ${stats.adapterCount} adapter`
      : "Có thể gán cho từng adapter khi cần";

  return (
    <section className="persona-studio-sheet" aria-label="Hồ sơ Agent">
      <div className="persona-studio-profile">
        <div className="persona-studio-profile-head">
          <div className="persona-studio-avatar" aria-hidden="true">
            AI
          </div>
          <div className="min-w-0">
            <h1>{persona.name}</h1>
            <p>
              <Hash className="size-3.5" />
              {persona.slug}
            </p>
            <div className="persona-studio-status-row">
              <Badge
                variant="outline"
                className={
                  persona.is_active
                    ? "persona-studio-badge is-good"
                    : "persona-studio-badge"
                }
              >
                {persona.is_active ? <CheckCircle2 className="size-3" /> : null}
                {persona.is_active ? "Mặc định" : "Dự phòng"}
              </Badge>
              <Badge variant="outline" className="persona-studio-badge">
                {getScopeLabel(persona, stats)}
              </Badge>
            </div>
          </div>
          <div className="persona-studio-profile-actions">
            <span className="persona-studio-updated">Cập nhật {updatedAt}</span>
            <Button
              variant="outline"
              type="button"
              className="persona-overview-edit-action tt-btn-touch"
              onClick={() => onEdit(persona)}
            >
              <Pencil className="size-3.5" />
              Sửa Agent
            </Button>
          </div>
        </div>
      </div>

      <section className="persona-studio-section">
        <div className="persona-studio-section-title">
          <div>
            <h2>Mức hoàn thiện</h2>
            <p>
              {stats.sectionCount}/{PERSONA_SECTION_TOTAL} phần ·{" "}
              {stats.followupEnabledCount}/{FOLLOWUP_TOTAL} follow-up ·{" "}
              {stats.adapterCount} adapter
            </p>
          </div>
        </div>
        <div className="persona-readiness-bar-card">
          <div>
            <span>Hồ sơ</span>
            <strong>{readinessPercent}%</strong>
          </div>
          <progress
            className="tt-progress tt-progress-success persona-readiness-bar"
            value={readinessPercent}
            max={100}
            aria-label={`Sẵn sàng ${readinessPercent}%`}
          />
          <Badge
            variant="outline"
            className={`persona-studio-badge ${readinessPercent >= 100 ? "is-good" : ""}`}
          >
            {readinessPercent >= 100 ? "Đạt" : "Đang thiếu"}
          </Badge>
        </div>
        <div className="persona-studio-checklist">
          <div>
            {hasCompleteContent ? (
              <CheckCircle2 className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock3 className="is-incomplete size-3.5" aria-hidden="true" />
            )}
            <span>
              <strong>Nội dung</strong>
              <small>
                {stats.sectionCount} / {PERSONA_SECTION_TOTAL} phần
              </small>
            </span>
          </div>
          <div>
            {hasCompleteFollowups ? (
              <CheckCircle2 className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock3 className="is-incomplete size-3.5" aria-hidden="true" />
            )}
            <span>
              <strong>Follow-up</strong>
              <small>
                {stats.followupEnabledCount} / {FOLLOWUP_TOTAL} kịch bản
              </small>
            </span>
          </div>
          <div>
            {hasAssignedScope ? (
              <CheckCircle2 className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock3 className="is-incomplete size-3.5" aria-hidden="true" />
            )}
            <span>
              <strong>Phạm vi</strong>
              <small>{adapterScopeSummary}</small>
            </span>
          </div>
          <div>
            {hasAuthoredContent ? (
              <CheckCircle2 className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock3 className="is-incomplete size-3.5" aria-hidden="true" />
            )}
            <span>
              <strong>Dung lượng</strong>
              <small>{numberFormatter.format(stats.contentLength)} ký tự</small>
            </span>
          </div>
        </div>
      </section>

      <section className="persona-studio-section">
        <div className="persona-studio-section-title">
          <div>
            <h2>Prompt Agent</h2>
            <p>7 phần định hình cách Agent tư vấn.</p>
          </div>
        </div>
        <div className="persona-prompt-list">
          {sections.map((section) => (
            <details key={section.title} className="persona-prompt-disclosure">
              <summary>
                <span className="persona-prompt-summary-copy">
                  <strong>{section.title}</strong>
                  <span>{getContentPreview(section.content)}</span>
                </span>
                <span className="persona-prompt-summary-state">
                  <Badge
                    variant="outline"
                    className={
                      section.content
                        ? "persona-studio-badge is-good"
                        : "persona-studio-badge"
                    }
                  >
                    {section.content ? "Đã viết" : "Thiếu"}
                  </Badge>
                  <ChevronDown className="size-4" aria-hidden="true" />
                </span>
              </summary>
              <div className="persona-prompt-disclosure-content">
                <PersonaFormattedContent
                  content={section.content}
                  emptyText="Chưa có nội dung cho phần này."
                />
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="persona-studio-section">
        <div className="persona-studio-section-title">
          <div>
            <h2>Follow-up</h2>
            <p>Lịch nhắc theo mức ưu tiên.</p>
          </div>
        </div>
        <div className="persona-followup-grid">
          {FOLLOWUP_KEYS.map((key) => {
            const rule = persona.followup_rules?.[key];
            return (
              <article key={key} className="persona-followup-card">
                <div>
                  <strong>{FOLLOWUP_LABELS[key]}</strong>
                  <Badge
                    variant="outline"
                    className={
                      rule?.enabled
                        ? "persona-studio-badge is-good"
                        : "persona-studio-badge"
                    }
                  >
                    {rule?.enabled ? "Bật" : "Tắt"}
                  </Badge>
                </div>
                <p>
                  {rule?.cadence_hours?.length
                    ? `Sau ${rule.cadence_hours.join(", ")} giờ`
                    : "Chưa đặt lịch"}
                </p>
                <small>
                  {rule?.eligible_stages?.join(", ") || "Chưa chọn nhóm"}
                </small>
              </article>
            );
          })}
        </div>
      </section>

      <section className="persona-studio-section">
        <div className="persona-studio-section-title">
          <div>
            <h2>Phạm vi</h2>
            <p>Adapter sử dụng Agent này.</p>
          </div>
        </div>
        <div className="persona-scope-activity-grid">
          <div className="persona-scope-list">
            <div className="persona-scope-row">
              <span>Kiểu dùng</span>
              <strong>{adapterModeLabel}</strong>
              <Badge
                variant="outline"
                className="persona-studio-badge is-brand"
              >
                {persona.is_active ? "Mặc định" : "Tuỳ chọn"}
              </Badge>
            </div>
            <div className="persona-scope-row">
              <span>Đang dùng</span>
              <strong>{adapterScopeSummary}</strong>
            </div>
            <div className="persona-scope-row">
              <span>Ghi chú</span>
              <strong>{persona.notes?.trim() || "Chưa có"}</strong>
            </div>
          </div>
          <details className="persona-activity-disclosure">
            <summary>
              <span>
                <Clock3 className="size-4" />
                Lịch sử
              </span>
              <ChevronDown className="size-4" aria-hidden="true" />
            </summary>
            <div className="persona-activity">
              <div>
                <span>
                  <Pencil className="size-3.5" />
                </span>
                <p>
                  <strong>Cập nhật cấu hình</strong>
                  <small>{updatedAt}</small>
                </p>
              </div>
              <div>
                <span>
                  <Clock3 className="size-3.5" />
                </span>
                <p>
                  <strong>Tạo Agent</strong>
                  <small>{createdAt}</small>
                </p>
              </div>
              <div>
                <span>
                  <CheckCircle2 className="size-3.5" />
                </span>
                <p>
                  <strong>
                    {persona.is_active
                      ? "Đang làm mặc định"
                      : "Trạng thái adapter"}
                  </strong>
                  <small>{adapterActivitySummary}</small>
                </p>
              </div>
            </div>
          </details>
        </div>
      </section>

      {!persona.is_active ? (
        <footer className="persona-profile-footer">
          <Button type="button" onClick={() => onActivate(persona)}>
            <Zap className="size-3.5" />
            Đặt mặc định
          </Button>
        </footer>
      ) : null}
    </section>
  );
};

const PersonaEmptyWorkspace = ({ onCreate }: { onCreate: () => void }) => (
  <section className="persona-empty-workspace" aria-label="Tạo Agent đầu tiên">
    <div className="persona-empty-primary">
      <div className="persona-empty-copy">
        <span className="persona-empty-icon" aria-hidden="true">
          <BotMessageSquare className="size-5" />
        </span>
        <p className="persona-panel-eyebrow">Bắt đầu</p>
        <h2>Tạo giọng Agent đầu tiên</h2>
        <p>
          Thiết lập một hồ sơ để chatbot biết cách chào hỏi, hỏi thông tin và
          chuyển cuộc trò chuyện cho đội tuyển dụng khi cần.
        </p>
        <Button
          type="button"
          className="h-9 rounded-[8px] text-button"
          onClick={onCreate}
        >
          <Plus className="size-4" />
          Tạo Agent
        </Button>
      </div>
    </div>
    <div className="persona-empty-guide" aria-label="Quy trình thiết lập">
      <div>
        <span className="persona-empty-step-index">1</span>
        <div>
          <strong>Viết giọng tư vấn</strong>
          <p>Vai trò, phạm vi trả lời, những điều Agent không được bịa.</p>
        </div>
      </div>
      <div>
        <span className="persona-empty-step-index">2</span>
        <div>
          <strong>Thiết lập adapter</strong>
          <p>
            Chọn adapter nào dùng Agent này hoặc để adapter kế thừa mặc định.
          </p>
        </div>
      </div>
      <div>
        <span className="persona-empty-step-index">3</span>
        <div>
          <strong>Bật follow-up</strong>
          <p>Đặt lịch nhắc lại theo Hot, Warm hoặc Not interested.</p>
        </div>
      </div>
    </div>
  </section>
);

const PersonaListContent = ({ embedded = false }: PersonaListProps) => {
  const { data, isPending, total } = useListContext<Persona>();
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
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
          <PersonaEmptyWorkspace
            onCreate={() => redirect("create", "personas")}
          />
        ) : (
          <>
            <div className="persona-studio-layout persona-agent-stack">
              <section
                className="persona-agent-picker"
                aria-label="Danh sách Agent"
              >
                <div className="persona-panel-header">
                  <div className="persona-panel-heading">
                    <h2>Agent</h2>
                    <Badge
                      variant="outline"
                      className="border-border bg-background/70"
                      aria-label={`${numberFormatter.format(totalCount)} hồ sơ`}
                    >
                      {numberFormatter.format(totalCount)}
                    </Badge>
                  </div>
                  <Button
                    type="button"
                    className="persona-create-action tt-btn-touch"
                    onClick={() => redirect("create", "personas")}
                  >
                    <Plus className="size-4" />
                    Tạo Agent
                  </Button>
                </div>

                <label className="tt-input persona-studio-command">
                  <Search className="size-4" />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder="Tìm Agent"
                    aria-label="Tìm Agent"
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
                      <p className="persona-empty-results">
                        Không tìm thấy Agent phù hợp.
                      </p>
                    )}
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
