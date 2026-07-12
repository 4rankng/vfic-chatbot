import {
  useState,
  useMemo,
  useEffect,
  useCallback,
  memo,
  useRef,
  useDeferredValue,
  type ReactNode,
} from "react";
import {
  InfiniteListBase,
  useInfinitePaginationContext,
  useListContext,
  RecordContextProvider,
} from "ra-core";
import { useSearchParams } from "react-router";
import type { Conversation, Lead } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { InboxIcons } from "./InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import { chatRepository } from "./chatRepository";
import { Skeleton } from "@/components/ui/skeleton";
import { vietnameseSearchIncludes } from "@/lib/vietnameseSearch";
import { getLeadPriorityChip, getLeadStatusColor } from "./conversationDisplay";
import {
  isAttentionReason,
  type QueueFilter,
} from "../dashboard/attentionDashboard";
import conversationEmptyIllustration from "@/assets/empty-states/conversation-empty-illustration.png";
import conversationLoadErrorIllustration from "@/assets/empty-states/conversation-load-error-illustration.png";
import {
  AlertTriangle,
  Inbox,
  RefreshCw,
  Reply,
  SearchX,
  UserRound,
} from "lucide-react";
import "./inbox.css";

type ConversationRow = Conversation & {
  _lead?: Lead | null;
  _snippet?: string;
};

// Re-export so existing importers (`import { QueueFilter } from
// ".../ConversationList"`) keep compiling after FIX 3 moved the type into
// attentionDashboard.ts. Prefer importing QueueFilter from
// attentionDashboard.ts directly in new code.
export type { QueueFilter };

const CONVERSATION_LIST_SORT = { field: "updated_at", order: "DESC" } as const;

const QUEUE_FILTER_ICON: Record<QueueFilter, string> = {
  all: "#i-filter",
  attention: "#i-clock",
  priority: "#i-sparkles",
};

const needsVisibleAttention = (
  conversation: Conversation,
  _readIds: Set<string>,
) => {
  if (conversation.mode !== "human" && conversation.mode !== "semi_auto") {
    return false;
  }
  if (!conversation.last_inbound_at) return false;
  if (!conversation.last_outbound_at) return true;
  return (
    new Date(conversation.last_inbound_at).getTime() >
    new Date(conversation.last_outbound_at).getTime()
  );
};

const getConversationModePriority = (mode: Conversation["mode"]) => {
  if (mode === "human") return 0;
  if (mode === "semi_auto") return 1;
  if (mode === "bot") return 2;
  return 3;
};

const getRelativeTimeString = (dateStr?: string) => {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
};

const getAttentionLabel = (
  conversation: Conversation,
  needsAttention: boolean,
): string => {
  if (conversation.mode === "closed") return "Đã đóng";
  if (conversation.needs_human) return "Cần xử lý";
  if (needsAttention) return "Chờ nhân viên";
  return "";
};

// Hoisted static style objects so list rows don't allocate brand-new objects on
// every render (defeats React.memo). These have no per-row variance.
const UNREAD_BADGE_DOT_STYLE: React.CSSProperties = {
  position: "absolute",
  top: 0,
  right: 0,
  width: 12,
  height: 12,
  borderRadius: 9999,
  background: "var(--ember)",
  boxShadow: "0 0 0 2px var(--card)",
} as const;

const UNREAD_BADGE_COUNT_STYLE: React.CSSProperties = {
  position: "absolute",
  top: -1,
  right: -1,
  minWidth: 18,
  height: 18,
  padding: "0 4px",
  borderRadius: 9999,
  background: "var(--ember)",
  color: "var(--primary-foreground)",
  fontSize: 10,
  fontWeight: 700,
  lineHeight: "18px",
  textAlign: "center",
  boxShadow: "0 0 0 2px var(--card)",
} as const;

const AVATAR_ICON_STYLE: React.CSSProperties = {
  width: "18px",
  height: "18px",
} as const;

