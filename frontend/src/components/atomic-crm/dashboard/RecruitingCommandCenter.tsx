import { AlertTriangle, Inbox, MessageCircle, Phone } from "lucide-react";
import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";

import {
  ATTENTION_QUERY_KEY,
  COUNTER_LABELS,
  REASON_LABELS,
  type AttentionCounters,
  type AttentionDashboard,
  type AttentionItem,
  type AttentionReason,
  fetchAttentionDashboard,
  formatElapsed,
} from "./attentionDashboard";
import {
  COUNTER_ORDER,
  continuationLabel,
  deriveCacheDiscriminators,
  filterByCounter,
  representativeReasonForCounter,
  showContinuation,
  type CounterKey,
} from "./recruitingCommandCenterLogic";
import { DashboardEmptyIllustration } from "./DashboardEmptyIllustration";

type RecruitingCommandCenterProps = {
  variant?: "desktop" | "mobile";
};

const normalizeText = (value: string | null | undefined): string =>
  value?.trim() ?? "";

const candidateName = (row: AttentionItem): string => {
  const name = normalizeText(row.name);
  if (name) return name;
  const suffix = row.phone_last4 ?? row.conversation_id?.slice(-4) ?? "";
  return suffix ? `Ứng viên ${suffix}` : "Ứng viên chưa định danh";
};

const initialsFor = (name: string): string => {
  const words = name
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean);
  if (words.length === 0) return "UV";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
};

const formatClock = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

/** Map a raw lead_stage code to a short Vietnamese chip label. */
const stageLabel = (stage: string): string => {
  const map: Record<string, string> = {
    NEW: "Mới",
    CONTACTING: "Đang liên hệ",
    REGISTERED: "Đã đăng ký",
    SKIPPED: "Bỏ qua",
  };
  return map[stage] ?? stage;
};

type Navigate = ReturnType<typeof useNavigate>;

/**
 * One primary action per row (no nested interactive controls — spec Risks).
 * `OPEN_CONVERSATION` navigates to the conversation; `CALL` only displays the
 * last-4 (we do not have a full phone to dial, so a `tel:` link would dial a
 * wrong number). Returns `null` for the static (CALL) variant.
 */
const rowOnClick = (
  row: AttentionItem,
  navigate: Navigate,
): (() => void) | null => {
  if (row.action === "OPEN_CONVERSATION" && row.conversation_id) {
    return () => navigate(`/conversations?id=${row.conversation_id}`);
  }
  return null;
};

