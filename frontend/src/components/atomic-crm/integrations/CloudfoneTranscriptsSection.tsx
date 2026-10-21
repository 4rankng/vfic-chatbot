import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  CloudDownload,
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
 * `cloudfone_call_transcripts`, one page of results at a time, and the full
 * transcript of the selected call below the list.
 *
 * A day the daily pass never covered (it only reports on the previous day)
 * would show an empty table, so the viewer fetches such a day from Cloudfone
 * on demand: the list response carries the inspected-day marker, and a day
 * without one is pulled once (the transcripts are then stored like any other).
 * A day the system already checked is left alone — it is known, and it may
 * legitimately hold nothing.
 *
 * Surface anatomy is Untitled UI's settings data table (filter bar → table
 * card → count strip + pagination), built from the vendored UUI primitives —
 * `frontend/AGENTS.md` § "UI/UX Component Sourcing". No Radix in this subtree:
 * React Aria owns the whole page.
 * Two responsive surfaces, one dataset, chosen by matchMedia at the `sm`
 * breakpoint (640px) rather than by CSS: the vitest browser project compiles
 * no Tailwind, so a class-only swap would leave both surfaces queryable in
 * unit tests, and a JS swap also keeps exactly one surface in the a11y tree.
 *  - ≥640px keeps Untitled UI's settings data table (filter bar → table card →
 *    count strip + pagination), built from the vendored UUI primitives —
 *    `frontend/AGENTS.md` § "UI/UX Component Sourcing".
 *  - <640px swaps in a card list (phone + duration badge, then call time +
 *    a "đã lưu" marker per card), stacked full-width filters, and a compact
 *    Trước/Sau pager — a five-column data table never fits a 390px phone.
 *
 * No Radix in this subtree: React Aria owns the whole page.
 */

const PAGE_SIZE = 20;

/**
 * One on-demand fetch transcribes at most the daily cap, so a day with more
 * calls than that needs a second pass — the loop continues until the day is
 * done. The bound keeps a pathological day from looping forever.
 */
const MAX_BACKFILL_PASSES = 20;
/** Tailwind's `sm` breakpoint — below this the card list replaces the table. */
const PHONE_QUERY = "(max-width: 639px)";

