import { AlertTriangle, MessageCircle, PanelRight, Phone } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useDataProvider, useNotify } from "ra-core";
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { VList, WindowVirtualizer } from "virtua";

import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useIsMobile } from "@/hooks/use-mobile";

import { LeadAvatar } from "../conversations/LeadAvatar";
import { useRoleActions } from "../hooks/useRoleActions";
import type { CandidateProfileUpdate } from "../leads/domain/candidateProfile";
import type { CrmDataProvider } from "../providers/types";
import type { Lead } from "../types";
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
import { CandidateDataDialog } from "./CandidateDataDialog";
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
type SaveCandidateProfile = (
  lead: Lead,
  changes: Partial<CandidateProfileUpdate>,
  version: number,
) => Promise<void>;

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
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const { canEdit } = useRoleActions();
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
  // The result object changes on every fetch-state flip; the refetch binding
  // does not, so the save callback can stay referentially stable.
  const { refetch: refetchCandidates } = candidatesQuery;
  const saveCandidateProfile: SaveCandidateProfile = useCallback(
    async (lead, changes, version) => {
      try {
        await dataProvider.update<Lead>("leads", {
          id: lead.id,
          data: { ...changes, version },
          previousData: lead,
        });
        notify("Đã cập nhật hồ sơ ứng viên", { type: "success" });
        await refetchCandidates().catch(() => undefined);
      } catch (error) {
        // No refetch here: the write failed, so the cached list is still the
        // authoritative snapshot — refetching only doubles list traffic.
        notify(
          error instanceof Error
            ? error.message
            : "Không thể cập nhật hồ sơ ứng viên",
          { type: "error" },
        );
        throw error;
      }
    },
    [dataProvider, notify, refetchCandidates],
  );

  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  // Both derivations are O(n) over the whole queue, so they are memoized on
  // their query data: unrelated re-renders (cache indicators, dialog state,
  // 30s refetches that return identical data) must not regroup the lists.
  const interventionRows = useMemo(
    () => filterHumanInterventions(data?.immediate ?? []),
    [data?.immediate],
  );
  const { candidateGroups, candidateCount } = useMemo(() => {
    const groups = groupCandidatesByDay(candidatesQuery.data ?? []);
    return {
      candidateGroups: groups,
      candidateCount: groups.reduce(
        (total, group) => total + group.candidates.length,
        0,
      ),
    };
  }, [candidatesQuery.data]);

  // Skeleton on first load only; cached data + refetch never flashes a skeleton.
  // Retained data + error banner on partial failure; retry pane on initial fail.
  const {
    showSkeleton,
    showInitialError,
    showPartialError,
    showRefetchIndicator,
  } = deriveCacheDiscriminators({ isPending, isFetching, isError, data });
  const latestUpdate = dataUpdatedAt
    ? formatClock(
        new Date(
          Math.max(dataUpdatedAt, candidatesQuery.dataUpdatedAt),
        ).toISOString(),
      )
    : null;

  return (
    <div className={shellClass}>
      <header className="recruiting-hero recruiting-hero-minimal">
        <div className="recruiting-hero-copy">
          <h1>Tổng quan</h1>
          <div className="recruiting-hero-meta">
            <span
              className="dashboard-live-dot is-success"
              aria-hidden="true"
            />
            <span>
              {latestUpdate
                ? `Cập nhật lúc ${latestUpdate}`
                : "Đang tải hàng đợi tuyển dụng"}
            </span>
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
        </div>
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
              void refetchCandidates();
            }}
          >
            Thử lại
          </button>
        </div>
      ) : null}

      <section
        className="recruiting-worklist"
        aria-label="Các hàng đợi tuyển dụng"
      >
        <AttentionPanel
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
          onRetry={refetchCandidates}
          canEdit={canEdit}
          onSave={saveCandidateProfile}
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
  rows: AttentionItem[];
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
};

const AttentionPanel = ({
  rows,
  state,
  navigate,
  onRetry,
}: AttentionPanelProps) => {
  const isEmpty =
    !state.showSkeleton && !state.showInitialError && !state.hasRows;
  const countLabel = state.showSkeleton
    ? "Đang tải số hội thoại cần xử lý"
    : state.showInitialError
      ? "Không tải được số hội thoại cần xử lý"
      : `${rows.length} hội thoại cần xử lý`;

  return (
    <article className={`recruiting-panel${isEmpty ? " is-empty" : ""}`}>
      <div className="recruiting-panel-header">
        <div className="recruiting-panel-title">
          <MessageCircle aria-hidden="true" />
          <h2>Cần xử lý</h2>
        </div>
        <strong
          className="dashboard-panel-count"
          aria-label={countLabel}
          aria-live="polite"
        >
          {state.showSkeleton || state.showInitialError ? "—" : rows.length}
        </strong>
      </div>
      {!isEmpty ? (
        <div className="dashboard-candidate-list">
          {state.showSkeleton ? (
            <DashboardListSkeleton />
          ) : state.showInitialError ? (
            <DashboardQueueError
              label="Không tải được hội thoại."
              onRetry={onRetry}
            />
          ) : (
            rows.map((row) => (
              <AttentionRow key={row.key} row={row} navigate={navigate} />
            ))
          )}
        </div>
      ) : null}
    </article>
  );
};

