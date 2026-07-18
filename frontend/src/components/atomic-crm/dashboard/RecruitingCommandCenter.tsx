import {
  AlertTriangle,
  CheckCircle2,
  MessageCircle,
  Phone,
  UserRound,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { GroupedVirtuoso } from "react-virtuoso";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { useIsMobile } from "@/hooks/use-mobile";

import {
  ATTENTION_QUERY_KEY,
  type AttentionDashboard,
  type AttentionItem,
  fetchAttentionDashboard,
  formatElapsed,
} from "./attentionDashboard";
import {
  CANDIDATES_QUERY_KEY,
  type DashboardCandidate,
  fetchDashboardCandidates,
  groupCandidatesByDay,
} from "./candidateDashboard";
import { deriveCacheDiscriminators } from "./recruitingCommandCenterLogic";

type RecruitingCommandCenterProps = {
  variant?: "desktop" | "mobile";
};

const normalizeText = (value: string | null | undefined): string =>
  value?.trim() ?? "";

const candidateName = (row: AttentionItem): string => {
  const name = normalizeText(row.name);
  if (name) return name;
  const phone = normalizeText(row.phone);
  return phone ? `Ứng viên ${phone}` : "Ứng viên mới";
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

type Navigate = ReturnType<typeof useNavigate>;

/**
 * One primary action per row (no nested interactive controls — spec Risks).
 * `OPEN_CONVERSATION` navigates to the conversation; `CALL` only displays the
 * Returns `null` for the static (CALL) variant.
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
  const candidatesQuery = useQuery<DashboardCandidate[]>({
    queryKey: CANDIDATES_QUERY_KEY,
    queryFn: fetchDashboardCandidates,
    refetchInterval: 30_000,
    staleTime: 25_000,
    gcTime: 5 * 60_000,
  });

  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  const interventionRows = (data?.immediate ?? []).filter(
    (row) => row.action === "OPEN_CONVERSATION" && row.conversation_id,
  );
  const candidateGroups = groupCandidatesByDay(candidatesQuery.data ?? []);
  const candidateCount = candidateGroups.reduce(
    (total, group) => total + group.candidates.length,
    0,
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
              ? `Cập nhật lúc ${formatClock(new Date(Math.max(dataUpdatedAt, candidatesQuery.dataUpdatedAt)).toISOString())}`
              : "Đang tải hàng đợi tuyển dụng"}
          </p>
          {showRefetchIndicator ||
          (candidatesQuery.isFetching && candidatesQuery.data) ? (
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

      {showPartialError || (candidatesQuery.isError && candidatesQuery.data) ? (
        <div className="dashboard-inline-error" role="status">
          <span>
            Không thể làm mới hàng đợi. Danh sách hiện tại vẫn được giữ lại.
          </span>
          <button
            type="button"
            onClick={() => {
              void refetch();
              void candidatesQuery.refetch();
            }}
          >
            Thử lại
          </button>
        </div>
      ) : null}

      <section className="recruiting-two-column">
        <AttentionPanel
          eyebrow="Cần can thiệp"
          rows={interventionRows}
          state={{
            showSkeleton,
            showInitialError,
            hasRows: interventionRows.length > 0,
          }}
          navigate={navigate}
          onRetry={refetch}
        />

        <CandidatePanel
          groups={candidateGroups}
          count={candidateCount}
          state={{
            showSkeleton: candidatesQuery.isPending && !candidatesQuery.data,
            showInitialError: candidatesQuery.isError && !candidatesQuery.data,
            hasRows: candidateCount > 0,
          }}
          onRetry={candidatesQuery.refetch}
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
  eyebrow: string;
  rows: AttentionItem[];
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
};

const AttentionPanel = ({
  eyebrow,
  rows,
  state,
  navigate,
  onRetry,
}: AttentionPanelProps) => {
  return (
    <article className="recruiting-panel">
      <div className="recruiting-panel-header">
        <div>
          <span className="recruiting-eyebrow">{eyebrow}</span>
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
            label="Không tải được các hội thoại cần can thiệp."
            onRetry={onRetry}
          />
        ) : state.hasRows ? (
          rows.map((row) => (
            <AttentionRow key={row.key} row={row} navigate={navigate} />
          ))
        ) : (
          <EmptyDashboardList
            content={{
              title: "Không có hội thoại cần can thiệp",
              description: "Mọi cuộc trò chuyện hiện đã được xử lý.",
            }}
          />
        )}
      </div>
    </article>
  );
};

const CandidatePanel = ({
  groups,
  count,
  state,
  onRetry,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
  state: PanelState;
  onRetry: () => void;
}) => (
  <article className="recruiting-panel recruiting-candidate-panel">
    <div className="recruiting-panel-header">
      <span className="recruiting-eyebrow">Ứng viên mới nhất</span>
      <span
        className="dashboard-panel-count"
        aria-label={`${count} ứng viên có số điện thoại`}
      >
        {count}
      </span>
    </div>
    <div className="dashboard-candidate-list">
      {state.showSkeleton ? (
        <DashboardListSkeleton />
      ) : state.showInitialError ? (
        <DashboardQueueError
          label="Không tải được danh sách ứng viên."
          onRetry={onRetry}
        />
      ) : state.hasRows ? (
        <CandidateGroupedList groups={groups} count={count} />
      ) : (
        <EmptyDashboardList
          content={{
            title: "Chưa có ứng viên có số điện thoại",
            description:
              "Ứng viên sẽ xuất hiện tại đây sau khi cung cấp số liên hệ.",
          }}
        />
      )}
    </div>
  </article>
);

const CandidateGroupedList = ({
  groups,
  count,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
}) => {
  const isMobile = useIsMobile();
  const candidates = groups.flatMap((group) => group.candidates);
  const desktopHeight = Math.min(720, count * 68 + groups.length * 32);

  return (
    <GroupedVirtuoso
      className="dashboard-candidate-virtual-list"
      data={candidates}
      groupCounts={groups.map((group) => group.candidates.length)}
      useWindowScroll={isMobile}
      style={isMobile ? undefined : { height: desktopHeight }}
      computeItemKey={(index, candidate) =>
        candidate ? `candidate-${candidate.id}` : `group-${index}`
      }
      groupContent={(index) => (
        <h2 className="dashboard-candidate-day-header">
          {groups[index]?.label}
        </h2>
      )}
      itemContent={(_index, _groupIndex, candidate) => (
        <CandidateRow candidate={candidate} />
      )}
    />
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
}: {
  row: AttentionItem;
  navigate: Navigate;
}) => {
  const name = candidateName(row);
  const onClick = rowOnClick(row, navigate);
  const elapsed = formatElapsed(row.urgency_at);
  const desiredJob = normalizeText(row.desired_job);
  const phone = normalizeText(row.phone);
  // The whole row is a single button (OPEN_CONVERSATION) so there are no
  // nested interactive controls; CALL rows remain static even when a contact
  // number is available.
  const sub = (
    <span className="dashboard-candidate-sub">
      {desiredJob ? <span className="dashboard-job">{desiredJob}</span> : null}
      {phone ? (
        <span
          className="dashboard-phone-hint"
          aria-label={`Số điện thoại ${phone}`}
        >
          <Phone className="size-3" aria-hidden="true" />
          {phone}
        </span>
      ) : null}
    </span>
  );
  const candidateTitle = (
    <span className="dashboard-candidate-title">
      <strong>{name}</strong>
    </span>
  );
  const meta = (
    <span className="dashboard-candidate-meta">
      {elapsed ? <small>{elapsed}</small> : null}
    </span>
  );
  if (onClick) {
    return (
      <button
        type="button"
        className="dashboard-candidate-row"
        onClick={onClick}
        aria-label={`Mở hội thoại với ${name}${elapsed ? `, ${elapsed}` : ""}`}
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
  // CALL row — displayed as a static row; it does not add a nested dial action.
  return (
    <div
      className="dashboard-candidate-row is-static"
      aria-label={`${name}${elapsed ? `, ${elapsed}` : ""}${
        phone ? `, số điện thoại ${phone}` : ""
      }`}
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

const CandidateRow = ({ candidate }: { candidate: DashboardCandidate }) => {
  const name = normalizeText(candidate.name) || "Ứng viên mới";
  const phone = normalizeText(candidate.phone);
  const desiredJob = normalizeText(candidate.desired_job);
  const createdAt = new Date(candidate.created_at);
  const time = Number.isNaN(createdAt.getTime())
    ? ""
    : new Intl.DateTimeFormat("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Ho_Chi_Minh",
      }).format(createdAt);

  return (
    <div
      className="dashboard-candidate-row is-static"
      aria-label={`${name}, số điện thoại ${phone}${time ? `, lúc ${time}` : ""}`}
    >
      <CandidateAvatar />
      <span className="dashboard-candidate-main">
        <span className="dashboard-candidate-title">
          <strong>{name}</strong>
        </span>
        <span className="dashboard-candidate-sub">
          <span
            className="dashboard-phone-hint"
            aria-label={`Số điện thoại ${phone}`}
          >
            <Phone className="size-3" aria-hidden="true" />
            {phone}
          </span>
          {desiredJob ? (
            <span className="dashboard-job">{desiredJob}</span>
          ) : null}
        </span>
      </span>
      {time ? (
        <span className="dashboard-candidate-meta">
          <small>{time}</small>
        </span>
      ) : null}
    </div>
  );
};

const EmptyDashboardList = ({
  content,
}: {
  content: {
    title: string;
    description: string;
  };
}) => (
  <div className="dashboard-empty-list">
    <span className="dashboard-empty-icon" aria-hidden="true">
      <CheckCircle2 />
    </span>
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
