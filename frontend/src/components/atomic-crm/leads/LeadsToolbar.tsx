import { FilterLiveForm, useListContext } from "ra-core";
import { ArrowDownUp, ChevronDown } from "lucide-react";
import { SearchInput } from "@/components/admin";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const SORT_OPTIONS: { field: string; order: "ASC" | "DESC"; label: string }[] =
  [
    { field: "updated_at", order: "DESC", label: "Cần xử lý trước" },
    { field: "updated_at", order: "ASC", label: "Cập nhật cũ nhất" },
    { field: "created_at", order: "DESC", label: "Mới tạo nhất" },
    { field: "name", order: "ASC", label: "Tên (A → Z)" },
  ];

const toolbarBtnClass =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/70 bg-card/60 px-3 text-sm font-medium text-foreground backdrop-blur transition-colors hover:bg-accent";

export const LeadsToolbar = () => {
  const { setSort, sort } = useListContext();

  const activeSortKey = sort
    ? `${sort.field}|${sort.order}`
    : "updated_at|DESC";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-[220px] flex-1">
        <FilterLiveForm>
          <SearchInput source="q" placeholder="Tìm tên, SĐT hoặc vị trí..." />
        </FilterLiveForm>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className={toolbarBtnClass}>
            <ArrowDownUp className="size-4" />
            <span className="hidden sm:inline">Sắp xếp</span>
            <ChevronDown className="size-3.5 opacity-60" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
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
    </div>
  );
};
