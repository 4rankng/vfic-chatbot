import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  ChevronDown,
  HelpCircle,
  Quote,
  RefreshCw,
  Tags,
} from "lucide-react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getKnowledgeUnits, type KnowledgeUnit } from "./knowledge-service";
import { Markdown } from "../misc/Markdown";
import type { KnowledgeSource } from "../types";
import { isPublished, needsReview } from "./knowledgePipelineUtils";
import { Chip } from "./KnowledgeSourceRow";
import {
  areEquivalentKnowledgeTexts,
  getKnowledgeUnitPreview,
  localizeKnowledgeText,
} from "./domain/knowledge-text";

const CATEGORY_LABELS: Record<string, string> = {
  benefits: "Phúc lợi",
  contact: "Liên hệ",
  faq: "Hỏi đáp",
  feature: "Đặc điểm",
  job: "Tuyển dụng",
  other: "Khác",
  policy: "Quy định",
  salary: "Lương",
  schedule: "Lịch trình",
};

const CONTENT_TYPE_LABELS: Record<string, string> = {
  bus_schedule: "Lịch xe",
  company_knowledge: "Kiến thức công ty",
  job_posting: "Tin tuyển dụng",
  policy: "Quy định",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "Cao",
  low: "Thấp",
  medium: "Trung bình",
};

const ENTITY_LABELS: Record<string, string> = {
  company: "Công ty",
  location: "Địa điểm",
  project: "Dự án",
  route: "Tuyến",
  salary: "Lương",
  shift: "Ca làm",
  stop: "Điểm đón",
};

const labelFromMap = (
  value: string | null | undefined,
  labels: Record<string, string>,
) => {
  const key = (value ?? "").trim();
  return key ? (labels[key] ?? key) : "";
};

const COMPACT_MARKDOWN_CLASS =
  "[&_h1]:text-section-title [&_h2]:text-section-title [&_h3]:text-card-title [&_h4]:text-card-title [&_h5]:text-card-title [&_h6]:text-card-title [&_pre]:p-3 [&_table]:text-helper";

const INITIAL_VISIBLE_UNITS = 8;

