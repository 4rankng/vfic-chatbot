import { useMemo, type ReactNode } from "react";
import {
  RecordContextProvider,
  useListContext,
  useListPaginationContext,
  useTranslate,
} from "ra-core";
import { Table } from "@/components/application/table/table";
import { Pagination } from "@/components/application/pagination/pagination-base";
import { Button } from "@/components/base/buttons/button";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { cx } from "@/utils/cx";
import { EmptyState } from "./page-shell";

/**
 * Table and pagination primitives bound to react-admin's list context.
 *
 * `ListTable` renders Untitled UI v8's `Table` (a React Aria table) against the
 * records, loading and error state `useListContext` already provides, and ends
 * with `ListPagination`. Columns and the row actions cell come from the caller,
 * so a screen supplies its own cells and this file owns the surface: one card
 * frame, one count strip, one skeleton, one empty state, one pager. Every cell
 * body is wrapped in react-admin's `RecordContextProvider`, so a cell component
 * may call `useRecordContext()` exactly as it would inside react-admin's
 * `Datagrid`.
 *
 * `uu-scope` on the card is required, not decorative — inside it the four
 * utility names the console and Untitled UI both define (`bg-primary`,
 * `bg-secondary`, `text-primary`, `border-primary`) take Untitled UI's meaning,
 * which this repo maps onto the console palette. See
 * `src/styles/untitledui-theme.css`.
 *
 * A React Aria subtree and a Radix (`@/components/ui/**`) subtree must not nest,
 * so cell renderers must stay on React Aria / plain DOM primitives.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing".
 */

export type ListTableColumn<RecordType> = {
  /** Stable column key, also the React Aria column id. */
  id: string;
  /** A string renders as the console's column caption; an element is rendered as-is. */
  header: ReactNode;
  /** The cell body for one record. */
  cell: (record: RecordType) => ReactNode;
  /** Marks the column carrying the row's accessible name. */
  isRowHeader?: boolean;
  headClassName?: string;
  cellClassName?: string;
};

export type ListTableClassNames = {
  table?: string;
  head?: string;
  body?: string;
  row?: string;
  /** The trailing actions column's header cell (e.g. a fixed width). */
  actionsHead?: string;
  actionsCell?: string;
};

type ListTableProps<RecordType extends { id: string | number }> = {
  /** Accessible name of the table. */
  ariaLabel: string;
  columns: ListTableColumn<RecordType>[];
  /** Rendered per row in the trailing actions cell. */
  rowActions?: (record: RecordType) => ReactNode;
  /** Accessible name of the trailing actions column. */
  actionsLabel?: string;
  /** Rendered above the table, inside the card (e.g. the count strip). */
  header?: ReactNode;
  empty: {
    icon: ReactNode;
    title: ReactNode;
    description: ReactNode;
    action?: ReactNode;
  };
  /** Extra class names for the caller's stylesheet. */
  classNames?: ListTableClassNames;
  className?: string;
  skeletonRows?: number;
  /** `false` hides the pager. */
  pagination?: false | { rowsPerPageOptions?: number[] };
};