// Hoisted skeleton styles — same rationale as UNREAD_BADGE_*: avoid
// allocating fresh style objects on every render of the skeleton row.
const SKELETON_AVATAR_STYLE: React.CSSProperties = {
  width: 36,
  height: 36,
  flexShrink: 0,
};

const SKELETON_BODY_STYLE: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const SKELETON_LINE_1_STYLE: React.CSSProperties = {
  height: 13,
  width: "55%",
  borderRadius: 6,
};

const SKELETON_LINE_2_STYLE: React.CSSProperties = {
  height: 12,
  width: "85%",
  borderRadius: 6,
};

type ConversationListItemProps = {
  conversation: ConversationRow;
  isActive: boolean;
  onSelect: (c: Conversation) => void;
  readIds: Set<string>;
};

// React.memo so a re-render of the list (typing in search, marking another row
// read, a sibling row's realtime update) does NOT re-render every visible row.
// Props are stable: `onSelect` is a useCallback in the parent, `readIds` is a
// Set identity that only changes when a read is committed, and `conversation`
// objects come from a memoized `rows` array.
const ConversationListItem = memo(
  ({
    conversation,
    isActive,
    onSelect,
    readIds,
  }: ConversationListItemProps) => {
    const lead = conversation._lead;
    const time = getRelativeTimeString(
      conversation.last_inbound_at ?? conversation.updated_at,
    );

    const name =
      lead?.name || `Ứng viên · ${(conversation.zalo_chat_id || "").slice(-4)}`;
    const colors = getLeadStatusColor(lead);
    // Preview = latest message snippet (batched via vfic_last_messages), falling
    // back to the contact's phone when no snippet is available yet.
    const subtitle = conversation._snippet || lead?.phone || "";

    const priorityChip = getLeadPriorityChip(lead);
    const needsAttention = needsVisibleAttention(conversation, readIds);
    const attentionLabel = getAttentionLabel(conversation, needsAttention);
    // Unread badge: optimistically cleared once opened (readIds); otherwise the
    // live counter kept in sync by the vfic_chat_histories_unread trigger.
    const unread = readIds.has(conversation.id)
      ? 0
      : (conversation.unread_count ?? 0);

    return (
      <button
        className={`conversation ${isActive ? "active" : ""} ${
          needsAttention ? "needs-attention" : ""
        }`}
        onClick={() => onSelect(conversation)}
        aria-label={`Mở hội thoại với ${name}`}
        aria-current={isActive ? "page" : undefined}
        aria-pressed={isActive}
      >
        <span
          className="avatar round"
          style={
            {
              "--avatar-bg": colors.bg,
              "--avatar-ink": colors.ink,
              position: "relative",
            } as React.CSSProperties
          }
        >
          <UserRound className="icon" style={AVATAR_ICON_STYLE} />
          {unread > 0 && (
            <span
              aria-label={`${unread} tin nhắn chưa đọc`}
              style={
                unread === 1 ? UNREAD_BADGE_DOT_STYLE : UNREAD_BADGE_COUNT_STYLE
              }
            >
              {unread > 1 ? (unread > 9 ? "9+" : unread) : ""}
            </span>
          )}
        </span>
        <span className="conv-body">
          <span className="conv-top">
            <span className="conv-name">{name}</span>
            <span className="conv-time">{time}</span>
          </span>
          <span className="conv-bottom">
            {subtitle && (
              <span className="conv-preview">
                <Reply className="conv-preview-icon" aria-hidden="true" />
                <span>{subtitle}</span>
              </span>
            )}
            <span className="conv-meta-row">
              {attentionLabel ? (
                <span
                  className={`conv-state-label ${
                    conversation.needs_human ? "is-human-escalation" : ""
                  }`}
                >
                  {conversation.needs_human ? (
                    <AlertTriangle
                      aria-hidden="true"
                      className="conv-state-icon"
                    />
                  ) : null}
                  {attentionLabel}
                </span>
              ) : null}
              {priorityChip ? (
                <span
                  className={`mini-chip priority-${priorityChip.tone}`}
                  title={priorityChip.label}
                >
                  {priorityChip.label}
                </span>
              ) : null}
            </span>
          </span>
        </span>
      </button>
    );
  },
);
ConversationListItem.displayName = "ConversationListItem";

