import {
  AlertTriangle,
  CheckCircle2,
  MessageCircle,
  PanelRight,
  Phone,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { GroupedVirtuoso } from "react-virtuoso";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useIsMobile } from "@/hooks/use-mobile";

import { LeadAvatar } from "../conversations/LeadAvatar";
import {
  ATTENTION_QUERY_KEY,
  REASON_LABELS,
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
import {
  deriveCacheDiscriminators,
  filterHumanInterventions,
} from "./recruitingCommandCenterLogic";

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

  const interventionRows = filterHumanInterventions(data?.immediate ?? []);
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
  const queueHealth =
    showInitialError || (candidatesQuery.isError && !candidatesQuery.data)
      ? {
          tone: "warning",
          title: "Đang chờ kết nối dữ liệu",
          detail: "Thử lại để tải hàng đợi",
        }
      : showPartialError ||
          (candidatesQuery.isError && Boolean(candidatesQuery.data))
        ? {
            tone: "warning",
            title: "Đang hiển thị dữ liệu gần nhất",
            detail: "Kết nối làm mới đang gián đoạn",
          }
        : showSkeleton || (candidatesQuery.isPending && !candidatesQuery.data)
          ? {
              tone: "neutral",
              title: "Đang kết nối hàng đợi",
              detail: "Đang tải dữ liệu tuyển dụng",
            }
          : {
              tone: "success",
              title: "",
              detail: "",
            };

  return (
    <div className={shellClass}>
      <header className="recruiting-hero recruiting-hero-minimal">
        <div className="recruiting-hero-copy">
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
        <button
          type="button"
          className="dashboard-open-inbox"
          onClick={() => navigate("/conversations")}
        >
          <MessageCircle className="size-4" aria-hidden="true" />
          Mở hộp thư
        </button>
        {queueHealth.title || queueHealth.detail ? (
          <div
            className={`dashboard-live-status is-${queueHealth.tone}`}
            role="status"
          >
            <span className="dashboard-live-dot" aria-hidden="true" />
            <div>
              {queueHealth.title ? <strong>{queueHealth.title}</strong> : null}
              {queueHealth.detail ? <span>{queueHealth.detail}</span> : null}
            </div>
          </div>
        ) : null}
      </header>

      {showPartialError || (candidatesQuery.isError && candidatesQuery.data) ? (
        <div
          className="dashboard-inline-error tt-alert tt-alert-error tt-alert-soft"
          role="status"
        >
          <span>
            Không thể làm mới hàng đợi. Danh sách hiện tại vẫn được giữ lại.
          </span>
          <button
            type="button"
            className="tt-btn tt-btn-sm tt-btn-error tt-btn-outline"
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
          navigate={navigate}
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
        <h2>{eyebrow}</h2>
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
  navigate,
  onRetry,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
}) => (
  <article className="recruiting-panel recruiting-candidate-panel">
    <div className="recruiting-panel-header">
      <h2>Ứng viên mới</h2>
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
        <CandidateGroupedList
          groups={groups}
          count={count}
          navigate={navigate}
        />
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
  navigate,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
  navigate: Navigate;
}) => {
  const isMobile = useIsMobile();
  const candidates = groups.flatMap((group) => group.candidates);
  const desktopHeight = Math.min(720, count * 68 + groups.length * 32);

  // The dashboard usually contains only a handful of recent candidates. A
  // direct list keeps those rows visible and avoids a virtualizer viewport
  // hiding the only result inside a short panel; larger histories still use
  // virtualization to keep scrolling inexpensive.
  if (count <= 20) {
    return (
      <div className="dashboard-candidate-static-list">
        {groups.map((group) => (
          <div key={group.key}>
            <h2 className="dashboard-candidate-day-header">{group.label}</h2>
            {group.candidates.map((candidate) => (
              <CandidateRow
                key={`candidate-${candidate.id}`}
                candidate={candidate}
                navigate={navigate}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

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
        <CandidateRow candidate={candidate} navigate={navigate} />
      )}
    />
  );
};

const CandidateAvatar = ({
  name,
  src,
}: {
  name: string;
  src?: string | null;
}) => (
  <LeadAvatar
    className="dashboard-candidate-avatar tt-avatar tt-avatar-placeholder"
    src={src}
    alt={`Ảnh đại diện của ${name}`}
    iconSize={20}
  />
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
      <span className="dashboard-job">{REASON_LABELS[row.reason]}</span>
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
      {onClick ? <small className="dashboard-row-action">Mở</small> : null}
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
        <CandidateAvatar name={name} />
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
      <CandidateAvatar name={name} />
      <span className="dashboard-candidate-main">
        {candidateTitle}
        {sub}
      </span>
      {meta}
    </div>
  );
};

const CandidateRow = ({
  candidate,
  navigate,
}: {
  candidate: DashboardCandidate;
  navigate: Navigate;
}) => {
  const name = normalizeText(candidate.name) || "Ứng viên mới";
  const phone = normalizeText(candidate.phone);
  const conversationId = candidate.conversation_id;
  const content = (
    <>
      <CandidateAvatar name={name} src={candidate.avatar_url} />
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
        </span>
      </span>
    </>
  );

  if (conversationId) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="dashboard-candidate-row"
            aria-label={`Chọn thao tác cho ${name}, số điện thoại ${phone}`}
          >
            {content}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          sideOffset={8}
          className="dashboard-candidate-action-menu"
        >
          <DropdownMenuItem
            className="dashboard-candidate-action-item"
            onSelect={() => navigate(`/conversations?id=${conversationId}`)}
          >
            <MessageCircle aria-hidden="true" />
            Xem hội thoại
          </DropdownMenuItem>
          <DropdownMenuItem
            className="dashboard-candidate-action-item"
            onSelect={() =>
              navigate(`/conversations?id=${conversationId}&panel=candidate`)
            }
          >
            <PanelRight aria-hidden="true" />
            Dữ liệu ứng viên
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  return (
    <div
      className="dashboard-candidate-row is-static"
      aria-label={`${name}, số điện thoại ${phone}`}
    >
      {content}
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
    <button
      className="tt-btn tt-btn-sm tt-btn-outline"
      type="button"
      onClick={() => void onRetry()}
    >
      Thử lại
    </button>
  </div>
);

const DashboardListSkeleton = () => (
  <>
    {Array.from({ length: 3 }).map((_, index) => (
      <div key={index} className="dashboard-candidate-row is-skeleton">
        <Skeleton shimmer className="dashboard-candidate-avatar tt-skeleton" />
        <span className="dashboard-candidate-main">
          <Skeleton shimmer className="h-4 w-32 rounded-md" />
          <Skeleton shimmer className="h-3 w-48 rounded-md" />
        </span>
        <MessageCircle className="size-4 text-muted-foreground/50" />
      </div>
    ))}
  </>
);