export const ListTable = <RecordType extends { id: string | number }>({
  ariaLabel,
  columns,
  rowActions,
  actionsLabel = "Thao tác",
  header,
  empty,
  classNames,
  className,
  skeletonRows = 4,
  pagination,
}: ListTableProps<RecordType>) => {
  const { data, isPending, error, refetch } = useListContext<RecordType>();
  const records = data ?? [];
  const actionsCellClassName = classNames?.actionsCell;
  const actionsHeadClassName = classNames?.actionsHead;
  // A stable identity matters: React Aria rebuilds its column collection when
  // the `columns` array changes, so a fresh array on every render would thrash
  // the table (and, with a render prop, loop).
  const allColumns = useMemo<ListTableColumn<RecordType>[]>(
    () =>
      rowActions
        ? [
            ...columns,
            {
              id: "__actions",
              header: actionsLabel,
              headClassName: actionsHeadClassName,
              cell: (record) => rowActions(record),
              cellClassName: cx("text-right", actionsCellClassName),
            },
          ]
        : columns,
    [
      actionsHeadClassName,
      actionsLabel,
      actionsCellClassName,
      columns,
      rowActions,
    ],
  );
  // Passed through `cx` (and through the PRO components' own `cx`), so the
  // console's `text-caption` role token is written as an explicit length:
  // tailwind-merge does not know the console's `--text-*` names and would
  // otherwise drop it as a duplicate text colour.
  const headClassName =
    "bg-[var(--workspace-surface-muted)] px-3 py-2 text-left text-[length:var(--fs-caption)] font-semibold tracking-[0.05em] uppercase text-tertiary";

  if (isPending) {
    return (
      <div
        className={cx(
          "uu-scope flex flex-col overflow-hidden rounded-panel border border-secondary bg-primary",
          className,
        )}
        role="status"
        aria-label="Đang tải danh sách"
      >
        {Array.from({ length: skeletonRows }).map((_, index) => (
          <div
            key={index}
            className="flex min-h-17 items-center gap-3 border-b border-secondary px-3 py-2.5 last:border-b-0"
          >
            <span className="size-9 shrink-0 animate-pulse rounded-full bg-tertiary" />
            <span className="flex-1 space-y-2">
              <span className="block h-4 w-40 max-w-full animate-pulse rounded bg-tertiary" />
              <span className="block h-3 w-56 max-w-full animate-pulse rounded bg-tertiary" />
            </span>
            <span className="h-6 w-24 shrink-0 animate-pulse rounded-full bg-tertiary" />
          </div>
        ))}
      </div>
    );
  }

  if (records.length === 0) {
    if (error) {
      return (
        <EmptyState
          role="alert"
          icon={<TriangleAlert aria-hidden="true" />}
          title="Chưa tải được danh sách"
          description="Hãy kiểm tra kết nối và thử lại."
          action={
            <Button
              color="secondary"
              size="md"
              iconLeading={RefreshCw}
              onClick={() => void refetch()}
            >
              Thử lại
            </Button>
          }
          className={className}
        />
      );
    }
    return (
      <EmptyState
        icon={empty.icon}
        title={empty.title}
        description={empty.description}
        action={empty.action}
        className={cx("uu-scope", className)}
      />
    );
  }

  return (
    <section
      className={cx(
        "uu-scope overflow-hidden rounded-panel border border-secondary bg-primary",
        className,
      )}
    >
      {header}
      <Table
        aria-label={ariaLabel}
        selectionMode="none"
        className={classNames?.table}
      >
        <Table.Header className={classNames?.head} columns={allColumns}>
          {(column: ListTableColumn<RecordType>) =>
            typeof column.header === "string" ? (
              <Table.Head
                id={column.id}
                label={column.header}
                isRowHeader={column.isRowHeader}
                className={cx(headClassName, column.headClassName)}
              />
            ) : (
              <Table.Head
                id={column.id}
                isRowHeader={column.isRowHeader}
                className={cx(headClassName, column.headClassName)}
              >
                {column.header}
              </Table.Head>
            )
          }
        </Table.Header>
        <Table.Body className={classNames?.body} items={records}>
          {(record: RecordType) => (
            <Table.Row
              id={String(record.id)}
              columns={allColumns}
              className={cx("h-auto!", classNames?.row)}
            >
              {(column: ListTableColumn<RecordType>) => (
                <Table.Cell
                  className={cx("p-3 align-middle", column.cellClassName)}
                >
                  {/* react-admin's `Datagrid` gives every cell a record
                      context, so cell components may legally call
                      `useRecordContext()` (the users directory's no-props
                      badges and row actions do). The wrap must sit inside the
                      row's children function: React Aria renders only the
                      cells from that function into the real DOM, so a
                      provider around the `Table.Row` never wraps them. */}
                  <RecordContextProvider value={record}>
                    {column.cell(record)}
                  </RecordContextProvider>
                </Table.Cell>
              )}
            </Table.Row>
          )}
        </Table.Body>
      </Table>
      {pagination === false ? null : (
        <ListPagination rowsPerPageOptions={pagination?.rowsPerPageOptions} />
      )}
    </section>
  );
};

/**
 * The console's pager: Untitled UI's `Pagination.Root` (page windowing, current
 * page, prev/next disabled states) with the console's Vietnamese copy and
 * react-admin's list context. Reads `useListPaginationContext`, so it must be
 * rendered inside a `ListBase`.
 *
 * Total `-1` is react-admin's "unknown total": the pager then walks one page at
 * a time instead of inventing a page count.
 */