// Read synchronously so the first render already picks the right surface
// (a phone must not paint the desktop table for one frame). False pre-hydration.
const subscribePhone = (onChange: () => void) => {
  const mql = window.matchMedia(PHONE_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
};

const useIsPhone = () =>
  useSyncExternalStore(
    subscribePhone,
    () => window.matchMedia(PHONE_QUERY).matches,
    () => false,
  );

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

/**
 * The previous ICT calendar day (the day the daily pass reports on) as
 * "YYYY-MM-DD". Vietnam has no DST, so the +7 offset is exact.
 */
const ictYesterday = (): string => {
  const shifted = new Date(Date.now() + 7 * 3_600_000 - 86_400_000);
  return shifted.toISOString().slice(0, 10);
};

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

/** The desktop count strip + page-number window (Untitled UI settings table). */
const DesktopPager = ({
  page,
  pageCount,
  pageStart,
  pageEnd,
  total,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  pageStart: number;
  pageEnd: number;
  total: number;
  onPageChange: (page: number) => void;
}) => (
  <div className="flex flex-wrap items-center gap-2 border-t border-secondary px-3 py-2.5">
    <span className="text-[length:var(--fs-helper)] tabular-nums text-tertiary">
      {pageStart}-{pageEnd} / {total}
    </span>

    <Pagination.Root
      page={page}
      total={pageCount}
      onPageChange={onPageChange}
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

      <Pagination.Context>
        {({ pages }) => (
          <div className="flex items-center gap-0.5">
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
                        isSelected && "bg-secondary font-semibold text-primary",
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
);

/** The phone pager: count + Trước/Sau text buttons + "1/1", no page window. */
const PhonePager = ({
  page,
  pageCount,
  pageStart,
  pageEnd,
  total,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  pageStart: number;
  pageEnd: number;
  total: number;
  onPageChange: (page: number) => void;
}) => (
  <div className="flex items-center justify-between gap-2 border-t border-secondary px-3 py-2.5">
    <span className="text-[length:var(--fs-helper)] tabular-nums text-tertiary">
      {pageStart}-{pageEnd} / {total}
    </span>
    <div className="flex items-center gap-1">
      <Button
        type="button"
        color="secondary"
        size="md"
        iconLeading={ChevronLeft}
        className="tt-btn-touch"
        isDisabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        Trước
      </Button>
      <span
        className="px-1 text-helper tabular-nums text-tertiary"
        aria-live="polite"
      >
        {page}/{pageCount}
      </span>
      <Button
        type="button"
        color="secondary"
        size="md"
        iconLeading={ChevronRight}
        className="tt-btn-touch"
        isDisabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        Sau
      </Button>
    </div>
  </div>
);

export const CloudfoneTranscriptsSection = ({
  onBack,
}: {
  onBack: () => void;
}) => {
  const isPhone = useIsPhone();
  const [day, setDay] = useState("");
  const [callerDraft, setCallerDraft] = useState("");
  const [caller, setCaller] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const queryClient = useQueryClient();

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

  /**
   * Pull a day from Cloudfone and store its transcripts.
   *
   * One pass transcribes at most the daily cap, so a day with more calls than
   * that continues in the next pass (the stored ones are reused, not
   * re-transcribed). The list is refreshed when the day is done.
   */
  const backfillMutation = useMutation({
    mutationFn: async ({
      day: target,
      force = false,
    }: {
      day: string;
      force?: boolean;
    }) => {
      for (let pass = 0; pass < MAX_BACKFILL_PASSES; pass += 1) {
        const result =
          await zaloIntegrationGateway.backfillCloudfoneTranscripts({
            day: target,
            force,
          });
        if (result.status !== "checked" || result.remaining === 0)
          return result;
        // The day is checked by now, so continuing needs the explicit force.
        force = true;
      }
      return null;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["cloudfone-transcripts"],
      });
    },
  });
  const { mutate: requestBackfill } = backfillMutation;

  const pageData = listQuery.data;
  const items = pageData?.items ?? [];
  const total = pageData?.total ?? 0;
  const dayState = pageData?.day_state ?? null;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(page * PAGE_SIZE, total);
  const filtered = Boolean(day || caller);

  /**
   * A day the system never checked is fetched once, on its own: the admin
   * opened a day, the stored table has nothing for it, and the vendor still
   * has the calls. The guard keeps the fetch to one attempt per day — the
   * marker the fetch writes stops it from repeating.
   */
  const autoFetchedDays = useRef(new Set<string>());
  useEffect(() => {
    if (!day) return;
    if (listQuery.isPending || listQuery.isError) return;
    if (items.length > 0) return;
    if (dayState?.status !== "unchecked") return;
    if (autoFetchedDays.current.has(day)) return;
    autoFetchedDays.current.add(day);
    requestBackfill({ day });
  }, [
    day,
    dayState,
    items.length,
    listQuery.isError,
    listQuery.isPending,
    requestBackfill,
  ]);

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

  /** Pull a day from Cloudfone on the admin's request (never automatic). */
  const fetchDayFromCloudfone = (target: string, force = false) => {
    autoFetchedDays.current.add(target);
    requestBackfill({ day: target, force });
  };

  /**
   * Load the most recent call day — the one the daily pass reports on. The
   * filter follows the fetch so the admin sees that day's result (and its
   * marker) instead of an unfiltered list that may stay empty.
   */
  const loadMostRecentDay = () => {
    const target = ictYesterday();
    setDay(target);
    setPage(1);
    setSelectedId(null);
    fetchDayFromCloudfone(target, true);
  };

  /**
   * Why a checked day holds no transcript.
   *
   * The marker counts what the fetch found: the calls of the day, the ones
   * that carried a recording, and the ones that became a transcript. A day
   * whose calls had recordings but produced no transcript is a different
   * story from a day without calls — and the admin deserves to know which one
   * they are looking at instead of a bare "nothing here".
   */
  const knownDayExplanation = (): string => {
    if (!dayState) return "";
    const calls = dayState.call_count;
    const recordable = dayState.recordable_count;
    const transcripts = dayState.transcript_count;
    if (calls === 0)
      return "Hệ thống đã kiểm tra ngày này: không có cuộc gọi nào.";
    if (recordable === 0) {
      return `Hệ thống đã kiểm tra ngày này: ${calls} cuộc gọi nhưng không có bản ghi để chuyển đổi.`;
    }
    if (transcripts === 0) {
      return `Hệ thống đã kiểm tra ngày này: ${recordable} cuộc gọi có bản ghi nhưng không chuyển sang văn bản được (bản ghi quá ngắn hoặc bị Cloudfone lỗi).`;
    }
    return `Hệ thống đã kiểm tra ngày này: ${transcripts}/${recordable} cuộc gọi có bản ghi văn bản.`;
  };

  // The three empty situations the marker can describe, told apart.
  const knownDay = Boolean(day) && dayState?.status === "checked";
  const dayHasTranscripts = (dayState?.transcript_count ?? 0) > 0;
  const dayHasRecordings = (dayState?.recordable_count ?? 0) > 0;
  // The day holds transcripts but the phone filter excludes them all.
  const numberFilteredOut = knownDay && dayHasTranscripts && Boolean(caller);
  const nothingTranscribable =
    knownDay && dayHasRecordings && !dayHasTranscripts;

  const changePage = (next: number) => {
    setPage(next);
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

  const pager = isPhone ? (
    <PhonePager
      page={page}
      pageCount={pageCount}
      pageStart={pageStart}
      pageEnd={pageEnd}
      total={total}
      onPageChange={changePage}
    />
  ) : (
    <DesktopPager
      page={page}
      pageCount={pageCount}
      pageStart={pageStart}
      pageEnd={pageEnd}
      total={total}
      onPageChange={changePage}
    />
  );

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

      {/* Filter bar: one row ≥640px, stacked full-width on a phone. */}
      <form
        className={cx(
          "uu-scope flex items-end gap-3",
          isPhone ? "flex-col items-stretch" : "flex-wrap",
        )}
        onSubmit={applyCaller}
      >
        <div
          className={cx("flex flex-col gap-1.5", isPhone ? "w-full" : "w-48")}
        >
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
        <div
          className={cx("flex flex-col gap-1.5", isPhone ? "w-full" : "w-64")}
        >
          <Label htmlFor="cloudfone-transcripts-caller" isRequired={false}>
            Số điện thoại
          </Label>
          <InputBase
            id="cloudfone-transcripts-caller"
            icon={Search}
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
          className={cx("tt-btn-touch", isPhone && "w-full")}
        >
          Lọc
        </Button>
        {filtered ? (
          <Button
            type="button"
            color="secondary"
            size="md"
            iconLeading={X}
            className={cx("tt-btn-touch", isPhone && "w-full")}
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
          icon={
            backfillMutation.isPending ? (
              <RefreshCw className="size-6 animate-spin" aria-hidden="true" />
            ) : dayState?.status === "error" ? (
              <TriangleAlert className="size-6" aria-hidden="true" />
            ) : (
              <FileText className="size-6" aria-hidden="true" />
            )
          }
          title={
            backfillMutation.isPending
              ? "Đang tải bản ghi từ Cloudfone"
              : dayState?.status === "error"
                ? "Chưa tải được dữ liệu từ Cloudfone"
                : numberFilteredOut
                  ? "Không tìm thấy bản ghi phù hợp"
                  : nothingTranscribable
                    ? "Không chuyển được bản ghi sang văn bản"
                    : knownDay
                      ? "Ngày này không có bản ghi"
                      : filtered
                        ? "Không tìm thấy bản ghi phù hợp"
                        : "Chưa có bản ghi cuộc gọi"
          }
          description={
            backfillMutation.isPending
              ? "Hệ thống đang lấy cuộc gọi của ngày này và chuyển giọng nói thành văn bản. Việc này có thể mất vài phút."
              : dayState?.status === "error"
                ? (dayState.error ??
                  "Cloudfone không phản hồi. Hãy thử lại sau ít phút.")
                : numberFilteredOut
                  ? "Ngày đã chọn có bản ghi, nhưng không có cuộc gọi nào khớp với số điện thoại này."
                  : knownDay
                    ? knownDayExplanation()
                    : filtered
                      ? "Thử thay đổi ngày hoặc số điện thoại."
                      : "Bản ghi xuất hiện tại đây sau khi hệ thống lấy cuộc gọi từ Cloudfone."
          }
          action={
            backfillMutation.isPending ? undefined : dayState?.status ===
              "error" ? (
              <Button
                color="secondary"
                size="md"
                iconLeading={RefreshCw}
                onClick={() => fetchDayFromCloudfone(day, true)}
              >
                Thử lại
              </Button>
            ) : numberFilteredOut ? (
              <Button color="secondary" size="md" onClick={clearFilters}>
                Xóa lọc
              </Button>
            ) : knownDay ? (
              <Button
                color="secondary"
                size="md"
                iconLeading={CloudDownload}
                onClick={() => fetchDayFromCloudfone(day, true)}
              >
                Kiểm tra lại từ Cloudfone
              </Button>
            ) : !day ? (
              <Button
                color="secondary"
                size="md"
                iconLeading={CloudDownload}
                onClick={loadMostRecentDay}
              >
                Tải bản ghi ngày gần nhất
              </Button>
            ) : filtered ? (
              <Button color="secondary" size="md" onClick={clearFilters}>
                Xóa lọc
              </Button>
            ) : undefined
          }
        />
      ) : (
        <section className="uu-scope overflow-hidden rounded-panel border border-secondary bg-primary">
          {isPhone ? (
            // <640px: one card per call — the card opens the transcript.
            <ul role="list">
              {items.map((row) => {
                const isSelected = row.call_id === selectedId;
                return (
                  <li
                    key={row.call_id}
                    role="listitem"
                    className="border-b border-secondary last:border-b-0"
                  >
                    <button
                      type="button"
                      // Compound control (row card), the documented opt-out
                      // from the 40px control-height ceiling (index.css §3).
                      data-allow-tall
                      aria-selected={isSelected}
                      onClick={() => setSelectedId(row.call_id)}
                      className={cx(
                        "flex min-h-11 w-full flex-col gap-1.5 px-3 py-3 text-left transition-colors outline-focus-ring focus-visible:outline-2 focus-visible:-outline-offset-2",
                        isSelected
                          ? "bg-secondary outline-2 -outline-offset-2"
                          : "hover:bg-secondary",
                      )}
                    >
                      <span className="flex w-full items-center justify-between gap-3">
                        <span className="tabular-nums text-body-sm font-semibold text-primary">
                          {row.caller}
                        </span>
                        <span className="shrink-0 rounded-full border border-secondary px-2.5 py-0.5 text-helper font-medium tabular-nums text-secondary">
                          {fmtDuration(row.talk_seconds)}
                        </span>
                      </span>
                      <span className="flex w-full items-center justify-between gap-3">
                        <span className="text-helper tabular-nums text-tertiary">
                          {fmtStarted(row.started_at)}
                        </span>
                        <span className="text-helper text-tertiary">
                          đã lưu
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            // ≥640px: the settings data table, unchanged.
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
          )}

          {pager}
        </section>
      )}

      {selectedId ? (
        <section className="uu-scope rounded-panel border border-secondary bg-primary">
          <header className="flex flex-wrap items-center gap-3 border-b border-secondary px-4 py-3">
            <FileText className="size-5 text-tertiary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="break-words text-body-sm font-semibold text-primary">
                {detailQuery.data
                  ? `${detailQuery.data.caller} · ${fmtDuration(detailQuery.data.talk_seconds)}`
                  : "Bản ghi cuộc gọi"}
              </p>
              {detailQuery.data ? (
                <p className="text-helper text-tertiary">
                  {fmtStarted(detailQuery.data.started_at)} · lưu{" "}
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
              <p className="text-left break-words whitespace-pre-wrap text-body-sm text-primary">
                {detailQuery.data.transcript}
              </p>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
};
