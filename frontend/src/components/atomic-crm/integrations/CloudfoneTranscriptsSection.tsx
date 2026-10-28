import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import {
  MessageCircleMore,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CloudDownload,
  Copy,
  FileText,
  Phone,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-react";

import {
  AppModal,
  AppModalOverlay,
} from "@/components/atomic-crm/kit/app-modal";
import { Dialog } from "@/components/application/modals/modal";
import { Button } from "@/components/base/buttons/button";
import { InputBase } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { Pagination } from "@/components/application/pagination/pagination-base";
import { Table } from "@/components/application/table/table";
import { useIsMobile } from "@/hooks/use-mobile";
import { cx } from "@/utils/cx";
import { EmptyState } from "../kit/page-shell";

import { zaloIntegrationGateway, type CloudfoneTranscriptSummary } from "./api";
import { copyCredentialFieldValue } from "./credentialClipboard";
import { TranscriptConversation } from "./TranscriptConversation";
import { TranscriptFullscreen } from "./TranscriptFullscreen";
import { parseTranscriptUtterances } from "./transcript-utterances";

import "./cloudfone-transcripts.css";

/**
 * The stored voice-call transcripts viewer, reached from the Cloudfone
 * settings section: a filter surface (call day, phone fragment) over
 * `cloudfone_call_transcripts`, one page of results at a time, and the full
 * transcript of the selected call.
 *
 * A day the daily pass never covered (it only reports on the previous day)
 * would show an empty table, so the viewer fetches such a day from Cloudfone
 * on demand: the list response carries the inspected-day marker, and a day
 * without one is pulled once (the transcripts are then stored like any other).
 * A day the system already checked is left alone — it is known, and it may
 * legitimately hold nothing.
 *
 * Two responsive surfaces, one dataset, split at the console's mobile
 * breakpoint (768px — `useIsMobile`, the same seam the settings drill-down
 * uses) rather than by CSS: the vitest browser project compiles no Tailwind,
 * so a class-only swap would leave both surfaces queryable in unit tests, and
 * a JS swap also keeps exactly one surface in the a11y tree.
 *  - ≥768px keeps Untitled UI's settings data table (filter bar → table card →
 *    count strip + pagination) and the transcript panel below it, built from
 *    the vendored UUI primitives — `frontend/AGENTS.md` § "UI/UX Component
 *    Sourcing".
 *  - <768px swaps in the phone surface (cloudfone redesign consult 22/10): a
 *    sticky search (h-10, 300ms debounce) with scrolling h-7 day-scope chips,
 *    one ~76px bordered card per call (call icon + number + time-of-day over
 *    a one-line preview + duration pill, no five-column table fits a 390px
 *    phone), a compact Trước/Sau pager — and the transcript opens in a
 *    full-screen overlay (owner decision 23/10 09:24, replacing the consult's
 *    50% → 92vh bottom sheet): 100% of the visual viewport, one ~56px header
 *    row (‹ Quay lại | number · duration · date | copy-all, 44px touch
 *    targets), bubbles filling the rest, sliding in from the right like the
 *    settings drill-down. The generic `BottomSheet` component stays for other
 *    surfaces; this viewer no longer mounts it.
 *
 * The transcript itself renders as the same two-speaker conversation in both
 * surfaces (`TranscriptConversation`) — S1 left gray-100 / S2 right brand-50,
 * copy-all in the surface header. The overlay's three body states (skeleton
 * bubbles, empty, error + retry) follow the consult's §3.
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

/** "2026-10-01T17:02:35" → "5:02 CH" (Vietnamese 12-hour clock) — the call
 * card's time-of-day, per the redesign consult's "10:45 SA" example. */
const fmtTimeOfDay = (iso: string): string => {
  const timePart = iso.split("T")[1] ?? "";
  const [hRaw = "", m = ""] = timePart.split(":");
  const h = Number(hRaw);
  if (!hRaw || !m || !Number.isFinite(h)) return iso;
  const suffix = h < 12 ? "SA" : "CH";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${suffix}`;
};

/**
 * The previous ICT calendar day (the day the daily pass reports on) as
 * "YYYY-MM-DD". Vietnam has no DST, so the +7 offset is exact.
 */
const ictYesterday = (): string => {
  const shifted = new Date(Date.now() + 7 * 3_600_000 - 86_400_000);
  return shifted.toISOString().slice(0, 10);
};

/** The current ICT calendar day as "YYYY-MM-DD" (same exact +7 offset). */
const ictToday = (): string => {
  const shifted = new Date(Date.now() + 7 * 3_600_000);
  return shifted.toISOString().slice(0, 10);
};

/** The chip-row day scopes the mobile filter surface offers. */
type DayScope = "all" | "today" | "yesterday" | "custom";

const dayScopeOf = (day: string): DayScope => {
  if (day === "") return "all";
  if (day === ictToday()) return "today";
  if (day === ictYesterday()) return "yesterday";
  return "custom";
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
  /**
   * Back into the Cloudfone settings sub-page. Omitted on the workspace
   * call-records page (CHAT-15): non-admins have no config surface to
   * return to, so they must not see the settings exit.
   */
  onBack?: () => void;
}) => {
  const isMobile = useIsMobile();
  const notify = useNotify();
  const [day, setDay] = useState("");
  const [callerDraft, setCallerDraft] = useState("");
  const [caller, setCaller] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Mobile chip row: "Chọn ngày" reveals the date field; a chosen date then
  // owns the custom scope. Desktop keeps its always-visible filter form.
  const [dateRowOpen, setDateRowOpen] = useState(false);
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

  /**
   * Mobile search-as-you-type: the phone-fragment filter follows the search
   * field after a 300ms pause (consult §2), instead of the desktop form's
   * explicit Lọc submit. Desktop typing stays inert until Lọc.
   */
  useEffect(() => {
    if (!isMobile) return;
    const handle = window.setTimeout(() => {
      const next = callerDraft.trim();
      if (next !== caller) {
        setCaller(next);
        setPage(1);
        setSelectedId(null);
      }
    }, 300);
    return () => window.clearTimeout(handle);
  }, [isMobile, callerDraft, caller]);

  /** A chip picked on the mobile surface (custom only reveals the date field). */
  const applyDayScope = (scope: DayScope) => {
    if (scope === "all") {
      setDay("");
      setDateRowOpen(false);
    } else if (scope === "today") {
      setDay(ictToday());
      setDateRowOpen(false);
    } else if (scope === "yesterday") {
      setDay(ictYesterday());
      setDateRowOpen(false);
    } else {
      setDateRowOpen(true);
    }
    setPage(1);
    setSelectedId(null);
  };

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

  const pager = isMobile ? (
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

  // One snapshot of the loaded record: closures below (copy-all) must not
  // re-narrow a mutable query result.
  const detail = detailQuery.data;

  // The sheet/panel body's three states + the conversation (consult §3):
  // three alternating skeleton bubbles while loading, an explanatory empty
  // state for a stored call without utterances, an error card with a retry,
  // and the S1/S2 bubbles once the transcript parses.
  const detailBody = detailQuery.isPending ? (
    <div className="transcript-skeleton" aria-busy="true">
      <span
        aria-hidden="true"
        className="transcript-skeleton-bubble is-left bg-neutral-200 animate-pulse"
        style={{ height: 48, width: "58%" }}
      />
      <span
        aria-hidden="true"
        className="transcript-skeleton-bubble is-right bg-neutral-200 animate-pulse"
        style={{ height: 64, width: "72%" }}
      />
      <span
        aria-hidden="true"
        className="transcript-skeleton-bubble is-left bg-neutral-200 animate-pulse"
        style={{ height: 40, width: "44%" }}
      />
    </div>
  ) : detailQuery.isError ? (
    <div className="detail-state" role="alert">
      <CircleAlert className="size-10 text-rose-500" aria-hidden="true" />
      <p className="detail-state-title text-neutral-800">
        Không thể tải hội thoại
      </p>
      <p className="detail-state-sub text-neutral-500">
        Đã xảy ra lỗi khi bóc băng hoặc tải dữ liệu
      </p>
      <button
        type="button"
        className="detail-state-retry bg-neutral-900 text-white active:scale-95 outline-focus-ring focus-visible:outline-2 focus-visible:outline-offset-2"
        onClick={() => void detailQuery.refetch()}
      >
        Thử lại
      </button>
    </div>
  ) : parseTranscriptUtterances(detailQuery.data.transcript).length === 0 ? (
    <div className="detail-state">
      <MessageCircleMore
        className="size-10 text-neutral-300"
        aria-hidden="true"
      />
      <p className="detail-state-title text-neutral-700">
        Chưa có nội dung cuộc gọi
      </p>
      <p className="detail-state-sub text-neutral-400">
        Nội dung bóc băng sẽ hiển thị tại đây
      </p>
    </div>
  ) : (
    <TranscriptConversation transcript={detailQuery.data.transcript} />
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Mobile back navigation lives in the settings app bar; the section
          keeps its own explicit exit on desktop, and only in the console
          flow (onBack) — the workspace page has no settings to exit to. */}
      {!isMobile && onBack ? (
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
      ) : null}

      {isMobile ? (
        /* Sticky phone filter surface (consult §2): search-as-you-type +
           day-scope chips, the custom date field only when asked for.
           `uu-scope` re-binds the UUI input semantics (the desktop form's
           wrapper does the same). */
        <div className="transcripts-toolbar uu-scope">
          <InputBase
            type="search"
            icon={Search}
            aria-label="Tìm số điện thoại"
            placeholder="Tìm số điện thoại…"
            value={callerDraft}
            onChange={(event) => setCallerDraft(event.target.value)}
            wrapperClassName="transcripts-search"
          />
          <div
            className="transcripts-chips"
            role="radiogroup"
            aria-label="Lọc thời gian cuộc gọi"
          >
            {(
              [
                ["all", "Tất cả"],
                ["today", "Hôm nay"],
                ["yesterday", "Hôm qua"],
                ["custom", "Chọn ngày"],
              ] as Array<[DayScope, string]>
            ).map(([scope, label]) => (
              <label
                key={scope}
                className={cx(
                  "transcripts-chip",
                  dayScopeOf(day) === scope
                    ? "border-brand-600 bg-brand-50 font-semibold text-brand-700"
                    : "border-neutral-300 bg-white font-medium text-neutral-700",
                )}
              >
                <input
                  type="radio"
                  name="cloudfone-day-scope"
                  className="transcripts-chip-input"
                  checked={dayScopeOf(day) === scope}
                  onChange={() => applyDayScope(scope)}
                />
                {label}
              </label>
            ))}
          </div>
          {dateRowOpen ? (
            <div className="transcripts-date-row">
              <Label
                htmlFor="cloudfone-transcripts-day-mobile"
                isRequired={false}
              >
                Ngày cuộc gọi
              </Label>
              <InputBase
                id="cloudfone-transcripts-day-mobile"
                type="date"
                value={day}
                onChange={(event) => {
                  setDay(event.target.value);
                  setPage(1);
                  setSelectedId(null);
                }}
                wrapperClassName="flex-1"
              />
            </div>
          ) : null}
        </div>
      ) : (
        /* Desktop filter bar: one row, unchanged. */
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
      )}

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
      ) : isMobile ? (
        <>
          {/* <768px: one ~76px bordered card per call (consult §4) — call
              icon + number + time-of-day over a one-line preview + duration
              pill. The card opens the full-screen transcript overlay. */}
          <ul role="list" className="call-card-list">
            {items.map((row) => {
              const isSelected = row.call_id === selectedId;
              return (
                <li key={row.call_id} role="listitem">
                  <button
                    type="button"
                    // Compound control (row card), the documented opt-out
                    // from the 40px control-height ceiling (index.css §3).
                    data-allow-tall
                    aria-selected={isSelected}
                    onClick={() => setSelectedId(row.call_id)}
                    className={cx(
                      "call-card border shadow-xs transition-colors outline-focus-ring focus-visible:outline-2 focus-visible:-outline-offset-2",
                      isSelected
                        ? "border-brand-300 bg-brand-50"
                        : "border-neutral-200 bg-white hover:bg-neutral-50 active:bg-neutral-50",
                    )}
                  >
                    <span className="call-card-top">
                      {/* The stored row carries no direction, so the neutral
                          phone glyph stands in for the consult's
                          call-in/call-out pair until the API exposes one. */}
                      <span className="call-card-headline">
                        <Phone
                          className="call-card-icon text-neutral-500"
                          aria-hidden="true"
                        />
                        <span className="call-card-name text-neutral-900">
                          {row.caller}
                        </span>
                      </span>
                      <span className="call-card-time text-neutral-500">
                        {fmtTimeOfDay(row.started_at)}
                      </span>
                    </span>
                    <span className="call-card-middle">
                      <span className="call-card-preview text-neutral-500">
                        {row.transcript_preview}
                      </span>
                      <span className="call-card-badge bg-neutral-100 text-neutral-600">
                        {fmtDuration(row.talk_seconds)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="uu-scope overflow-hidden rounded-panel border border-secondary bg-primary">
            {pager}
          </div>
        </>
      ) : (
        <section className="uu-scope overflow-hidden rounded-panel border border-secondary bg-primary">
          {/* ≥768px: the settings data table, unchanged. */}
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

          {pager}
        </section>
      )}

      {selectedId ? (
        isMobile ? (
          /* <768px: the full-screen overlay replaces the panel below the
              list (owner 23/10 09:24 — reading a transcript should read like
              a chat screen, not a sheet). One fixed ~56px header row — ‹
              Quay lại | number · duration · date | copy-all (44px touch
              targets) — and the bubbles scroll in everything below it;
              slides in from the right like the settings drill-down, 200ms. */
          <TranscriptFullscreen
            isOpen
            onOpenChange={(open) => {
              if (!open) setSelectedId(null);
            }}
            title={
              detail
                ? `Bản ghi cuộc gọi của ${detail.caller}`
                : "Bản ghi cuộc gọi"
            }
            header={
              <header className="transcript-fullscreen-header">
                <button
                  type="button"
                  className="transcripts-back-action"
                  onClick={() => setSelectedId(null)}
                >
                  <ChevronLeft aria-hidden="true" />
                  <span>Quay lại</span>
                </button>
                <div className="transcripts-fullscreen-heading">
                  <p className="transcripts-fullscreen-title text-neutral-900">
                    {detail ? detail.caller : "Bản ghi cuộc gọi"}
                  </p>
                  {detail ? (
                    <p className="transcripts-fullscreen-meta text-neutral-500">
                      {fmtDuration(detail.talk_seconds)} ·{" "}
                      {fmtStarted(detail.started_at)}
                    </p>
                  ) : null}
                </div>
                {detail ? (
                  <button
                    type="button"
                    className="transcripts-icon-action"
                    aria-label="Sao chép toàn bộ bản ghi"
                    onClick={() =>
                      void copyCredentialFieldValue(
                        "toàn bộ bản ghi",
                        detail.transcript,
                        notify,
                      )
                    }
                  >
                    <Copy aria-hidden="true" />
                  </button>
                ) : null}
              </header>
            }
          >
            {detailBody}
          </TranscriptFullscreen>
        ) : (
          /* ≥768px: the PRO modal pattern (application/modals family) — the
             detail opens as a centered overlay instead of a panel below the
             table, so clicking "Xem" never sends the operator hunting down
             the page. Same header anatomy as the phone sheet. */
          <AppModalOverlay
            isOpen
            onOpenChange={(open) => {
              if (!open) setSelectedId(null);
            }}
            isDismissable
            className="uu-scope"
          >
            <AppModal className="w-full outline-hidden sm:max-w-lg">
              <Dialog aria-label="Bản ghi cuộc gọi" className="outline-hidden">
                <div className="transcripts-sheet-header border-b border-secondary px-4 py-3">
                  <div className="transcripts-sheet-heading">
                    <p className="transcripts-sheet-title text-neutral-900">
                      {detail ? detail.caller : "Bản ghi cuộc gọi"}
                    </p>
                    {detail ? (
                      <p className="transcripts-sheet-meta text-neutral-500">
                        {fmtDuration(detail.talk_seconds)} •{" "}
                        {fmtStarted(detail.started_at)}
                      </p>
                    ) : null}
                  </div>
                  {detail ? (
                    <button
                      type="button"
                      className="transcripts-icon-action"
                      aria-label="Sao chép toàn bộ bản ghi"
                      onClick={() =>
                        void copyCredentialFieldValue(
                          "toàn bộ bản ghi",
                          detail.transcript,
                          notify,
                        )
                      }
                    >
                      <Copy aria-hidden="true" />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="transcripts-icon-action"
                    aria-label="Đóng bản ghi"
                    onClick={() => setSelectedId(null)}
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
                <div className="max-h-[70vh] overflow-y-auto px-4 py-3">
                  {detailBody}
                </div>
              </Dialog>
            </AppModal>
          </AppModalOverlay>
        )
      ) : null}
    </div>
  );
};