export const StoredKnowledgePanel = ({
  source,
}: {
  source: KnowledgeSource;
}) => {
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_UNITS);
  const { data, isError, isPending } = useQuery({
    queryKey: ["knowledge-units", source.id],
    queryFn: () => getKnowledgeUnits(String(source.id), 50),
    enabled: Boolean(source.id) && (isPublished(source) || needsReview(source)),
    staleTime: 5000,
  });
  const units = data?.data ?? [];
  const visibleUnits = units.slice(0, visibleCount);
  const remainingCount = Math.max(0, units.length - visibleCount);

  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE_UNITS);
  }, [source.id]);

  return (
    <section className="knowledge-units-panel">
      <div className="knowledge-units-header">
        <div className="min-w-0">
          <h4 className="kb-display text-card-title text-foreground">
            Kiến thức agent dùng
          </h4>
          <p className="mt-1 text-helper leading-5 text-muted-foreground">
            Mở từng đơn vị để kiểm tra nội dung.
          </p>
        </div>
        <Badge type="pill-color" size="md" color="brand" className="kb-mono">
          {source.digest_meta?.unit_count ?? units.length} đơn vị
        </Badge>
      </div>

      {!isPublished(source) && !needsReview(source) ? (
        <div className="mt-3 flex items-center gap-2 border-l-2 border-[var(--kb-teal)] py-2 pl-3 text-body text-[var(--kb-teal)]">
          <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" />
          Kiến thức sẽ hiện ở đây sau khi pipeline xuất bản các đơn vị truy
          xuất.
        </div>
      ) : isPending ? (
        <div className="mt-4 grid gap-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-24 rounded-[10px]" />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-3 border-l-2 border-[var(--kb-rust)] py-2 pl-3 text-body text-[var(--kb-rust)]">
          Chưa tải được danh sách kiến thức đã lưu. Hãy làm mới trang hoặc thử
          lại sau.
        </div>
      ) : units.length === 0 ? (
        <div className="mt-3 border-l-2 border-border py-2 pl-3 text-body text-muted-foreground">
          Chưa có đơn vị kiến thức. Kiểm tra nguồn hoặc chạy lại pipeline.
        </div>
      ) : (
        <>
          <div className="knowledge-unit-list">
            {visibleUnits.map((unit) => (
              <KnowledgeUnitDisclosure key={unit.id} unit={unit} />
            ))}
          </div>
          {remainingCount > 0 ? (
            <Button
              type="button"
              color="tertiary"
              size="md"
              data-slot="button"
              className="knowledge-unit-more tt-btn-touch uu-scope"
              onClick={() =>
                setVisibleCount((count) =>
                  Math.min(units.length, count + INITIAL_VISIBLE_UNITS),
                )
              }
            >
              Xem thêm {Math.min(INITIAL_VISIBLE_UNITS, remainingCount)} đơn vị
            </Button>
          ) : units.length > INITIAL_VISIBLE_UNITS ? (
            <Button
              type="button"
              color="tertiary"
              size="md"
              data-slot="button"
              className="knowledge-unit-more tt-btn-touch uu-scope"
              onClick={() => setVisibleCount(INITIAL_VISIBLE_UNITS)}
            >
              Thu gọn danh sách
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
};

const KnowledgeUnitDisclosure = ({ unit }: { unit: KnowledgeUnit }) => {
  const content = localizeKnowledgeText(unit.content);
  const summary = unit.summary ? localizeKnowledgeText(unit.summary) : "";
  const sourceQuote = unit.source_quote
    ? localizeKnowledgeText(unit.source_quote)
    : "";
  const showSummary =
    Boolean(summary) && !areEquivalentKnowledgeTexts(summary, content);
  const showSourceQuote =
    Boolean(sourceQuote) &&
    !areEquivalentKnowledgeTexts(sourceQuote, content) &&
    !areEquivalentKnowledgeTexts(sourceQuote, summary);
  const relatedQuestions = (unit.questions ?? []).slice(1, 4);
  const entityEntries = Object.entries(unit.entities ?? {}).filter(
    ([, value]) =>
      value !== null && value !== undefined && String(value) !== "",
  );

  return (
    <details className="knowledge-unit-disclosure">
      <summary>
        <div className="knowledge-unit-summary-copy">
          <div className="knowledge-unit-summary-meta">
            <Chip>
              {labelFromMap(unit.category || "other", CATEGORY_LABELS)}
            </Chip>
            <Chip
              tone={
                unit.confidence === "low"
                  ? "warning"
                  : unit.confidence === "high"
                    ? "success"
                    : "neutral"
              }
            >
              Tin cậy{" "}
              {labelFromMap(unit.confidence || "medium", CONFIDENCE_LABELS)}
            </Chip>
            {unit.is_inference && <Chip tone="warning">Suy luận</Chip>}
            <span className="kb-mono text-caption text-muted-foreground">
              #{unit.chunk_index + 1}
            </span>
          </div>
          <p className="knowledge-unit-preview">
            {getKnowledgeUnitPreview(unit)}
          </p>
        </div>
        <ChevronDown
          className="knowledge-unit-chevron size-4"
          aria-hidden="true"
        />
      </summary>

      <div className="knowledge-unit-body">
        {(unit.content_type || unit.route_id) && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {unit.content_type && (
              <Chip>
                {labelFromMap(unit.content_type, CONTENT_TYPE_LABELS)}
              </Chip>
            )}
            {unit.route_id && <Chip>{unit.route_id}</Chip>}
          </div>
        )}

        <section className="knowledge-unit-section">
          <h5>Nội dung</h5>
          <Markdown
            className={`break-words text-body leading-6 text-foreground ${COMPACT_MARKDOWN_CLASS}`}
          >
            {content}
          </Markdown>
        </section>

        {showSummary && (
          <section className="knowledge-unit-section">
            <h5>Tóm tắt</h5>
            <Markdown
              className={`text-helper [&_p]:leading-5 ${COMPACT_MARKDOWN_CLASS}`}
            >
              {summary}
            </Markdown>
          </section>
        )}

        {showSourceQuote && (
          <section className="knowledge-unit-section">
            <h5>Nguồn trích dẫn</h5>
            <div className="flex gap-2 text-helper leading-5 text-muted-foreground">
              <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-ink-300)]" />
              <Markdown
                className={`min-w-0 flex-1 break-words text-helper [&_p]:leading-5 ${COMPACT_MARKDOWN_CLASS}`}
              >
                {sourceQuote}
              </Markdown>
            </div>
          </section>
        )}

        {(unit.citation_label || unit.source_anchor || unit.effective_from) && (
          <section className="knowledge-unit-section">
            <h5>Nguồn và hiệu lực</h5>
            <div className="grid gap-2 text-helper leading-5 text-muted-foreground">
              {unit.citation_label && (
                <div className="flex gap-2">
                  <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-teal)]" />
                  <span className="break-words">
                    {localizeKnowledgeText(unit.citation_label)}
                  </span>
                </div>
              )}
              {unit.source_anchor && (
                <div className="kb-mono break-words text-caption">
                  Mốc: {localizeKnowledgeText(unit.source_anchor)}
                </div>
              )}
              {unit.effective_from && (
                <div className="flex gap-2">
                  <CalendarDays className="mt-0.5 size-4 shrink-0 text-[var(--kb-teal)]" />
                  <span>
                    Hiệu lực: {unit.effective_from}
                    {unit.effective_to ? ` - ${unit.effective_to}` : ""}
                  </span>
                </div>
              )}
            </div>
          </section>
        )}

        {relatedQuestions.length > 0 && (
          <section className="knowledge-unit-section">
            <h5 className="flex items-center gap-2">
              <HelpCircle className="size-4 text-[var(--kb-teal)]" />
              Câu hỏi liên quan
            </h5>
            <ul className="mt-2 grid gap-1.5">
              {relatedQuestions.map((question) => (
                <li
                  key={question}
                  className="break-words border-l-2 border-border py-1 pl-3 text-helper leading-5 text-[var(--kb-ink-700)]"
                >
                  {localizeKnowledgeText(question)}
                </li>
              ))}
            </ul>
          </section>
        )}

        {entityEntries.length > 0 && (
          <section className="knowledge-unit-section">
            <h5 className="flex items-center gap-2">
              <Tags className="size-4 text-[var(--kb-teal)]" />
              Thực thể
            </h5>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {entityEntries.slice(0, 8).map(([key, value]) => (
                <Badge
                  key={key}
                  type="pill-color"
                  size="md"
                  color="gray"
                  className="kb-mono"
                >
                  {labelFromMap(key, ENTITY_LABELS)}: {String(value)}
                </Badge>
              ))}
            </div>
          </section>
        )}
      </div>
    </details>
  );
};
