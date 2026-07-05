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
  ChevronRight,
  Clock3,
  FileText,
  Hash,
  MessageSquareText,
  Pencil,
  Plus,
  Search,
  UsersRound,
  Zap,
} from "lucide-react";
import type { Persona } from "../types";
import { activatePersona } from "@/lib/vfic/knowledgeService";
import { PersonaWorkspaceShell } from "./PersonaWorkspaceShell";
import {
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
  getPersonaSectionSummaries,
} from "./personaMarkdown";

const PERSONA_SECTION_TOTAL = 7;
const FOLLOWUP_TOTAL = 3;
const FOLLOWUP_KEYS = ["hot", "warm", "not_interested"] as const;
const FOLLOWUP_LABELS: Record<(typeof FOLLOWUP_KEYS)[number], string> = {
  hot: "Hot",
  warm: "Warm",
  not_interested: "Cold",
};

type PersonaDerivedStats = {
  assignedCount: number;
  contentLength: number;
  followupEnabledCount: number;
  sectionCount: number;
};

const numberFormatter = new Intl.NumberFormat("vi-VN");
const dateFormatter = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const getPersonaDerivedStats = (persona: Persona): PersonaDerivedStats => ({
  assignedCount: persona.assigned_projects?.length ?? 0,
  contentLength: getPersonaAuthoredContentLength(persona.body_md),
  followupEnabledCount: FOLLOWUP_KEYS.filter(
    (key) => persona.followup_rules?.[key]?.enabled,
  ).length,
  sectionCount: getCompletedPersonaSectionCount(persona.body_md),
});

const getReadinessPercent = (sectionCount: number) =>
  Math.round(
    (Math.max(0, Math.min(PERSONA_SECTION_TOTAL, sectionCount)) /
      PERSONA_SECTION_TOTAL) *
      100,
  );

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Chưa rõ";
  return dateFormatter.format(date);
};

type PersonaRowProps = {
  persona: Persona;
  isSelected: boolean;
  onSelect: (persona: Persona) => void;
};

