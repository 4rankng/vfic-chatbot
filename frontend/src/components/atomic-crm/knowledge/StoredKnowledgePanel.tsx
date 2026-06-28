import { useQuery } from "@tanstack/react-query";
import { HelpCircle, Quote, RefreshCw, Tags } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getKnowledgeUnits,
  type KnowledgeUnit,
} from "@/lib/vfic/knowledgeService";
import type { KnowledgeSource } from "../types";
import { isPublished, needsReview } from "./knowledgePipelineUtils";
import { Chip } from "./KnowledgeSourceRow";
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
    <section className="rounded-[12px] border border-border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="kb-display text-sm text-foreground">
            Kiến thức đã lưu
          </h4>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Đơn vị agent thực sự truy xuất — đây là phần con người có thể kiểm
            tra.
          </p>
        </div>
        <Badge className="kb-mono rounded-full bg-secondary text-[11px] text-[var(--kb-ink-700)] hover:bg-secondary">
          {source.digest_meta?.unit_count ?? units.length} đơn vị
        </Badge>
      </div>

      {!isPublished(source) && !needsReview(source) ? (
        <div className="mt-3 flex items-center gap-2 rounded-[10px] bg-[var(--kb-teal-soft)] p-3 text-sm text-[var(--kb-teal)]">
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
        <div className="mt-3 rounded-[10px] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
          Chưa tải được danh sách kiến thức đã lưu. Hãy làm mới trang hoặc thử
          lại sau.
        </div>
      ) : units.length === 0 ? (
        <div className="mt-3 rounded-[10px] bg-secondary p-3 text-sm text-muted-foreground">
          Chưa có đơn vị kiến thức nào được lưu. Nếu tài liệu đã xử lý xong, hãy
          kiểm tra nội dung nguồn hoặc chạy lại pipeline.
        </div>
      ) : (
        <div className="mt-4 grid max-h-[460px] gap-3 overflow-y-auto pr-1">
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
    <article className="rounded-[10px] border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{unit.category || "other"}</Chip>
        <Chip
          tone={
            unit.confidence === "low"
              ? "warning"
              : unit.confidence === "high"
                ? "success"
                : "neutral"
          }
        >
          Tin cậy {unit.confidence || "medium"}
        </Chip>
        {unit.is_inference && <Chip tone="warning">Suy luận</Chip>}
        <span className="kb-mono ml-auto text-[11px] text-muted-foreground">
          #{unit.chunk_index + 1}
        </span>
      </div>

      <p className="mt-3 break-words text-sm leading-6 text-foreground">
        {unit.content}
      </p>

      {unit.summary && (
        <div className="mt-3 rounded-lg bg-secondary p-3 text-xs leading-5 text-muted-foreground">
          {unit.summary}
        </div>
      )}

      {unit.source_quote && (
        <div className="mt-3 flex gap-2 rounded-lg border border-border bg-secondary p-3 text-xs leading-5 text-muted-foreground">
          <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-ink-300)]" />
          <span className="break-words">{unit.source_quote}</span>
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
                className="break-words rounded-lg bg-secondary px-3 py-2 text-xs leading-5 text-[var(--kb-ink-700)]"
              >
                {question}
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
                {key}: {String(value)}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
};