export const RecruitingCommandCenter = ({
  variant = "desktop",
}: RecruitingCommandCenterProps) => {
  const navigate = useNavigate();
  // TanStack caching contract (Red-team Medium 14 — exact):
  //   - skeleton iff isPending && !data (first load only)
  //   - cached data + background-refetch indicator iff data && isFetching
  //     (NO skeleton flash on 30s refetch)
  //   - retry iff isError && !data (initial failure)
  //   - retained data + error banner iff isError && data (partial failure)
  // staleTime (25s) sits just under the 30s refetch so a routine refetch does
  // not flip the query back to a fetching-without-data state; gcTime keeps the
  // last good snapshot around for 5 minutes after unmount/counter-swap.
  // placeholderData: keepPreviousData smooths the counter-swap transition.
  const { data, isPending, isFetching, isError, refetch, dataUpdatedAt } =
    useQuery<AttentionDashboard>({
      queryKey: ATTENTION_QUERY_KEY,
      queryFn: fetchAttentionDashboard,
      refetchInterval: 30_000,
      staleTime: 25_000,
      gcTime: 5 * 60_000,
      placeholderData: keepPreviousData,
    });

  const [selectedCounter, setSelectedCounter] = useState<CounterKey | null>(
    null,
  );

  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  const immediateRows = useMemo(
    () => filterByCounter(data?.immediate ?? [], selectedCounter),
    [data?.immediate, selectedCounter],
  );
  const todayRows = useMemo(
    () => filterByCounter(data?.today ?? [], selectedCounter),
    [data?.today, selectedCounter],
  );

  // Skeleton on first load only; cached data + refetch never flashes a skeleton.
  // Retained data + error banner on partial failure; retry pane on initial fail.
  const {
    showSkeleton,
    showInitialError,
    showPartialError,
    showRefetchIndicator,
  } = deriveCacheDiscriminators({ isPending, isFetching, isError, data });

  return (
    <div className={shellClass}>
      <header className="recruiting-hero recruiting-hero-minimal">
        <div className="recruiting-hero-copy">
          <span className="recruiting-eyebrow">Theo dõi trực tiếp</span>
          <h1>Tổng quan tuyển dụng</h1>
          <p>
            {dataUpdatedAt
              ? `Cập nhật lúc ${formatClock(new Date(dataUpdatedAt).toISOString())}`
              : "Đang tải hàng đợi tuyển dụng"}
          </p>
          {showRefetchIndicator ? (
            <span
              className="attention-refetch-indicator"
              aria-live="polite"
              role="status"
            >
              Đang làm mới…
            </span>
          ) : null}
        </div>
      </header>

      {showPartialError ? (
        <div className="dashboard-inline-error" role="status">
          <span>
            Không thể làm mới hàng đợi. Danh sách hiện tại vẫn được giữ lại.
          </span>
          <button type="button" onClick={() => void refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}

      <CounterStrip
        counters={data?.counters}
        selected={selectedCounter}
        onSelect={setSelectedCounter}
        disabled={showSkeleton || showInitialError}
      />

      <section className="recruiting-two-column">
        <AttentionPanel
          title="Ứng viên cần xử lý ngay"
          eyebrow="Cần phản hồi"
          rows={immediateRows}
          totalCount={data?.immediate.length ?? 0}
          exactTotal={
            selectedCounter && data ? data.counters[selectedCounter] : null
          }
          state={{
            showSkeleton,
            showInitialError,
            hasRows: immediateRows.length > 0,
            selectedCounter,
          }}
          navigate={navigate}
          onRetry={refetch}
        />

        <AttentionPanel
          title="Cần xử lý hôm nay"
          eyebrow="Theo dõi hôm nay"
          rows={todayRows}
          totalCount={data?.today.length ?? 0}
          exactTotal={
            selectedCounter && data ? data.counters[selectedCounter] : null
          }
          state={{
            showSkeleton,
            showInitialError,
            hasRows: todayRows.length > 0,
            selectedCounter,
          }}
          navigate={navigate}
          onRetry={refetch}
          secondary
        />
      </section>
    </div>
  );
};

type PanelState = {
  showSkeleton: boolean;
  showInitialError: boolean;
  hasRows: boolean;
  selectedCounter: CounterKey | null;
};

type AttentionPanelProps = {
  title: string;
  eyebrow: string;
  rows: AttentionItem[];
  totalCount: number;
  /** Exact counter total when a counter is selected (authoritative backend value). */
  exactTotal: number | null;
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
  secondary?: boolean;
};

const AttentionPanel = ({
  title,
  eyebrow,
  rows,
  totalCount,
  exactTotal,
  state,
  navigate,
  onRetry,
  secondary,
}: AttentionPanelProps) => {
  // The continuation reason is the representative reason of the selected
  // counter, if any; for the unfiltered view we do not show the link (the
  // preview already is the whole queue).
  const continuationReason = state.selectedCounter
    ? representativeReasonForCounter(state.selectedCounter)
    : null;
  // `exactTotal` is the cross-queue counter total (e.g. `overdue` =
  // REPLY_OVERDUE + FOLLOWUP_OVERDUE across both queues); the link navigates to
  // `?reason=<representativeReason>` (ONE reason), so the inbox filtered set may
  // be smaller than exactTotal. The comparison is exactTotal > rows.length:
  // surface the link whenever the authoritative total beats what THIS panel
  // currently shows.
  const shouldShowContinuation = showContinuation({
    selectedCounter: state.selectedCounter,
    hasRows: state.hasRows,
    exactTotal,
    renderedRowCount: rows.length,
    totalCount,
  });

  return (
    <article className="recruiting-panel">
      <div className="recruiting-panel-header">
        <div>
          <span className="recruiting-eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <span
          className="dashboard-panel-count"
          aria-label={`${rows.length} mục đang hiển thị`}
        >
          {rows.length}
        </span>
      </div>
      <div className="dashboard-candidate-list">
        {state.showSkeleton ? (
          <DashboardListSkeleton />
        ) : state.showInitialError ? (
          <DashboardQueueError
            label={
              secondary
                ? "Không tải được danh sách xử lý hôm nay."
                : "Không tải được hàng đợi cần xử lý ngay."
            }
            onRetry={onRetry}
          />
        ) : state.hasRows ? (
          <>
            {rows.map((row) => (
              <AttentionRow key={row.key} row={row} navigate={navigate} />
            ))}
            {shouldShowContinuation && continuationReason ? (
              <ContinuationLink
                reason={continuationReason}
                navigate={navigate}
              />
            ) : null}
          </>
        ) : (
          <EmptyDashboardList
            content={
              state.selectedCounter
                ? {
                    title: "Không có mục nào trong nhóm đã chọn",
                    description:
                      "Hàng đợi này hiện không có công việc cần theo dõi.",
                    illustration: secondary ? "calendar" : "inbox",
                  }
                : secondary
                  ? {
                      title: "Không có việc cần xử lý hôm nay",
                      description:
                        "Bạn đã hoàn thành tất cả công việc cần theo dõi.",
                      illustration: "calendar",
                    }
                  : {
                      title: "Không có ứng viên cần xử lý ngay",
                      description: "Mọi cuộc trò chuyện hiện đã được xử lý.",
                      illustration: "inbox",
                    }
            }
          />
        )}
      </div>
    </article>
  );
};

type ContinuationLinkProps = {
  reason: AttentionReason;
  navigate: Navigate;
};

const ContinuationLink = ({ reason, navigate }: ContinuationLinkProps) => {
  // Phase 2 attention-dashboard continuation (Critical 2 Option A): navigate to
  // the inbox with `?reason=<enum>`. ConversationList reads `reason` at its
  // `<InfiniteListBase>` mount and passes it as the list's permanent `filter`,
  // so the data provider emits `?reason=<enum>` and the backend
  // `list_conversations` delegates to `list_by_attention_reason` (Phase 1).
  //
  // FIX 4: the label is the neutral "Mở hộp thư" — it deliberately does NOT
  // promise "N rows", because the counter total spans multiple reasons (and
  // both queues) while `?reason=` drills into a single representative reason.
  return (
    <button
      type="button"
      className="dashboard-continuation"
      onClick={() => navigate(`/conversations?reason=${reason}`)}
    >
      <span>{continuationLabel()}</span>
      <Inbox className="size-4" aria-hidden="true" />
    </button>
  );
};

const CounterStrip = ({
  counters,
  selected,
  onSelect,
  disabled,
}: {
  counters: AttentionCounters | undefined;
  selected: CounterKey | null;
  onSelect: (next: CounterKey | null) => void;
  disabled: boolean;
}) => {
  const safeCounters: AttentionCounters = counters ?? {
    needs_reply: 0,
    overdue: 0,
    due_today: 0,
    priority: 0,
    unread: 0,
  };

  return (
    <div
      className="attention-counter-strip"
      role="group"
      aria-label="Bộ lọc theo loại cần xử lý"
    >
      {COUNTER_ORDER.map((key) => {
        const isPressed = selected === key;
        const count = safeCounters[key];
        return (
          <button
            key={key}
            type="button"
            className="attention-counter-btn"
            aria-pressed={isPressed}
            aria-label={`${COUNTER_LABELS[key]}: ${count}`}
            disabled={disabled}
            onClick={() => onSelect(isPressed ? null : key)}
          >
            <span className="attention-counter-count" aria-hidden="true">
              {count}
            </span>
            <span className="attention-counter-label">
              {COUNTER_LABELS[key]}
            </span>
          </button>
        );
      })}
    </div>
  );
};

const CandidateAvatar = ({ name }: { name: string }) => (
  <span className="dashboard-candidate-avatar" aria-hidden>
    {initialsFor(name)}
  </span>
);

const AttentionRow = ({
  row,
  navigate,
}: {
  row: AttentionItem;
  navigate: Navigate;
}) => {
  const name = candidateName(row);
  const onClick = rowOnClick(row, navigate);
  const elapsed = formatElapsed(row.urgency_at);
  const reasonLabel = REASON_LABELS[row.reason] ?? row.reason;
  const stage = normalizeText(row.lead_stage);
  const desiredJob = normalizeText(row.desired_job);
  const phoneHint = normalizeText(row.phone_last4)
    ? `••• ${row.phone_last4}`
    : "";
  // The whole row is a single button (OPEN_CONVERSATION) so there are no
  // nested interactive controls; for CALL rows (no dialable phone) we render a
  // static row that still displays the last-4 identifier hint.
  const sub = (
    <span className="dashboard-candidate-sub">
      {stage ? (
        <span className="dashboard-stage-chip">{stageLabel(stage)}</span>
      ) : null}
      {desiredJob ? <span className="dashboard-job">{desiredJob}</span> : null}
      {phoneHint ? (
        <span
          className="dashboard-phone-hint"
          aria-label="Số điện thoại cuối 4 số"
        >
          <Phone className="size-3" aria-hidden="true" />
          {phoneHint}
        </span>
      ) : null}
    </span>
  );
  const meta = (
    <span className="dashboard-candidate-meta">
      <span className="dashboard-reason-label">{reasonLabel}</span>
      {elapsed ? <small>{elapsed}</small> : null}
    </span>
  );
  if (onClick) {
    return (
      <button
        type="button"
        className="dashboard-candidate-row"
        onClick={onClick}
        aria-label={`Mở hội thoại với ${name}. ${reasonLabel}${
          elapsed ? `, ${elapsed}` : ""
        }`}
      >
        <CandidateAvatar name={name} />
        <span className="dashboard-candidate-main">
          <strong>{name}</strong>
          {sub}
        </span>
        {meta}
      </button>
    );
  }
  // CALL row — last-4 only, no dial action (we don't have a full phone).
  return (
    <div
      className="dashboard-candidate-row is-static"
      aria-label={`${name}. ${reasonLabel}${
        elapsed ? `, ${elapsed}` : ""
      }${phoneHint ? `, số cuối ${row.phone_last4}` : ""}`}
    >
      <CandidateAvatar name={name} />
      <span className="dashboard-candidate-main">
        <strong>{name}</strong>
        {sub}
      </span>
      {meta}
    </div>
  );
};

const EmptyDashboardList = ({
  content,
}: {
  content: {
    title: string;
    description: string;
    illustration: "inbox" | "calendar";
  };
}) => (
  <div className="dashboard-empty-list">
    <DashboardEmptyIllustration kind={content.illustration} />
    <div className="dashboard-empty-copy">
      <p>{content.title}</p>
      <span>{content.description}</span>
    </div>
  </div>
);

const DashboardQueueError = ({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => void;
}) => (
  <div className="dashboard-empty-list dashboard-queue-error" role="status">
    <AlertTriangle className="size-4" aria-hidden="true" />
    <span>{label}</span>
    <button type="button" onClick={() => void onRetry()}>
      Thử lại
    </button>
  </div>
);

const DashboardListSkeleton = () => (
  <>
    {Array.from({ length: 3 }).map((_, index) => (
      <div key={index} className="dashboard-candidate-row is-skeleton">
        <Skeleton shimmer className="dashboard-candidate-avatar" />
        <span className="dashboard-candidate-main">
          <Skeleton shimmer className="h-4 w-32 rounded-md" />
          <Skeleton shimmer className="h-3 w-48 rounded-md" />
        </span>
        <MessageCircle className="size-4 text-muted-foreground/50" />
      </div>
    ))}
  </>
);