// Shimmer skeleton matching the inbox row shape, shown while the first page
// loads (replaces the previous "flash of empty-state" on slow connections).
const ConversationListItemSkeleton = () => (
  <div className="conversation" aria-hidden style={{ cursor: "default" }}>
    <Skeleton shimmer className="!rounded-full" style={SKELETON_AVATAR_STYLE} />
    <div className="conv-body" style={SKELETON_BODY_STYLE}>
      <Skeleton shimmer style={SKELETON_LINE_1_STYLE} />
      <Skeleton shimmer style={SKELETON_LINE_2_STYLE} />
    </div>
  </div>
);

type ListEmptyStateProps = {
  kind: "empty" | "filtered" | "error";
  onAction?: () => void;
};

const ListEmptyState = ({ kind, onAction }: ListEmptyStateProps) => {
  const content = {
    empty: {
      icon: Inbox,
      title: "Chưa có cuộc trò chuyện",
      description: "Các cuộc trò chuyện mới từ ứng viên sẽ xuất hiện tại đây.",
    },
    filtered: {
      icon: SearchX,
      title: "Không tìm thấy hội thoại",
      description: "Thử xoá từ khoá tìm kiếm hoặc bộ lọc để xem thêm.",
      action: "Xoá tìm kiếm và bộ lọc",
    },
    error: {
      icon: AlertTriangle,
      image: conversationLoadErrorIllustration,
      title: "Không thể tải hội thoại",
      description: "Kiểm tra kết nối và thử lại.",
      action: "Thử lại",
    },
  }[kind];
  const Icon = content.icon;

  return (
    <div className={`empty-state list-empty-state is-${kind}`} role="status">
      {content.image ? (
        <img className="list-empty-state-image" src={content.image} alt="" />
      ) : (
        <span className="list-empty-state-icon" aria-hidden="true">
          <Icon />
        </span>
      )}
      <div className="list-empty-state-copy">
        <p>{content.title}</p>
        <span>{content.description}</span>
      </div>
      {content.action && onAction ? (
        <button type="button" className="list-retry" onClick={onAction}>
          {kind === "error" ? <RefreshCw aria-hidden="true" /> : null}
          {content.action}
        </button>
      ) : null}
    </div>
  );
};

const WorkspaceEmptyState = () => {
  return (
    <>
      <header
        className="chat-header chat-header-placeholder"
        aria-hidden="true"
      >
        <span className="chat-header-placeholder-avatar" />
        <span className="chat-header-placeholder-copy">
          <i />
          <i />
        </span>
        <span className="chat-header-placeholder-action" />
      </header>
      <div className="workspace-empty-state" role="status">
        <img
          className="workspace-empty-illustration"
          src={conversationEmptyIllustration}
          alt=""
        />
        <div className="workspace-empty-copy">
          <h2>Chọn một cuộc trò chuyện</h2>
          <p>
            Chọn một cuộc trò chuyện từ danh sách để xem tin nhắn và thông tin
            ứng viên.
          </p>
        </div>
      </div>
    </>
  );
};