const CandidatePanel = ({
  groups,
  count,
  state,
  navigate,
  onRetry,
  canEdit,
  onSave,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
  state: PanelState;
  navigate: Navigate;
  onRetry: () => void;
  canEdit: boolean;
  onSave: SaveCandidateProfile;
}) => {
  const isEmpty =
    !state.showSkeleton && !state.showInitialError && !state.hasRows;
  const countLabel = state.showSkeleton
    ? "Đang tải số ứng viên mới"
    : state.showInitialError
      ? "Không tải được số ứng viên mới"
      : `${count} ứng viên mới`;

  return (
    <article
      className={`recruiting-panel recruiting-candidate-panel${
        isEmpty ? " is-empty" : ""
      }`}
    >
      <div className="recruiting-panel-header">
        <div className="recruiting-panel-title">
          <Phone aria-hidden="true" />
          <h2>Ứng viên mới</h2>
        </div>
        <strong
          className="dashboard-panel-count"
          aria-label={countLabel}
          aria-live="polite"
        >
          {state.showSkeleton || state.showInitialError ? "—" : count}
        </strong>
      </div>
      {!isEmpty ? (
        <div className="dashboard-candidate-list">
          {state.showSkeleton ? (
            <DashboardListSkeleton />
          ) : state.showInitialError ? (
            <DashboardQueueError
              label="Không tải được ứng viên."
              onRetry={onRetry}
            />
          ) : (
            <CandidateGroupedList
              groups={groups}
              count={count}
              navigate={navigate}
              canEdit={canEdit}
              onSave={onSave}
            />
          )}
        </div>
      ) : null}
    </article>
  );
};

const CandidateGroupedList = ({
  groups,
  count,
  navigate,
  canEdit,
  onSave,
}: {
  groups: ReturnType<typeof groupCandidatesByDay>;
  count: number;
  navigate: Navigate;
  canEdit: boolean;
  onSave: SaveCandidateProfile;
}) => {
  const isMobile = useIsMobile();
  const desktopHeight = Math.min(640, count * 58 + groups.length * 30);

  // virtua virtualizes a flat child list and has no grouped API, so each day
  // header is emitted as its own item immediately before that day's rows. The
  // list only exists for the virtualized branch, hence the empty array below
  // the static-list threshold.
  const virtualItems = useMemo(
    () =>
      count <= 20
        ? []
        : groups.flatMap((group) => [
            <h3
              key={`day-${group.key}`}
              className="dashboard-candidate-day-header"
            >
              {group.label}
            </h3>,
            ...group.candidates.map((candidate) => (
              <CandidateRow
                key={`candidate-${candidate.id}`}
                candidate={candidate}
                navigate={navigate}
                canEdit={canEdit}
                onSave={onSave}
              />
            )),
          ]),
    [count, groups, navigate, canEdit, onSave],
  );

  // The dashboard usually contains only a handful of recent candidates. A
  // direct list keeps those rows visible and avoids a virtualizer viewport
  // hiding the only result inside a short panel; larger histories still use
  // virtualization to keep scrolling inexpensive.
  if (count <= 20) {
    return (
      <div className="dashboard-candidate-static-list">
        {groups.map((group) => (
          <div key={group.key}>
            <h3 className="dashboard-candidate-day-header">{group.label}</h3>
            {group.candidates.map((candidate) => (
              <CandidateRow
                key={`candidate-${candidate.id}`}
                candidate={candidate}
                navigate={navigate}
                canEdit={canEdit}
                onSave={onSave}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

  // Mobile scrolls the document (`.dashboard-workspace` is `overflow: visible`
  // under 768px), so the window is the scroll container there; the desktop
  // panel keeps its own bounded scroll viewport.
  if (isMobile) {
    return (
      <div className="dashboard-candidate-virtual-list">
        <WindowVirtualizer>{virtualItems}</WindowVirtualizer>
      </div>
    );
  }

  return (
    <VList
      className="dashboard-candidate-virtual-list"
      style={{ height: desktopHeight }}
    >
      {virtualItems}
    </VList>
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
  canEdit,
  onSave,
}: {
  candidate: DashboardCandidate;
  navigate: Navigate;
  canEdit: boolean;
  onSave: SaveCandidateProfile;
}) => {
  const [isCandidateDataOpen, setIsCandidateDataOpen] = useState(false);
  const actionTriggerRef = useRef<HTMLButtonElement>(null);
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
      {conversationId ? (
        <span className="dashboard-candidate-meta" aria-hidden="true">
          <small className="dashboard-row-action">Xem</small>
        </span>
      ) : null}
    </>
  );

  if (conversationId) {
    return (
      <>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              ref={actionTriggerRef}
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
              onSelect={() => setIsCandidateDataOpen(true)}
            >
              <PanelRight aria-hidden="true" />
              Dữ liệu ứng viên
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <CandidateDataDialog
          lead={candidate.lead}
          displayName={name}
          displayAvatarUrl={candidate.avatar_url}
          open={isCandidateDataOpen}
          onOpenChange={setIsCandidateDataOpen}
          returnFocusRef={actionTriggerRef}
          canEdit={canEdit}
          onSave={(changes, version) =>
            onSave(candidate.lead, changes, version)
          }
        />
      </>
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