export const ListPagination = ({
  rowsPerPageOptions = [10, 25, 50, 100],
  className,
}: {
  rowsPerPageOptions?: number[];
  className?: string;
}) => {
  const translate = useTranslate();
  const { data } = useListContext();
  const {
    hasNextPage,
    hasPreviousPage,
    page,
    perPage,
    setPage,
    setPerPage,
    total,
  } = useListPaginationContext();

  const knownTotal = total ?? -1;
  const resolvedTotal = knownTotal === -1 ? page * perPage : knownTotal;
  const hasResults =
    knownTotal === -1 ? Boolean(data?.length) : resolvedTotal > 0;
  const pageStart = hasResults ? (page - 1) * perPage + 1 : 0;
  const pageEnd = hasResults
    ? knownTotal === -1
      ? (page - 1) * perPage + (data?.length ?? perPage)
      : Math.min(page * perPage, resolvedTotal)
    : 0;
  const pageCount =
    knownTotal === -1
      ? page + (hasNextPage ? 1 : 0)
      : knownTotal > 0
        ? Math.ceil(knownTotal / perPage)
        : 1;
  const sizeItems: SelectItemType[] = rowsPerPageOptions.map((size) => ({
    id: String(size),
    label: String(size),
  }));
  const previousLabel = translate("ra.navigation.previous", {
    _: "Về trang trước",
  });
  const nextLabel = translate("ra.navigation.next", { _: "Trang tiếp" });

  return (
    <div
      className={cx(
        "uu-scope flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-secondary px-3 py-2.5 sm:justify-end",
        className,
      )}
    >
      <div className="hidden items-center gap-2 md:flex">
        <span className="text-[length:var(--fs-helper)] text-tertiary">
          {translate("ra.navigation.page_rows_per_page", {
            _: "Số dòng mỗi trang",
          })}
        </span>
        <UntitledSelect
          size="sm"
          className="uu-scope w-20"
          aria-label={translate("ra.navigation.page_rows_per_page", {
            _: "Số dòng mỗi trang",
          })}
          items={sizeItems}
          selectedKey={String(perPage)}
          onSelectionChange={(key) => setPerPage(Number(key))}
        >
          {(item: SelectItemType) => (
            <UntitledSelect.Item id={item.id} label={item.label} />
          )}
        </UntitledSelect>
      </div>

      <span className="text-[length:var(--fs-helper)] tabular-nums text-tertiary">
        {hasResults
          ? knownTotal === -1
            ? `${pageStart}-${pageEnd}`
            : `${pageStart}-${pageEnd} / ${resolvedTotal}`
          : translate("ra.navigation.page_range_empty", {
              _: "Không có kết quả",
            })}
      </span>

      <Pagination.Root
        page={page}
        total={pageCount}
        onPageChange={setPage}
        className="flex min-w-0 flex-wrap items-center gap-0.5"
      >
        <Pagination.PrevTrigger ariaLabel={previousLabel} asChild>
          <Button
            color="secondary"
            size="md"
            iconLeading={ChevronLeft}
            className={cx(!hasPreviousPage && "cursor-not-allowed")}
          />
        </Pagination.PrevTrigger>

        <span
          className="px-2 text-helper tabular-nums text-tertiary sm:hidden"
          aria-live="polite"
        >
          {knownTotal === -1 ? `Trang ${page}` : `Trang ${page} / ${pageCount}`}
        </span>

        <Pagination.Context>
          {({ pages }) => (
            <div className="hidden items-center gap-0.5 sm:flex">
              {pages.map((item) =>
                item.type === "page" ? (
                  <Pagination.Item
                    key={item.value}
                    value={item.value}
                    isCurrent={item.isCurrent}
                    ariaLabel={`Trang ${item.value}`}
                  >
                    {({ onClick, isSelected, ...aria }) => (
                      <button
                        type="button"
                        onClick={onClick}
                        aria-current={aria["aria-current"]}
                        aria-label={aria["aria-label"]}
                        className={cx(
                          "flex size-10 items-center justify-center rounded-lg text-[length:var(--fs-body)] font-medium tabular-nums text-tertiary outline-focus-ring transition-colors hover:bg-secondary hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2",
                          isSelected &&
                            "bg-secondary font-semibold text-primary",
                        )}
                      >
                        {item.value}
                      </button>
                    )}
                  </Pagination.Item>
                ) : (
                  <Pagination.Ellipsis
                    key={item.key}
                    className="flex size-10 items-center justify-center text-tertiary"
                  />
                ),
              )}
            </div>
          )}
        </Pagination.Context>

        <Pagination.NextTrigger ariaLabel={nextLabel} asChild>
          <Button
            color="secondary"
            size="md"
            iconLeading={ChevronRight}
            className={cx(!hasNextPage && "cursor-not-allowed")}
          />
        </Pagination.NextTrigger>
      </Pagination.Root>
    </div>
  );
};
