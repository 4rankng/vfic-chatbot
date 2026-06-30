import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ShowBase, useRefresh } from "ra-core";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  UserRound,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

import { LEAD_STAGES, type Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { LeadShowContentSheet } from "./LeadShow";
import type { LeadSort } from "./LeadsToolbar";
import { apiJson } from "../providers/rest/api";

const CARD_GRID_CLASS =
  "grid justify-start gap-2 [grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),240px))]";
const SECTION_PER_PAGE = 60;

type StageSectionKey = (typeof LEAD_STAGES)[number]["value"];
type SectionKey = "needs_reply" | StageSectionKey;

type SectionConfig = {
  key: SectionKey;
  title: string;
  isPriority?: boolean;
};

type SectionResult = {
  key: string;
  title: string;
  leads: Lead[];
  total: number;
  page: number;
  perPage: number;
  isPriority?: boolean;
  isLoading: boolean;
  error: boolean;
};

type LeadBoardResponse = {
  sections: {
    key: string;
    title: string;
    data: Lead[];
    total: number;
    page: number;
    per_page: number;
    is_priority: boolean;
  }[];
  total: number;
};

const SECTION_CONFIGS: SectionConfig[] = [
  {
    key: "needs_reply",
    title: "Cần trả lời",
    isPriority: true,
  },
  ...LEAD_STAGES.map((stage) => ({
    key: stage.value,
    title: stage.label,
  })),
];

const createSectionPages = () =>
  SECTION_CONFIGS.reduce(
    (acc, section) => ({ ...acc, [section.key]: 1 }),
    {} as Record<SectionKey, number>,
  );

const createSectionResults = (isLoading: boolean) =>
  SECTION_CONFIGS.reduce(
    (acc, section) => ({
      ...acc,
      [section.key]: {
        key: section.key,
        title: section.title,
        leads: [],
        total: 0,
        page: 1,
        perPage: SECTION_PER_PAGE,
        isPriority: section.isPriority,
        isLoading,
        error: false,
      },
    }),
    {} as Record<SectionKey, SectionResult>,
  );

export const LeadListContent = ({
  searchQuery,
  sort,
  onTotalChange,
}: {
  searchQuery: string;
  sort: LeadSort;
  onTotalChange: (total: number) => void;
}) => {
  const refresh = useRefresh();
  const [selectedLeadId, setSelectedLeadId] = useState<string | number | null>(
    null,
  );
  const [sectionPages, setSectionPages] = useState(createSectionPages);
  const [sectionResults, setSectionResults] = useState(() =>
    createSectionResults(true),
  );
  const [refreshTick, setRefreshTick] = useState(0);

  const normalizedSearchQuery = searchQuery.trim();
  const sortField = sort?.field ?? "updated_at";
  const sortOrder = sort?.order === "ASC" ? "ASC" : "DESC";

  useEffect(() => {
    setSectionPages(createSectionPages());
  }, [normalizedSearchQuery, sortField, sortOrder]);

  useEffect(() => {
    const refreshSections = () => setRefreshTick((value) => value + 1);

    window.addEventListener("vfic:lead-list-refresh", refreshSections);
    window.addEventListener("vfic:lead-updated", refreshSections);
    return () => {
      window.removeEventListener("vfic:lead-list-refresh", refreshSections);
      window.removeEventListener("vfic:lead-updated", refreshSections);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    setSectionResults((prev) =>
      SECTION_CONFIGS.reduce(
        (acc, section) => ({
          ...acc,
          [section.key]: {
            ...prev[section.key],
            isLoading: true,
            error: false,
          },
        }),
        {} as Record<SectionKey, SectionResult>,
      ),
    );

    const loadSections = async () => {
      try {
        const response = await apiJson<LeadBoardResponse>(
          "/api/v1/leads/board",
          {
            method: "POST",
            body: {
              q: normalizedSearchQuery || undefined,
              sort: sortField,
              order: sortOrder,
              per_page: SECTION_PER_PAGE,
              section_pages: sectionPages,
            },
          },
        );
        if (cancelled) return;
        setSectionResults(
          response.sections.reduce(
            (acc, section) => ({
              ...acc,
              [section.key as SectionKey]: {
                key: section.key,
                title: section.title,
                leads: section.data,
                total: section.total,
                page: section.page,
                perPage: section.per_page,
                isPriority: section.is_priority,
                isLoading: false,
                error: false,
              },
            }),
            {} as Record<SectionKey, SectionResult>,
          ),
        );
        onTotalChange(response.total);
      } catch {
        if (cancelled) return;
        setSectionResults((prev) =>
          SECTION_CONFIGS.reduce(
            (acc, section) => ({
              ...acc,
              [section.key]: {
                ...prev[section.key],
                leads: [],
                total: 0,
                isLoading: false,
                error: true,
              },
            }),
            {} as Record<SectionKey, SectionResult>,
          ),
        );
        onTotalChange(0);
      }
    };

    void loadSections();

    return () => {
      cancelled = true;
    };
  }, [
    onTotalChange,
    refreshTick,
    normalizedSearchQuery,
    sectionPages,
    sortField,
    sortOrder,
  ]);

  const handleLeadSelect = useCallback((lead: Lead) => {
    setSelectedLeadId(lead.id);
  }, []);

  const handleRefresh = useCallback(() => {
    refresh();
    setRefreshTick((value) => value + 1);
  }, [refresh]);

  const allSections = useMemo(
    () =>
      SECTION_CONFIGS.map((section) => ({
        ...sectionResults[section.key],
      })),
    [sectionResults],
  );

  const isAnySectionLoading = allSections.some((section) => section.isLoading);
  const hasAnyLead = allSections.some((section) => section.total > 0);
  const hasEverySectionError = allSections.every((section) => section.error);

  if (
    !isAnySectionLoading &&
    !hasAnyLead &&
    !normalizedSearchQuery &&
    !hasEverySectionError
  ) {
    return (
      <EmptyState
        icon={<Users className="size-6" />}
        title="Chưa có ứng viên"
        description="Ứng viên được tạo tự động khi ứng viên nhắn tin qua Zalo. Nhấp vào một ứng viên để xem chi tiết."
        actions={
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="size-4" />
            Làm mới
          </Button>
        }
      />
    );
  }

  return (
    <>
      <div className="space-y-6">
        <LeadPriorityLegend />
        {allSections.map((section) => (
          <LeadSection
            key={section.key}
            title={section.title}
            leads={section.leads}
            total={section.total}
            page={section.page}
            perPage={SECTION_PER_PAGE}
            isPriority={section.isPriority}
            isLoading={section.isLoading}
            error={section.error}
            emptyText={
              section.key === "needs_reply"
                ? "Không có ứng viên cần trả lời."
                : "Không có ứng viên trong mục này."
            }
            onPageChange={(page) => {
              setSectionPages((prev) => ({ ...prev, [section.key]: page }));
            }}
          >
            {section.leads.map((lead) => (
              <LeadCard
                key={lead.id}
                lead={lead}
                onClick={handleLeadSelect}
              />
            ))}
          </LeadSection>
        ))}
      </div>
      <Sheet
        open={!!selectedLeadId}
        onOpenChange={(open) => !open && setSelectedLeadId(null)}
      >
        <SheetContent
          side="right"
          className="flex w-full flex-col gap-0 p-0 sm:max-w-[480px] lg:max-w-[600px] border-l"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>Chi tiết ứng viên</SheetTitle>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col">
            {selectedLeadId && (
              <ShowBase resource="leads" id={selectedLeadId}>
                <LeadShowContentSheet />
              </ShowBase>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};

const PRIORITY_LEGEND = [
  {
    label: "Cần chăm sóc",
    className:
      "border-rose-300/70 bg-rose-100/80 text-rose-700 dark:border-rose-500/45 dark:bg-rose-950/45 dark:text-rose-300",
  },
  {
    label: "Cần theo dõi",
    className:
      "border-amber-300/70 bg-amber-100/80 text-amber-700 dark:border-amber-500/45 dark:bg-amber-950/45 dark:text-amber-300",
  },
  {
    label: "Bình thường",
    className: "border-border bg-muted text-muted-foreground",
  },
];

const LeadPriorityLegend = () => (
  <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
    <span className="font-medium text-foreground">Mức độ ưu tiên</span>
    {PRIORITY_LEGEND.map((item) => (
      <span key={item.label} className="inline-flex items-center gap-1.5">
        <span
          className={cn(
            "inline-flex size-5 items-center justify-center rounded-full border ring-1 ring-border/60",
            item.className,
          )}
        >
          <UserRound className="size-3" aria-hidden="true" />
        </span>
        {item.label}
      </span>
    ))}
  </div>
);

const LeadSection = ({
  title,
  leads,
  total,
  page,
  perPage,
  emptyText,
  isLoading,
  error,
  isPriority,
  onPageChange,
  children,
}: {
  title: string;
  leads: Lead[];
  total: number;
  page: number;
  perPage: number;
  emptyText: string;
  isLoading: boolean;
  error: boolean;
  isPriority?: boolean;
  onPageChange: (page: number) => void;
  children: ReactNode;
}) => {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const start = total === 0 ? 0 : (page - 1) * perPage + 1;
  const end = Math.min(total, page * perPage);
  const showPager = total > perPage;

  return (
    <section className="space-y-3">
      <div
        className={cn(
          "flex min-h-9 items-center justify-between gap-3 border-b border-border/70 pb-2",
          isPriority && "border-primary/25",
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          <h2
            className={cn(
              "truncate text-sm font-semibold text-foreground",
              isPriority && "text-primary",
            )}
          >
            {title}
          </h2>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums text-muted-foreground">
            {total}
          </span>
        </div>
        {isLoading && (
          <span className="text-xs font-medium text-muted-foreground">
            Đang cập nhật
          </span>
        )}
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-5 text-sm text-destructive">
          Không tải được danh sách ứng viên.
        </div>
      ) : leads.length > 0 ? (
        <div className={CARD_GRID_CLASS}>{children}</div>
      ) : isLoading ? (
        <div className={CARD_GRID_CLASS}>
          {Array.from({ length: 3 }).map((_, i) => (
            <LeadCardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border/80 px-4 py-5 text-sm text-muted-foreground">
          {emptyText}
        </div>
      )}

      {showPager && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
          <span className="tabular-nums">
            {start}-{end} / {total}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-card text-foreground shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] transition-colors hover:border-primary/35 hover:bg-card disabled:cursor-not-allowed disabled:opacity-50 dark:border-border/80 dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)] dark:hover:bg-accent/20"
              disabled={isLoading || page <= 1}
              onClick={() => onPageChange(Math.max(1, page - 1))}
              aria-label={`Trang trước của ${title}`}
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="min-w-16 text-center tabular-nums">
              {page} / {totalPages}
            </span>
            <button
              type="button"
              className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-card text-foreground shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] transition-colors hover:border-primary/35 hover:bg-card disabled:cursor-not-allowed disabled:opacity-50 dark:border-border/80 dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)] dark:hover:bg-accent/20"
              disabled={isLoading || page >= totalPages}
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              aria-label={`Trang tiếp theo của ${title}`}
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

const LeadCardSkeleton = () => (
  <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] dark:border-border/80 dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)]">
    <div className="flex items-center gap-2">
      <Skeleton shimmer className="size-7 shrink-0 rounded-full" />
      <div className="min-w-0 flex-1">
        <Skeleton shimmer className="h-3.5 w-1/2 rounded" />
      </div>
      <Skeleton shimmer className="size-7 shrink-0 rounded-md" />
    </div>
  </div>
);
