import { useTranslate, type TranslateFunction } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CheckCircle2,
  ChevronDown,
  Clock3,
  Hash,
  Pencil,
  Zap,
} from "lucide-react";
import { getPersonaSectionSummaries } from "../domain/personaMarkdown";
import {
  PERSONA_SECTION_TOTAL,
  getPersonaReadinessPercent,
} from "../domain/personaReadiness";
import type { Persona } from "../../types";
import {
  FOLLOWUP_KEYS,
  getScopeLabel,
  numberFormatter,
  type PersonaDerivedStats,
} from "./persona-presentation";

const FOLLOWUP_TOTAL = 3;

const FOLLOWUP_LABELS: Record<(typeof FOLLOWUP_KEYS)[number], string> = {
  hot: "Hot",
  warm: "Warm",
  not_interested: "Cold",
};

const dateFormatter = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const getAdapterScopeSummary = (
  persona: Persona,
  stats: PersonaDerivedStats,
  translate: TranslateFunction,
) => {
  if (stats.adapterCount > 0) {
    return stats.adapterLabels.join(", ");
  }
  if (persona.is_active) {
    return translate("personas.scope_inherits_default");
  }
  return translate("personas.scope_unused");
};

const formatDate = (value: string, translate: TranslateFunction) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return translate("crm.common.unknown");
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

type PersonaProfileHeaderProps = {
  persona: Persona;
  stats: PersonaDerivedStats;
  updatedAt: string;
  onEdit: (persona: Persona) => void;
};

const PersonaProfileHeader = ({
  persona,
  stats,
  updatedAt,
  onEdit,
}: PersonaProfileHeaderProps) => {
  const translate = useTranslate();

  return (
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
            {persona.is_active
              ? translate("personas.status_default")
              : translate("personas.status_fallback")}
          </Badge>
          <Badge variant="outline" className="persona-studio-badge">
            {getScopeLabel(persona, stats, translate)}
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
  );
};

type PersonaReadinessSectionProps = {
  persona: Persona;
  stats: PersonaDerivedStats;
  readinessPercent: number;
  adapterScopeSummary: string;
};

const PersonaReadinessSection = ({
  persona,
  stats,
  readinessPercent,
  adapterScopeSummary,
}: PersonaReadinessSectionProps) => {
  const hasCompleteContent = stats.sectionCount >= PERSONA_SECTION_TOTAL;
  const hasCompleteFollowups = stats.followupEnabledCount >= FOLLOWUP_TOTAL;
  const hasAssignedScope = persona.is_active || stats.adapterCount > 0;
  const hasAuthoredContent = stats.contentLength > 0;

  return (
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
  );
};

const PersonaPromptSection = ({ bodyMd }: { bodyMd: string }) => {
  const sections = getPersonaSectionSummaries(bodyMd);

  return (
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
  );
};

const PersonaFollowupSection = ({ persona }: { persona: Persona }) => {
  return (
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
  );
};

type PersonaScopeSectionProps = {
  persona: Persona;
  adapterModeLabel: string;
  adapterScopeSummary: string;
  adapterActivitySummary: string;
  updatedAt: string;
  createdAt: string;
};

const PersonaScopeSection = ({
  persona,
  adapterModeLabel,
  adapterScopeSummary,
  adapterActivitySummary,
  updatedAt,
  createdAt,
}: PersonaScopeSectionProps) => {
  const translate = useTranslate();

  return (
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
            <Badge variant="outline" className="persona-studio-badge is-brand">
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
                <strong>{translate("personas.create_agent")}</strong>
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
  );
};

export const PersonaStudioOverview = ({
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
  const translate = useTranslate();

  if (!persona || !stats) {
    return null;
  }

  const readinessPercent = getPersonaReadinessPercent(stats.sectionCount);
  const updatedAt = formatDate(persona.updated_at, translate);
  const createdAt = formatDate(persona.created_at, translate);
  const adapterScopeSummary = getAdapterScopeSummary(persona, stats, translate);
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
        <PersonaProfileHeader
          persona={persona}
          stats={stats}
          updatedAt={updatedAt}
          onEdit={onEdit}
        />
      </div>

      <PersonaReadinessSection
        persona={persona}
        stats={stats}
        readinessPercent={readinessPercent}
        adapterScopeSummary={adapterScopeSummary}
      />

      <PersonaPromptSection bodyMd={persona.body_md} />

      <PersonaFollowupSection persona={persona} />

      <PersonaScopeSection
        persona={persona}
        adapterModeLabel={adapterModeLabel}
        adapterScopeSummary={adapterScopeSummary}
        adapterActivitySummary={adapterActivitySummary}
        updatedAt={updatedAt}
        createdAt={createdAt}
      />

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