const PersonaRow = memo(
  ({ persona, isSelected, onSelect }: PersonaRowProps) => {
    const stats = getPersonaDerivedStats(persona);

    return (
      <article
        className={`persona-directory-row ${persona.is_active ? "is-active" : ""} ${
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
              <span className="persona-directory-badges">
                {persona.is_active ? (
                  <Badge
                    variant="outline"
                    className="gap-1 border-primary/20 bg-primary/5 text-[10px] text-primary"
                  >
                    <CheckCircle2 className="size-3" />
                    Mặc định
                  </Badge>
                ) : null}
              </span>
            </span>
            <span className="persona-directory-meta">
              <span>
                <FileText className="size-3" />
                {stats.sectionCount}/{PERSONA_SECTION_TOTAL}
              </span>
              <span>
                <MessageSquareText className="size-3" />
                {stats.followupEnabledCount}/{FOLLOWUP_TOTAL}
              </span>
              <span>
                <UsersRound className="size-3" />
                {stats.assignedCount > 0
                  ? `${stats.assignedCount} dự án`
                  : "Chung"}
              </span>
              <span>
                <Clock3 className="size-3" />
                {formatDate(persona.updated_at)}
              </span>
              </span>
            </span>
        </button>
      </article>
    );
  },
);
PersonaRow.displayName = "PersonaRow";

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

  const projects = persona.assigned_projects ?? [];
  const readinessPercent = getReadinessPercent(stats.sectionCount);
  const updatedAt = formatDate(persona.updated_at);
  const createdAt = formatDate(persona.created_at);
  const sections = getPersonaSectionSummaries(persona.body_md);
  const ruleSections = sections.filter((_, index) => [2, 3, 5].includes(index));

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
                  <CheckCircle2 className="size-3" />
                  {persona.is_active ? "Đang dùng" : "Đang xem"}
                </Badge>
                {persona.is_active ? (
                  <Badge
                    variant="outline"
                    className="persona-studio-badge is-brand"
                  >
                    Mặc định
                  </Badge>
                ) : null}
                <Badge variant="outline" className="persona-studio-badge">
                  {projects.length > 0 ? `${projects.length} dự án` : "Áp dụng chung"}
                </Badge>
              </div>
            </div>
            <div className="persona-studio-profile-actions">
              <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
                <Pencil className="size-3.5" />
                Sửa Agent
              </Button>
            </div>
          </div>
        </div>

        <section className="persona-studio-section">
          <div className="persona-studio-section-title">
            <div>
              <h2>Mức sẵn sàng</h2>
              <p>Agent có đủ prompt, follow-up và phạm vi áp dụng để vận hành.</p>
            </div>
            <span>Cập nhật {updatedAt}</span>
          </div>
          <div className="persona-readiness-bar-card">
            <div>
              <span>Sẵn sàng</span>
              <strong>{readinessPercent}%</strong>
            </div>
            <div
              className="persona-readiness-bar"
              aria-label={`Sẵn sàng ${readinessPercent}%`}
            >
              <span style={{ width: `${readinessPercent}%` }} />
            </div>
            <Badge
              variant="outline"
              className={`persona-studio-badge ${readinessPercent >= 100 ? "is-good" : ""}`}
            >
              {readinessPercent >= 100 ? "Đạt" : "Đang thiếu"}
            </Badge>
          </div>
          <div className="persona-studio-checklist">
            <div>
              <CheckCircle2 className="size-3.5" />
              <span>
                <strong>Nội dung</strong>
                <small>
                  {stats.sectionCount} / {PERSONA_SECTION_TOTAL} phần
                </small>
              </span>
            </div>
            <div>
              <CheckCircle2 className="size-3.5" />
              <span>
                <strong>Follow-up</strong>
                <small>
                  {stats.followupEnabledCount} / {FOLLOWUP_TOTAL} kịch bản
                </small>
              </span>
            </div>
            <div>
              <CheckCircle2 className="size-3.5" />
              <span>
                <strong>Phạm vi</strong>
                <small>
                  {projects.length > 0 ? `${projects.length} dự án` : "Áp dụng chung"}
                </small>
              </span>
            </div>
            <div>
              <CheckCircle2 className="size-3.5" />
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
              <p>Nội dung quyết định agent nói gì, hỏi gì và tránh điều gì.</p>
            </div>
            <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
              <Pencil className="size-3.5" />
              Sửa prompt
            </Button>
          </div>
          <div className="persona-prompt-list">
            {sections.map((section) => (
              <article key={section.title} className="persona-prompt-card">
                <div>
                  <strong>{section.title}</strong>
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
                </div>
                <p>{section.content || "Chưa có nội dung cho phần này."}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="persona-studio-section">
          <div className="persona-studio-section-title">
            <div>
              <h2>Luật phản hồi</h2>
              <p>Những nguyên tắc quan trọng nhất agent phải tuân thủ.</p>
            </div>
          </div>
          <div className="persona-prompt-list">
            {ruleSections.map((section) => (
              <article key={section.title} className="persona-rule-card">
                <div>
                  <Badge
                    variant="outline"
                    className={
                      section.content
                        ? "persona-studio-badge is-good"
                        : "persona-studio-badge"
                    }
                  >
                    {section.content ? "Bật" : "Thiếu"}
                  </Badge>
                  <strong>{section.title}</strong>
                </div>
                <p>{section.content || "Chưa có luật phản hồi cho phần này."}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="persona-studio-section">
          <div className="persona-studio-section-title">
            <div>
              <h2>Tự động follow-up</h2>
              <p>Lịch nhắc lại theo mức ưu tiên của ứng viên.</p>
            </div>
            <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
              <Pencil className="size-3.5" />
              Sửa follow-up
            </Button>
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
                      ? `Nhắc sau ${rule.cadence_hours.join(", ")} giờ`
                      : "Chưa đặt lịch nhắc"}
                  </p>
                  <small>
                    Giai đoạn: {rule?.eligible_stages?.join(", ") || "Chưa chọn"}
                  </small>
                </article>
              );
            })}
          </div>
        </section>

        <section className="persona-studio-section">
          <div className="persona-studio-section-title">
            <div>
              <h2>Phạm vi & nhật ký</h2>
              <p>Agent đang áp dụng ở đâu và thay đổi gần nhất là gì.</p>
            </div>
          </div>
          <div className="persona-scope-activity-grid">
            <div className="persona-scope-list">
              <div className="persona-scope-row">
                <span>Loại agent</span>
                <strong>
                  {persona.is_active ? "Mặc định toàn hệ thống" : "Hồ sơ dự phòng"}
                </strong>
                <Badge variant="outline" className="persona-studio-badge is-brand">
                  {persona.is_active ? "Default" : "Draft"}
                </Badge>
              </div>
              <div className="persona-scope-row">
                <span>Dự án riêng</span>
                <strong>
                  {projects.length > 0
                    ? projects.slice(0, 2).map((project) => project.name).join(", ")
                    : "Chưa gắn dự án cụ thể"}
                </strong>
                <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
                  Gắn dự án
                </Button>
              </div>
              <div className="persona-scope-row">
                <span>Ghi chú nội bộ</span>
                <strong>{persona.notes?.trim() || "Chưa có ghi chú"}</strong>
                <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
                  Thêm
                </Button>
              </div>
            </div>
            <div className="persona-activity is-expanded">
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
                  <strong>{persona.is_active ? "Đang làm mặc định" : "Hồ sơ dự phòng"}</strong>
                  <small>
                    {persona.is_active
                      ? "Áp dụng cho dự án chưa gắn agent"
                      : "Có thể đặt làm mặc định khi cần"}
                  </small>
                </p>
              </div>
            </div>
          </div>
        </section>

        {!persona.is_active ? (
          <footer className="persona-profile-footer">
          <Button variant="outline" type="button" onClick={() => onEdit(persona)}>
            <Pencil className="size-3.5" />
            Sửa
          </Button>
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
          className="h-9 rounded-[8px] text-sm"
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
          <strong>Gán dự án</strong>
          <p>Dùng chung cho toàn bộ chatbot hoặc gán riêng theo nhà máy.</p>
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

const PersonaListContent = () => {
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
        ...(persona.assigned_projects?.map((project) => project.name) ?? []),
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
  const selectedPersona = useMemo(
    () =>
      personas.find((persona) => persona.id === selectedPersonaId) ??
      defaultPersona,
    [defaultPersona, personas, selectedPersonaId],
  );
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

  return (
    <PersonaWorkspaceShell>
      <div className="persona-workspace-content">
        <div className="persona-page-shell">
          <header className="persona-studio-topbar">
            <div className="persona-studio-crumbs">
              <span>Hồ sơ Agent</span>
              <ChevronRight className="size-4" aria-hidden="true" />
              <strong>{selectedPersona?.name ?? "Agent"}</strong>
            </div>
            <label className="persona-studio-command">
              <Search className="size-4" />
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Tìm Agent, slug hoặc dự án"
                aria-label="Tìm Agent"
              />
            </label>
            <Button
              type="button"
              className="persona-create-action"
              onClick={() => redirect("create", "personas")}
            >
              <Plus className="size-4" />
              Tạo Agent
            </Button>
          </header>

          {isEmpty ? (
            <PersonaEmptyWorkspace
              onCreate={() => redirect("create", "personas")}
            />
          ) : (
            <>
              <div className="persona-studio-layout">
                <aside className="persona-studio-sidebar">
                  <div className="persona-panel-header">
                    <div>
                      <p className="persona-panel-eyebrow">Danh sách</p>
                      <h2>Danh sách Agent</h2>
                    </div>
                    <Badge
                      variant="outline"
                      className="border-border bg-background/70"
                    >
                      {numberFormatter.format(totalCount)} hồ sơ
                    </Badge>
                  </div>

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
                    <div className="persona-directory-list">
                      {filteredPersonas.length > 0 ? (
                        filteredPersonas.map((p) => (
                          <PersonaRow
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
                </aside>

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
    </PersonaWorkspaceShell>
  );
};

export const PersonaList = () => (
  <ListBase perPage={25} sort={{ field: "name", order: "ASC" }}>
    <PersonaListContent />
  </ListBase>
);
