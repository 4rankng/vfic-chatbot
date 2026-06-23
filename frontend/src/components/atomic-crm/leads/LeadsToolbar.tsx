import type { ReactNode } from "react";
import { FilterLiveForm, useListContext } from "ra-core";
import { ArrowDownUp, ChevronDown, LayoutGrid, List } from "lucide-react";
import { SearchInput } from "@/components/admin";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { LEAD_SCORES, LEAD_STAGES } from "../types";

const SORT_OPTIONS: { field: string; order: "ASC" | "DESC"; label: string }[] =
  [
    { field: "updated_at", order: "DESC", label: "Cập nhật mới nhất" },
    { field: "updated_at", order: "ASC", label: "Cập nhật cũ nhất" },
    { field: "created_at", order: "DESC", label: "Mới tạo nhất" },
    { field: "name", order: "ASC", label: "Tên (A → Z)" },
  ];

const toolbarBtnClass =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/70 bg-card/60 px-3 text-sm font-medium text-foreground backdrop-blur transition-colors hover:bg-accent";

/**
 * Lead list toolbar. Search (?q=, full-text on name/phone/desired_job/zalo_id —
 * configured in the supabase dataProvider), single-select stage filter
 * (?lead_stage=), single-select score filter (?lead_score=), and sort
 * (?sort=&order=). All state lives in the URL via useListContext.
 *
 * NOTE on filter composition: ra-core `setFilters` REPLACES the filter object
 * (useListParams SET_FILTER → removeEmpty(filter)), so each control passes the
 * full merged filter set. The search `<FilterLiveForm>` merges its `q` into the
 * current filterValues on submit, so search never wipes the stage/score filters.
 */
export const LeadsToolbar = () => {
  const { filterValues, setFilters, sort, setSort } = useListContext();
  const filters = filterValues ?? {};
  const stage = filters.lead_stage as string | undefined;
  const score = filters.lead_score as string | undefined;

  const applyFilter = (key: string, value?: string) => {
    const next = { ...filters };
    delete next[key];
    setFilters(value ? { ...next, [key]: value } : next);
  };

  const activeSortKey = sort
    ? `${sort.field}|${sort.order}`
    : "updated_at|DESC";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-[220px] flex-1">
        <FilterLiveForm>
          <SearchInput source="q" placeholder="Tìm tên, SĐT, công việc…" />
        </FilterLiveForm>
      </div>

      <FilterPill
        label="Giai đoạn"
        selectedLabel={LEAD_STAGES.find((s) => s.value === stage)?.label}
        active={Boolean(stage)}
        onClear={() => applyFilter("lead_stage")}
      >
        {LEAD_STAGES.map((s) => (
          <DropdownMenuCheckboxItem
            key={s.value}
            checked={s.value === stage}
            onCheckedChange={(checked) => {
              if (checked) applyFilter("lead_stage", s.value);
            }}
          >
            {s.label}
          </DropdownMenuCheckboxItem>
        ))}
      </FilterPill>

      <FilterPill
        label="Điểm"
        selectedLabel={LEAD_SCORES.find((s) => s.value === score)?.label}
        active={Boolean(score)}
        onClear={() => applyFilter("lead_score")}
      >
        {LEAD_SCORES.map((s) => (
          <DropdownMenuCheckboxItem
            key={s.value}
            checked={s.value === score}
            onCheckedChange={(checked) => {
              if (checked) applyFilter("lead_score", s.value);
            }}
          >
            {s.label}
          </DropdownMenuCheckboxItem>
        ))}
      </FilterPill>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className={toolbarBtnClass}>
            <ArrowDownUp className="size-4" />
            <span className="hidden sm:inline">Sắp xếp</span>
            <ChevronDown className="size-3.5 opacity-60" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuLabel>Sắp xếp theo</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {SORT_OPTIONS.map((opt) => (
            <DropdownMenuCheckboxItem
              key={opt.label}
              checked={activeSortKey === `${opt.field}|${opt.order}`}
              onCheckedChange={(checked) => {
                if (checked) setSort({ field: opt.field, order: opt.order });
              }}
            >
              {opt.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Desktop-only view-mode toggle. The board (Phase 4) is gated behind a
          stakeholder decision, so "Bảng" stays inert until <LeadBoard/> ships. */}
      <div
        className="hidden items-center gap-0.5 rounded-lg border border-border/70 bg-card/60 p-0.5 backdrop-blur md:flex"
        aria-label="Chế độ xem"
      >
        <span className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-foreground">
          <List className="size-3.5" />
          Danh sách
        </span>
        <span
          className="inline-flex h-8 cursor-not-allowed items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted-foreground/60"
          title="Sắp ra mắt"
          aria-disabled="true"
        >
          <LayoutGrid className="size-3.5" />
          Bảng
        </span>
      </div>
    </div>
  );
};

const FilterPill = ({
  label,
  selectedLabel,
  active,
  onClear,
  children,
}: {
  label: string;
  selectedLabel?: string;
  active: boolean;
  onClear: () => void;
  children: ReactNode;
}) => (
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <button
        type="button"
        className={cn(
          toolbarBtnClass,
          active && "border-primary/50 text-primary",
        )}
      >
        <span>{label}</span>
        {selectedLabel && (
          <span className="text-muted-foreground">· {selectedLabel}</span>
        )}
        <ChevronDown className="size-3.5 opacity-60" />
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" className="w-52">
      <DropdownMenuLabel>{label}</DropdownMenuLabel>
      {active && (
        <>
          <DropdownMenuItem onClick={onClear}>Tất cả</DropdownMenuItem>
          <DropdownMenuSeparator />
        </>
      )}
      {children}
    </DropdownMenuContent>
  </DropdownMenu>
);