const ConversationListPanel = ({
  selectedId,
  onSelect,
  readIds,
}: {
  selectedId: string | null;
  onSelect: (c: Conversation) => void;
  readIds: Set<string>;
}) => {
  const {
    data: conversations,
    isPending,
    error,
    refetch,
  } = useListContext<Conversation>();
  const { fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfinitePaginationContext();
  const [leads, setLeads] = useState<Record<string, Lead | null>>({});
  const [snippets, setSnippets] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  // The chip always starts on "all". A `?reason=` deep link filters
  // server-side (via `InfiniteListBase filter`), NOT via this chip — see the
  // note in `ConversationList`. The user may still pick a chip on top.
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const clearSearchAndFilters = useCallback(() => {
    setQuery("");
    setQueueFilter("all");
  }, []);
  // Defer the query used for filtering so fast typing never blocks the input;
  // the immediate `query` still drives the search box value.
  const deferredQuery = useDeferredValue(query);
  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const conversationIdsKey = useMemo(
    () => conversations?.map((c) => c.id).join("|") ?? "",
    [conversations],
  );

  // Resolve contact details AND the latest message per conversation in one
  // batched pass each (getLeadsByZaloIds + getLastMessages), replacing the old
  // per-zalo_id N+1 lookups. Both fire concurrently.
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    let cancelled = false;
    (async () => {
      const zaloIds = Array.from(
        new Set(conversations.map((c) => c.zalo_chat_id).filter(Boolean)),
      );
      try {
        const [all, snips] = await Promise.all([
          chatRepository.getLeadsByZaloIds(zaloIds),
          chatRepository.getLastMessages(conversations),
        ]);
        if (cancelled) return;
        const byZalo: Record<string, Lead | null> = {};
        for (const lead of all) {
          const key = lead.zalo_id;
          if (key && byZalo[key] === undefined) byZalo[key] = lead;
        }
        setLeads((prev) => {
          if (
            Object.entries(byZalo).every(([key, value]) => prev[key] === value)
          ) {
            return prev;
          }
          return { ...prev, ...byZalo };
        });
        setSnippets((prev) => {
          if (
            Object.entries(snips).every(([key, value]) => prev[key] === value)
          ) {
            return prev;
          }
          return { ...prev, ...snips };
        });
      } catch {
        // Leave previously loaded leads/snippets intact on error.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationIdsKey, conversations]);

  const rows: ConversationRow[] = useMemo(() => {
    if (!conversations) return [];
    return conversations
      .map((c) => {
        const lead = leads[c.zalo_chat_id] ?? null;
        return {
          ...c,
          _lead: lead,
          _snippet: snippets[c.zalo_chat_id] ?? "",
        };
      })
      .filter((c) => {
        if (queueFilter === "attention" && !needsVisibleAttention(c, readIds)) {
          return false;
        }
        if (
          queueFilter === "priority" &&
          c._lead?.lead_score !== "hot" &&
          c._lead?.lead_score !== "warm"
        ) {
          return false;
        }
        if (deferredQuery) {
          const haystack = [
            c.zalo_chat_id,
            c._lead?.name,
            c._lead?.phone,
            c._lead?.desired_job,
            c._lead?.region,
            c._lead?.living_area,
            c._snippet,
          ]
            .filter(Boolean)
            .join(" ");
          if (!vietnameseSearchIncludes(haystack, deferredQuery)) return false;
        }
        return true;
      })
      .sort((a, b) => {
        const aMode = getConversationModePriority(a.mode);
        const bMode = getConversationModePriority(b.mode);
        if (aMode !== bMode) return aMode - bMode;

        const aAttention = needsVisibleAttention(a, readIds) ? 1 : 0;
        const bAttention = needsVisibleAttention(b, readIds) ? 1 : 0;
        if (aAttention !== bAttention) return bAttention - aAttention;

        const aUnread = readIds.has(a.id) ? 0 : (a.unread_count ?? 0);
        const bUnread = readIds.has(b.id) ? 0 : (b.unread_count ?? 0);
        if (aUnread !== bUnread) return bUnread - aUnread;

        return (
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        );
      });
  }, [conversations, leads, snippets, deferredQuery, queueFilter, readIds]);

  useEffect(() => {
    const root = scrollRootRef.current;
    const marker = loadMoreRef.current;
    if (!root || !marker || !hasNextPage || isFetchingNextPage) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          fetchNextPage();
        }
      },
      { root, rootMargin: "160px 0px", threshold: 0.01 },
    );

    observer.observe(marker);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, rows.length]);

  return (
    <aside className="panel left-panel" aria-label="Danh sách cuộc trò chuyện">
      <WorkspaceRail
        searchSlot={
          <div className="inbox-toolbar">
            <label className="search">
              <span className="sr-only">Tìm ứng viên hoặc số điện thoại</span>
              <svg className="icon">
                <use href="#i-search" />
              </svg>
              <input
                type="search"
                placeholder="Tìm kiếm"
                aria-label="Tìm ứng viên hoặc số điện thoại"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="conversation-filters" aria-label="Lọc hội thoại">
              {(
                [
                  ["all", "Tất cả hội thoại"],
                  ["attention", "Cần phản hồi"],
                  ["priority", "Ứng viên ưu tiên"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`conversation-filter is-${value}`}
                  aria-label={label}
                  aria-pressed={queueFilter === value}
                  title={label}
                  onClick={() => setQueueFilter(value)}
                >
                  <svg className="icon" aria-hidden="true">
                    <use href={QUEUE_FILTER_ICON[value]} />
                  </svg>
                </button>
              ))}
            </div>
          </div>
        }
      />

      <div
        className="conversations animate-in fade-in-0 duration-300"
        ref={scrollRootRef}
      >
        {isPending ? (
          Array.from({ length: 6 }).map((_, i) => (
            <ConversationListItemSkeleton key={i} />
          ))
        ) : error ? (
          <ListEmptyState kind="error" onAction={() => void refetch()} />
        ) : rows.length === 0 ? (
          <ListEmptyState
            kind={query || queueFilter !== "all" ? "filtered" : "empty"}
            onAction={
              query || queueFilter !== "all" ? clearSearchAndFilters : undefined
            }
          />
        ) : (
          rows.map((c) => (
            <ConversationListItem
              key={c.id}
              conversation={c}
              isActive={selectedId === c.id}
              onSelect={onSelect}
              readIds={readIds}
            />
          ))
        )}

        {hasNextPage && (
          <div
            className="infinite-scroll-sentinel"
            ref={loadMoreRef}
            aria-hidden="true"
          >
            {isFetchingNextPage ? <ConversationListItemSkeleton /> : <span />}
          </div>
        )}
      </div>
    </aside>
  );
};

const WorkspaceRail = ({ searchSlot }: { searchSlot: ReactNode }) => (
  <div className="workspace-rail" aria-label="Tin nhắn">
    <div className="workspace-title-row">
      <div className="workspace-title-copy">
        <h1 className="workspace-heading">Tin nhắn</h1>
      </div>
    </div>
    <div className="inbox-tools">{searchSlot}</div>
  </div>
);

const ConversationListContent = () => {
  const { data: conversations } = useListContext<Conversation>();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const conversationIdsKey = useMemo(
    () => conversations?.map((c) => c.id).join("|") ?? "",
    [conversations],
  );
  // Optimistic unread-clears. Reset whenever the list refreshes so the server
  // state stays authoritative (markAsRead has reset unread_count) — otherwise a
  // fresh inbound that bumps the count back above 0 would stay hidden for the
  // whole session after a chat is opened once.
  const [pendingReadIds, setPendingReadIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    setPendingReadIds((current) => (current.size === 0 ? current : new Set()));
  }, [conversationIdsKey]);

  const urlId = searchParams.get("id");
  // BLOCKER #1: the `?reason=` URL param is now consumed at the
  // `<ConversationList>` mount (passed to `InfiniteListBase filter`) so the
  // backend `list_by_attention_reason` filter runs and the server returns the
  // filtered set. The client-side queue chip is intentionally NOT seeded from
  // the reason here — the chip would fight the backend filter (chip semantics
  // are `attention`/`priority`, which don't map 1:1 to the nine reason enums,
  // e.g. `FOLLOWUP_TODAY` has no matching chip). The chip stays on "all" while a
  // `?reason=` is active; the user may still pick a chip on top.
  // On mobile the detail pane is shown iff a conversation id is in the URL, so
  // the browser back button naturally returns to the list. Desktop always shows
  // the detail alongside the list.
  const detailOpen = !isMobile || !!urlId;

  // Seed the selection: a deep link (?id=) opens that conversation; otherwise
  // desktop auto-selects the first for an immediate detail view, while mobile
  // stays list-first until the user taps a row.
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    const hasUrlConversation =
      !!urlId && conversations.some((c) => c.id === urlId);
    const hasSelectedConversation =
      !!selectedId && conversations.some((c) => c.id === selectedId);

    // A stale deep link (?id= for a deleted/invalid conversation) would leave
    // detailOpen true with no selectable conversation, stranding the user on
    // an empty detail pane. Clear it so the list shows instead.
    if (isMobile && urlId && !hasUrlConversation) {
      setSearchParams(
        (prev) => {
          prev.delete("id");
          return prev;
        },
        { replace: true },
      );
      return;
    }

    if (hasUrlConversation) {
      setSelectedId(urlId);
      return;
    }

    if (hasSelectedConversation) return;

    if (!isMobile) {
      const firstId = (conversations[0] as Conversation).id;
      setSelectedId(firstId);
      if (urlId) {
        setSearchParams(
          (prev) => {
            prev.set("id", firstId);
            return prev;
          },
          { replace: true },
        );
      }
    } else if (selectedId) {
      setSelectedId(null);
    }
  }, [conversations, urlId, selectedId, isMobile, setSearchParams]);

  const selected = conversations?.find((c) => c.id === selectedId) ?? null;

  // Stable identity so memoized ConversationListItem children don't re-render
  // on every list state change (the parent re-renders on search/selection, but
  // `onSelect` itself never needs to change — it only calls stable setters).
  const openConversation = useCallback(
    (c: Conversation) => {
      setSelectedId(c.id);
      // Optimistically clear the unread badge for this row; ConversationShow
      // confirms server-side via markAsRead on open.
      setPendingReadIds((prev) => {
        if (prev.has(c.id)) return prev;
        const next = new Set(prev);
        next.add(c.id);
        return next;
      });
      // Push (not replace) so each opened conversation is a history entry and the
      // browser back button returns to the list.
      setSearchParams((prev) => {
        prev.set("id", c.id);
        return prev;
      });
    },
    [setSearchParams],
  );

  const backToList = () => {
    setSearchParams(
      (prev) => {
        prev.delete("id");
        return prev;
      },
      { replace: true },
    );
  };

  return (
    <div
      className={`inbox-bg-container ${
        isMobile && detailOpen ? "conversation-open" : ""
      }`}
    >
      <InboxIcons />
      <div
        className={`app ${detailOpen ? "detail-open" : ""} ${
          selected ? "has-selected-conversation" : ""
        }`}
        id="app"
      >
        <ConversationListPanel
          selectedId={selected?.id ?? null}
          onSelect={openConversation}
          readIds={pendingReadIds}
        />

        {selected ? (
          <RecordContextProvider value={selected}>
            <ConversationShowContent
              onOpenList={backToList}
              showWorkspacePanel
            />
          </RecordContextProvider>
        ) : (
          <section className="panel center-panel">
            <WorkspaceEmptyState />
          </section>
        )}

        <div className="backdrop" onClick={backToList}></div>
      </div>
    </div>
  );
};

export const ConversationList = () => {
  // BLOCKER #1 fix: read `?reason=` HERE (at the InfiniteListBase mount) and
  // forward it as the list's permanent `filter` so react-admin emits
  // `?reason=<enum>` in the data-provider call, which the backend
  // `list_conversations` then delegates to `list_by_attention_reason`. Reading
  // it at the content level (useListContext child) would be too late — the
  // request has already fired.
  const [searchParams] = useSearchParams();
  const reasonParam = searchParams.get("reason");
  const reasonFilter = isAttentionReason(reasonParam)
    ? { reason: reasonParam }
    : undefined;
  // When the reason changes (or clears), remount cleanly so no stale rows from
  // the previous reason linger and react-admin's permanent-filter bookkeeping
  // resets. Acceptable per the spec note.
  const listKey = reasonFilter ? `reason:${reasonFilter.reason}` : "all";
  return (
    // Infinite pagination keeps the inbox light while removing visible page
    // controls. Row previews come from /conversations/last-messages/batch for
    // the loaded rows only.
    <InfiniteListBase
      key={listKey}
      perPage={25}
      sort={CONVERSATION_LIST_SORT}
      filter={reasonFilter}
    >
      <ConversationListContent />
    </InfiniteListBase>
  );
};
