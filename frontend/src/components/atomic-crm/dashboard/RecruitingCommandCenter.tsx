import { AlertTriangle, MessageCircle, Phone, UserRound } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";

import {
  ATTENTION_QUERY_KEY,
  REASON_LABELS,
  type AttentionDashboard,
  type AttentionItem,
  type AttentionQueue,
  fetchAttentionDashboard,
  formatElapsed,
  reasonLabelForQueue,
} from "./attentionDashboard";
import { deriveCacheDiscriminators } from "./recruitingCommandCenterLogic";
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
  // last good snapshot around for 5 minutes after unmount.
  const { data, isPending, isFetching, isError, refetch, dataUpdatedAt } =
    useQuery<AttentionDashboard>({
      queryKey: ATTENTION_QUERY_KEY,
      queryFn: fetchAttentionDashboard,
      refetchInterval: 30_000,
      staleTime: 25_000,
      gcTime: 5 * 60_000,
    });

  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  const immediateRows = data?.immediate ?? [];
  const todayRows = data?.today ?? [];

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

      <section className="recruiting-two-column">
        <AttentionPanel
          title="Ứng viên cần xử lý ngay"
          eyebrow="Cần phản hồi"
          rows={immediateRows}
          state={{
            showSkeleton,
            showInitialError,
            hasRows: immediateRows.length > 0,
          }}
          navigate={navigate}
          onRetry={refetch}
        />

        <AttentionPanel
          title="Cần xử lý hôm nay"
          eyebrow="Theo dõi hôm nay"
          rows={todayRows}
          state={{
            showSkeleton,
            showInitialError,
            hasRows: todayRows.length > 0,
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
};

type AttentionPanelProps = {
  title: string;
  eyebrow: string;
  rows: AttentionItem[];
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
  secondary?: boolean;
};

const AttentionPanel = ({
  title,
  eyebrow,
  rows,
  state,
  navigate,
  onRetry,
  secondary,
}: AttentionPanelProps) => {
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
          rows.map((row) => (
            <AttentionRow
              key={row.key}
              row={row}
              navigate={navigate}
              queue={secondary ? "today" : "immediate"}
            />
          ))
        ) : (
          <EmptyDashboardList
            content={
              secondary
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

const CandidateAvatar = () => (
  <span className="dashboard-candidate-avatar" aria-hidden>
    <UserRound className="size-5" />
  </span>
);

const AttentionRow = ({
  row,
  navigate,
  queue,
}: {
  row: AttentionItem;
  navigate: Navigate;
  queue: AttentionQueue;
}) => {
  const name = candidateName(row);
  const onClick = rowOnClick(row, navigate);
  const elapsed = formatElapsed(row.urgency_at);
  const reasonLabel = REASON_LABELS[row.reason] ?? row.reason;
  const visibleReasonLabel = reasonLabelForQueue(row.reason, queue);
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
  const candidateTitle = (
    <span className="dashboard-candidate-title">
      <strong>{name}</strong>
      {stage ? (
        <span className="dashboard-stage-chip">{stageLabel(stage)}</span>
      ) : null}
    </span>
  );
  const meta = (
    <span className="dashboard-candidate-meta">
      {visibleReasonLabel ? (
        <span className="dashboard-reason-label">{visibleReasonLabel}</span>
      ) : null}
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
        <CandidateAvatar />
        <span className="dashboard-candidate-main">
          {candidateTitle}
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
      <CandidateAvatar />
      <span className="dashboard-candidate-main">
        {candidateTitle}
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
