import { useQuery } from "@tanstack/react-query";
import { CalendarDays, HelpCircle, Quote, RefreshCw, Tags } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getKnowledgeUnits,
  type KnowledgeUnit,
} from "@/lib/vfic/knowledgeService";
import { Markdown } from "../misc/Markdown";
import type { KnowledgeSource } from "../types";
import { isPublished, needsReview } from "./knowledgePipelineUtils";
import { Chip } from "./KnowledgeSourceRow";

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

const CANONICAL_TEXT_LABELS: Record<string, string> = {
  "Company Overview": "Tổng quan công ty",
  "LG Display Worker Guide": "Hướng dẫn công nhân LG Display",
};

const labelFromMap = (value: string | null | undefined, labels: Record<string, string>) => {
  const key = (value ?? "").trim();
  return key ? labels[key] ?? key : "";
};

export const localizeKnowledgeText = (value: string) =>
  Object.entries(CANONICAL_TEXT_LABELS).reduce(
    (text, [source, label]) => text.replaceAll(source, label),
    value,
  );

const COMPACT_MARKDOWN_CLASS =
  "[&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_h4]:text-sm [&_h5]:text-sm [&_h6]:text-sm [&_pre]:p-3 [&_table]:text-xs";

export const StoredKnowledgePanel = ({
  source,
}: {
  source: KnowledgeSource;
}) => {
  const { data, isError, isPending } = useQuery({
    queryKey: ["knowledge-units", source.id],
    queryFn: () => getKnowledgeUnits(String(source.id), 50),
    enabled: Boolean(source.id) && (isPublished(source) || needsReview(source)),
    staleTime: 5000,
  });
  const units = data?.data ?? [];

  return (
    <section className="border-y border-border py-4 sm:rounded-[12px] sm:border sm:bg-background sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-3 px-1 sm:px-0">
        <div className="min-w-0">
          <h4 className="kb-display text-sm text-foreground">
            Kiến thức đã lưu
          </h4>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Đơn vị agent thực sự truy xuất — đây là phần con người có thể kiểm
            tra.
          </p>
        </div>
        <Badge className="kb-mono rounded-full bg-[var(--kb-teal-soft)] text-[11px] text-[var(--kb-teal)] hover:bg-[var(--kb-teal-soft)]">
          {source.digest_meta?.unit_count ?? units.length} đơn vị
        </Badge>
      </div>

      {!isPublished(source) && !needsReview(source) ? (
        <div className="mt-3 flex items-center gap-2 border-l-2 border-[var(--kb-teal)] py-2 pl-3 text-sm text-[var(--kb-teal)]">
          <RefreshCw className="size-4 animate-spin" />
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
        <div className="mt-3 border-l-2 border-[var(--kb-rust)] py-2 pl-3 text-sm text-[var(--kb-rust)]">
          Chưa tải được danh sách kiến thức đã lưu. Hãy làm mới trang hoặc thử
          lại sau.
        </div>
      ) : units.length === 0 ? (
        <div className="mt-3 border-l-2 border-border py-2 pl-3 text-sm text-muted-foreground">
          Chưa có đơn vị kiến thức nào được lưu. Nếu tài liệu đã xử lý xong, hãy
          kiểm tra nội dung nguồn hoặc chạy lại pipeline.
        </div>
      ) : (
        <div className="mt-4 max-h-[520px] divide-y divide-border overflow-y-auto">
          {units.map((unit) => (
            <KnowledgeUnitCard key={unit.id} unit={unit} />
          ))}
        </div>
      )}
    </section>
  );
};

const KnowledgeUnitCard = ({ unit }: { unit: KnowledgeUnit }) => {
  const questionCount = unit.questions?.length ?? 0;
  const entityEntries = Object.entries(unit.entities ?? {}).filter(
    ([, value]) =>
      value !== null && value !== undefined && String(value) !== "",
  );

  return (
    <article className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{labelFromMap(unit.category || "other", CATEGORY_LABELS)}</Chip>
        <Chip
          tone={
            unit.confidence === "low"
              ? "warning"
              : unit.confidence === "high"
                ? "success"
                : "neutral"
          }
        >
          Tin cậy {labelFromMap(unit.confidence || "medium", CONFIDENCE_LABELS)}
        </Chip>
        {unit.is_inference && <Chip tone="warning">Suy luận</Chip>}
        {unit.content_type && (
          <Chip>{labelFromMap(unit.content_type, CONTENT_TYPE_LABELS)}</Chip>
        )}
        {unit.route_id && <Chip>{unit.route_id}</Chip>}
        <span className="kb-mono text-[11px] text-muted-foreground sm:ml-auto">
          #{unit.chunk_index + 1}
        </span>
      </div>

      <Markdown
        className={`mt-3 break-words text-sm leading-6 text-foreground ${COMPACT_MARKDOWN_CLASS}`}
      >
        {localizeKnowledgeText(unit.content)}
      </Markdown>

      {unit.summary && (
        <div className="mt-3 border-l-2 border-border py-1 pl-3 text-xs leading-5 text-muted-foreground">
          <Markdown
            className={`text-xs [&_p]:leading-5 ${COMPACT_MARKDOWN_CLASS}`}
          >
            {localizeKnowledgeText(unit.summary)}
          </Markdown>
        </div>
      )}

      {unit.source_quote && (
        <div className="mt-3 flex gap-2 border-l-2 border-[var(--kb-line-strong)] py-1 pl-3 text-xs leading-5 text-muted-foreground">
          <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-ink-300)]" />
          <Markdown
            className={`min-w-0 flex-1 break-words text-xs [&_p]:leading-5 ${COMPACT_MARKDOWN_CLASS}`}
          >
            {localizeKnowledgeText(unit.source_quote)}
          </Markdown>
        </div>
      )}

      {(unit.citation_label || unit.source_anchor || unit.effective_from) && (
        <div className="mt-3 grid gap-2 border-t border-border pt-3 text-xs leading-5 text-muted-foreground">
          {unit.citation_label && (
            <div className="flex gap-2">
              <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-teal)]" />
              <span className="break-words">
                Nguồn: {localizeKnowledgeText(unit.citation_label)}
              </span>
            </div>
          )}
          {unit.source_anchor && (
            <div className="kb-mono break-words text-[11px]">
              Mốc nguồn: {localizeKnowledgeText(unit.source_anchor)}
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
      )}

      {questionCount > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <HelpCircle className="size-4 text-[var(--kb-teal)]" />
            Câu hỏi unit này trả lời được
          </div>
          <ul className="mt-2 grid gap-1.5">
            {unit.questions.slice(0, 3).map((question) => (
              <li
                key={question}
                className="break-words border-l-2 border-border py-1 pl-3 text-xs leading-5 text-[var(--kb-ink-700)]"
              >
                {localizeKnowledgeText(question)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {entityEntries.length > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Tags className="size-4 text-[var(--kb-teal)]" />
            Thực thể đã nhận diện
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {entityEntries.slice(0, 8).map(([key, value]) => (
              <span
                key={key}
                className="kb-mono rounded-full bg-secondary px-2 py-1 text-[11px] text-[var(--kb-ink-700)]"
              >
                {labelFromMap(key, ENTITY_LABELS)}: {String(value)}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
};
