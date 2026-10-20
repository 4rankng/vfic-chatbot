import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import { InputBase } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { Pagination } from "@/components/application/pagination/pagination-base";
import { Table } from "@/components/application/table/table";
import { cx } from "@/utils/cx";
import { EmptyState } from "../kit/page-shell";

import { zaloIntegrationGateway, type CloudfoneTranscriptSummary } from "./api";

/**
 * The stored voice-call transcripts viewer, reached from the Cloudfone
 * settings section: a filter bar (call day, phone fragment) over
 * `cloudfone_call_transcripts`, one page of rows at a time, and the full
 * transcript of the selected call below the table.
 *
 * Surface anatomy is Untitled UI's settings data table (filter bar → table
 * card → count strip + pagination), built from the vendored UUI primitives —
 * `frontend/AGENTS.md` § "UI/UX Component Sourcing". No Radix in this subtree:
 * React Aria owns the whole page.
 */

const PAGE_SIZE = 20;

/** "2026-10-01T17:02:35" → "01/10/2026 17:02" (Vietnam display order). */
const fmtStarted = (iso: string): string => {
  const [datePart = "", timePart = ""] = iso.split("T");
  const [y, m, d] = datePart.split("-");
  if (!y || !m || !d) return iso;
  return `${d}/${m}/${y} ${timePart.slice(0, 5)}`;
};

/** 88 → "1p28s", 45 → "45s" — the daily letter's duration format. */
const fmtDuration = (seconds: number): string =>
  seconds >= 60
    ? `${Math.floor(seconds / 60)}p${seconds % 60}s`
    : `${seconds}s`;

type TranscriptColumn = {
  id: string;
  header: string;
  cell: (row: CloudfoneTranscriptSummary) => React.ReactNode;
  isRowHeader?: boolean;
  cellClassName?: string;
};

const COLUMNS: TranscriptColumn[] = [
  {
    id: "started_at",
    header: "Thời gian",
    cell: (row) => (
      <span className="tabular-nums">{fmtStarted(row.started_at)}</span>
    ),
  },
  {
    id: "caller",
    header: "Số điện thoại",
    isRowHeader: true,
    cell: (row) => <span className="tabular-nums">{row.caller}</span>,
  },
  {
    id: "talk_seconds",
    header: "Thời lượng",
    cell: (row) => (
      <span className="tabular-nums">{fmtDuration(row.talk_seconds)}</span>
    ),
  },
  {
    id: "transcript_preview",
    header: "Tóm tắt",
    cell: (row) => (
      <span className="line-clamp-2 text-body-sm text-tertiary">
        {row.transcript_preview}
      </span>
    ),
  },
];

