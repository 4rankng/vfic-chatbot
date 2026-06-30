import { ArrowDownUp, ChevronDown, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";

export type LeadSort = {
  field: string;
  order: "ASC" | "DESC";
};

const SORT_OPTIONS: (LeadSort & { label: string })[] = [
  { field: "updated_at", order: "DESC", label: "Cần xử lý trước" },
  { field: "updated_at", order: "ASC", label: "Cập nhật cũ nhất" },
  { field: "created_at", order: "DESC", label: "Mới tạo nhất" },
  { field: "name", order: "ASC", label: "Tên (A → Z)" },
];

const toolbarBtnClass =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-sm font-medium text-foreground shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] transition-colors hover:border-primary/35 hover:bg-card hover:shadow-[0_4px_14px_rgba(26,34,40,0.11),0_1px_3px_rgba(26,34,40,0.08)] dark:border-border/80 dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)] dark:hover:border-primary/35 dark:hover:bg-accent/20";

const toolbarInputClass =
  "border-border bg-card pr-16 shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] placeholder:text-muted-foreground/80 hover:border-primary/25 focus-visible:border-primary/45 dark:border-border/80 dark:bg-card dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)]";

const toolbarMenuContentClass =
  "border-border bg-popover shadow-[0_12px_28px_rgba(26,34,40,0.16),0_4px_10px_rgba(26,34,40,0.08)] dark:border-border/80 dark:shadow-[0_16px_32px_rgba(0,0,0,0.44)]";

export const LeadsToolbar = ({
  searchQuery,
  sort,
  onSearchQueryChange,
  onSortChange,
}: {
  searchQuery: string;
  sort: LeadSort;
  onSearchQueryChange: (value: string) => void;
  onSortChange: (sort: LeadSort) => void;
}) => {
  const activeSortKey = `${sort.field}|${sort.order}`;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[220px] flex-1">
        <Input
          type="search"
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
          placeholder="Tìm tên, SĐT hoặc vị trí..."
          className={toolbarInputClass}
        />
        <Search className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        {searchQuery && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onSearchQueryChange("")}
            className="absolute right-8 top-1/2 size-6 -translate-y-1/2 rounded-full p-0 text-muted-foreground"
            aria-label="Xóa tìm kiếm"
          >
            <X className="size-3" />
          </Button>
        )}
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className={toolbarBtnClass}>
            <ArrowDownUp className="size-4" />
            <span className="hidden sm:inline">Sắp xếp</span>
            <ChevronDown className="size-3.5 opacity-60" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className={`w-56 ${toolbarMenuContentClass}`}
        >
          <DropdownMenuLabel>Sắp xếp theo</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {SORT_OPTIONS.map((opt) => (
            <DropdownMenuCheckboxItem
              key={opt.label}
              checked={activeSortKey === `${opt.field}|${opt.order}`}
              onCheckedChange={(checked) => {
                if (checked) {
                  onSortChange({ field: opt.field, order: opt.order });
                }
              }}
            >
              {opt.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};