export const CloudfoneTranscriptsSection = ({
  onBack,
}: {
  onBack: () => void;
}) => {
  const [day, setDay] = useState("");
  const [callerDraft, setCallerDraft] = useState("");
  const [caller, setCaller] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: ["cloudfone-transcripts", { day, caller, page }],
    queryFn: () =>
      zaloIntegrationGateway.listCloudfoneTranscripts({
        day: day || undefined,
        caller: caller || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    staleTime: 30_000,
  });
  const detailQuery = useQuery({
    queryKey: ["cloudfone-transcript", selectedId],
    queryFn: () => zaloIntegrationGateway.loadCloudfoneTranscript(selectedId!),
    enabled: Boolean(selectedId),
    staleTime: 300_000,
  });

  const pageData = listQuery.data;
  const items = pageData?.items ?? [];
  const total = pageData?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(page * PAGE_SIZE, total);
  const filtered = Boolean(day || caller);

  const applyCaller = (event: FormEvent) => {
    event.preventDefault();
    setCaller(callerDraft.trim());
    setPage(1);
    setSelectedId(null);
  };

  const clearFilters = () => {
    setDay("");
    setCallerDraft("");
    setCaller("");
    setPage(1);
    setSelectedId(null);
  };

  const columns: TranscriptColumn[] = [
    ...COLUMNS,
    {
      id: "actions",
      header: "",
      cellClassName: "w-24",
      // State-independent on purpose: React Aria table rows memoize their
      // content per item, so selection state must not leak into cells. The
      // open/close lifecycle lives in the detail panel below the table.
      cell: (row) => (
        <Button
          type="button"
          color="secondary"
          size="sm"
          className="tt-btn-touch"
          onClick={() => setSelectedId(row.call_id)}
        >
          Xem
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          color="secondary"
          size="md"
          iconLeading={ChevronLeft}
          className="uu-scope tt-btn-touch"
          onClick={onBack}
        >
          Quay lại cài đặt Cloudfone
        </Button>
      </div>

      <form
        className="uu-scope flex flex-wrap items-end gap-3"
        onSubmit={applyCaller}
      >
        <div className="flex w-48 flex-col gap-1.5">
          <Label htmlFor="cloudfone-transcripts-day" isRequired={false}>
            Ngày cuộc gọi
          </Label>
          <InputBase
            id="cloudfone-transcripts-day"
            type="date"
            value={day}
            onChange={(event) => {
              setDay(event.target.value);
              setPage(1);
              setSelectedId(null);
            }}
          />
        </div>
        <div className="flex w-64 flex-col gap-1.5">
          <Label htmlFor="cloudfone-transcripts-caller" isRequired={false}>
            Số điện thoại
          </Label>
          <InputBase
            id="cloudfone-transcripts-caller"
            placeholder="Nhập một phần số…"
            value={callerDraft}
            onChange={(event) => setCallerDraft(event.target.value)}
          />
        </div>
        <Button
          type="submit"
          color="secondary"
          size="md"
          iconLeading={Search}
          className="tt-btn-touch"
        >
          Lọc
        </Button>
        {filtered ? (
          <Button
            type="button"
            color="secondary"
            size="md"
            iconLeading={X}
            className="tt-btn-touch"
            onClick={clearFilters}
          >
            Xóa lọc
          </Button>
        ) : null}
      </form>

      {listQuery.isPending ? (
        <section
          className="uu-scope overflow-hidden rounded-panel border border-secondary bg-primary"
          aria-busy="true"
        >
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="flex min-h-17 items-center gap-3 border-b border-secondary px-3 py-2.5 last:border-b-0"
            >
              <span className="flex-1 space-y-2">
                <span className="block h-4 w-40 max-w-full animate-pulse rounded bg-tertiary" />
                <span className="block h-3 w-56 max-w-full animate-pulse rounded bg-tertiary" />
              </span>
            </div>
          ))}
        </section>
      ) : listQuery.isError ? (
        <EmptyState
          role="alert"
          icon={<TriangleAlert aria-hidden="true" />}
          title="Chưa tải được bản ghi cuộc gọi"
          description="Hãy kiểm tra kết nối và thử lại."
          action={
            <Button
              color="secondary"
              size="md"
              iconLeading={RefreshCw}
              onClick={() => void listQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<FileText className="size-6" aria-hidden="true" />}
          title={
            filtered
              ? "Không tìm thấy bản ghi phù hợp"
              : "Chưa có bản ghi cuộc gọi"
          }
          description={
            filtered
              ? "Thử thay đổi ngày hoặc số điện thoại."
              : "Bản ghi sẽ xuất hiện tại đây sau khi hệ thống chạy phân tích cuộc gọi hằng ngày."
          }
          action={
            filtered ? (
              <Button color="secondary" size="md" onClick={clearFilters}>
                Xóa lọc
              </Button>
            ) : undefined
          }
        />
      ) : (
        <section className="uu-scope overflow-hidden rounded-panel border border-secondary bg-primary">
          <Table aria-label="Bản ghi cuộc gọi" selectionMode="none">
            <Table.Header columns={columns}>
              {(column: TranscriptColumn) => (
                <Table.Head
                  id={column.id}
                  label={column.header}
                  isRowHeader={column.isRowHeader}
                />
              )}
            </Table.Header>
            <Table.Body items={items}>
              {(row: CloudfoneTranscriptSummary) => (
                <Table.Row
                  id={row.call_id}
                  columns={columns}
                  className="h-auto!"
                >
                  {(column: TranscriptColumn) => (
                    <Table.Cell
                      className={cx("p-3 align-middle", column.cellClassName)}
                    >
                      {column.cell(row)}
                    </Table.Cell>
                  )}
                </Table.Row>
              )}
            </Table.Body>
          </Table>

          <div className="flex flex-wrap items-center gap-2 border-t border-secondary px-3 py-2.5">
            <span className="text-[length:var(--fs-helper)] tabular-nums text-tertiary">
              {pageStart}-{pageEnd} / {total}
            </span>

            <Pagination.Root
              page={page}
              total={pageCount}
              onPageChange={(next) => {
                setPage(next);
                setSelectedId(null);
              }}
              className="ml-auto flex min-w-0 flex-wrap items-center gap-0.5"
            >
              <Pagination.PrevTrigger ariaLabel="Về trang trước" asChild>
                <Button
                  color="secondary"
                  size="md"
                  iconLeading={ChevronLeft}
                  className={cx(page <= 1 && "cursor-not-allowed")}
                />
              </Pagination.PrevTrigger>

              <span
                className="px-2 text-helper tabular-nums text-tertiary sm:hidden"
                aria-live="polite"
              >
                Trang {page} / {pageCount}
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

              <Pagination.NextTrigger ariaLabel="Trang tiếp" asChild>
                <Button
                  color="secondary"
                  size="md"
                  iconLeading={ChevronRight}
                  className={cx(page >= pageCount && "cursor-not-allowed")}
                />
              </Pagination.NextTrigger>
            </Pagination.Root>
          </div>
        </section>
      )}

      {selectedId ? (
        <section className="uu-scope rounded-panel border border-secondary bg-primary">
          <header className="flex flex-wrap items-center gap-3 border-b border-secondary px-4 py-3">
            <FileText className="size-5 text-tertiary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-body-sm font-semibold text-primary">
                {detailQuery.data
                  ? `${detailQuery.data.caller} · ${fmtStarted(detailQuery.data.started_at)}`
                  : "Bản ghi cuộc gọi"}
              </p>
              {detailQuery.data ? (
                <p className="text-helper text-tertiary">
                  {fmtDuration(detailQuery.data.talk_seconds)} · lưu{" "}
                  {fmtStarted(detailQuery.data.created_at)}
                </p>
              ) : null}
            </div>
            <Button
              type="button"
              color="secondary"
              size="sm"
              iconLeading={X}
              aria-label="Đóng bản ghi"
              className="tt-btn-touch"
              onClick={() => setSelectedId(null)}
            />
          </header>
          <div className="px-4 py-3">
            {detailQuery.isPending ? (
              <div className="space-y-2" aria-busy="true">
                <span className="block h-3 w-3/4 animate-pulse rounded bg-tertiary" />
                <span className="block h-3 w-1/2 animate-pulse rounded bg-tertiary" />
              </div>
            ) : detailQuery.isError ? (
              <p role="alert" className="text-body-sm text-error">
                Chưa tải được nội dung bản ghi.
              </p>
            ) : (
              <p className="whitespace-pre-wrap text-body-sm text-primary">
                {detailQuery.data.transcript}
              </p>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
};
