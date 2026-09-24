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
  useGetOne,
  useListContext,
  RecordContextProvider,
} from "ra-core";
import { useSearchParams } from "react-router";
import type { Conversation } from "../../types";
import { ConversationShowContent } from "./ConversationShow";
import { InboxIcons } from "../InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import { loadConversationSnippets } from "../application/conversation-runtime";
import { Skeleton } from "@/components/ui/skeleton";
import { vietnameseSearchIncludes } from "@/lib/vietnameseSearch";
import { LeadAvatar } from "../LeadAvatar";
import { useConversationCapabilitySlots } from "../conversation-capability";
import {
  getConversationListKey,
  getConversationListServerFilter,
  getEffectiveConversationChannelProvider,
  isAttentionReason,
} from "../domain/conversation-list-filters";
import { ChannelAdapterSelector } from "../ChannelAdapterSelector";
import {
  botHasNotReplied,
  compareConversationRows,
  getConversationAttentionLabel,
  getConversationUnreadCount,
  needsHumanReply,
} from "../domain/conversation-row-state";
import {
  conversationSelectionParams,
  findSelectedConversation,
} from "../domain/conversation-navigation";
import {
  pruneConversationRowViewModelCache,
  resolveConversationRowViewModel,
  type ConversationRowViewModelCacheEntry,
} from "./conversation-row-view-model";
import type { ConversationRowPresentation } from "../../capabilities/types";
import conversationWorkspaceIllustration from "@/assets/empty-states/conversation-workspace-illustration.webp";
import conversationLoadErrorIllustration from "@/assets/empty-states/conversation-load-error-illustration.png";
import { AlertTriangle, Inbox, RefreshCw, Reply, SearchX } from "lucide-react";
import "../inbox.css";

const CONVERSATION_LIST_SORT = { field: "last_message_at", order: "DESC" } as const;

const getRelativeTimeString = (dateStr?: string) => {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
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
  fontSize: "var(--fs-badge)",
  fontWeight: 700,
  lineHeight: "18px",
  textAlign: "center",
  boxShadow: "0 0 0 2px var(--card)",
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

// Hoisted empty read-set for `getConversationUnreadCount`: a row receives its
// own `isRead` boolean, so the domain helper only needs a set that can never
// match this row — allocating one per render would defeat the memo again.
const EMPTY_READ_IDS: ReadonlySet<string> = new Set();

type ConversationListItemProps = {
  conversation: Conversation;
  presentation: ConversationRowPresentation;
  snippet: string;
  isRead: boolean;
  isActive: boolean;
  onSelect: (c: Conversation) => void;
};

// React.memo so a re-render of the list (typing in search, marking another row
// read, a sibling row's realtime update) does NOT re-render every visible row.
// Every prop keeps its identity while its own input is unchanged: `conversation`
// comes straight from the list data, `presentation`/`snippet` come from the
// per-id view-model cache, `isRead` is this row's boolean instead of the shared
// read-id Set, `isActive` is a boolean and `onSelect` is stable across URL
// changes (see the latest-setter ref in `ConversationListContent`).
const ConversationListItem = memo(
  ({
    conversation,
    presentation,
    snippet,
    isRead,
    isActive,
    onSelect,
  }: ConversationListItemProps) => {
    const time = getRelativeTimeString(
      conversation.last_inbound_at ?? conversation.updated_at,
    );

    const name = presentation.displayName;
    // Preview = latest message snippet (batched via vfic_last_messages), falling
    // back to the contact's phone when no snippet is available yet.
    const subtitle = snippet || presentation.subtitle;

    const priorityChip = presentation.priorityLabel
      ? {
          label: presentation.priorityLabel,
          tone: presentation.priorityTone ?? "warm",
        }
      : null;
    const needsHumanAttention = needsHumanReply(conversation);
    const needsBotAttention = botHasNotReplied(conversation);
    const needsAttention = needsHumanAttention || needsBotAttention;
    const attentionLabel = getConversationAttentionLabel(conversation);
    // Unread badge: optimistically cleared once opened (isRead); otherwise the
    // live counter kept in sync by the vfic_chat_histories_unread trigger.
    const unread = isRead
      ? 0
      : getConversationUnreadCount(conversation, EMPTY_READ_IDS);

    return (
      <button
        className={`conversation ${isActive ? "active" : ""} ${
          needsAttention ? "needs-attention" : ""
        }`}
        onClick={() => onSelect(conversation)}
        aria-label={`Mở hội thoại với ${name}${attentionLabel ? `, ${attentionLabel}` : ""}`}
        aria-current={isActive ? "page" : undefined}
        aria-pressed={isActive}
      >
        <LeadAvatar
          src={presentation.avatarUrl}
          bg={presentation.avatarBackground}
          ink={presentation.avatarForeground}
          iconSize={18}
          className="avatar round"
          alt={`Ảnh đại diện của ${name}`}
        >
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
        </LeadAvatar>
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
    <Skeleton
      shimmer
      className="!rounded-full tt-skeleton"
      style={SKELETON_AVATAR_STYLE}
    />
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
      description: "Các cuộc trò chuyện mới từ liên hệ sẽ xuất hiện tại đây.",
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
        <button
          type="button"
          className="list-retry tt-btn tt-btn-sm tt-btn-outline"
          onClick={onAction}
        >
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
      <div className="workspace-empty-state tt-card tt-card-sm" role="status">
        <div className="workspace-empty-visual" aria-hidden="true">
          <span className="workspace-empty-eyebrow tt-badge tt-badge-soft">
            Không gian tư vấn
          </span>
          <img
            className="workspace-empty-illustration"
            src={conversationWorkspaceIllustration}
            alt=""
          />
        </div>
        <div className="workspace-empty-copy tt-card-body">
          <h2 className="tt-card-title">Bắt đầu từ một cuộc trò chuyện</h2>
          <p>
            Chọn một ứng viên để xem trọn vẹn lịch sử trao đổi, tiếp quản khi
            cần và cập nhật hồ sơ ngay trong một không gian.
          </p>
          <div className="workspace-empty-features" aria-hidden="true">
            <span>
              <svg className="icon">
                <use href="#i-bot" />
              </svg>
              Tin nhắn
            </span>
            <span>
              <svg className="icon">
                <use href="#i-user" />
              </svg>
              Hồ sơ
            </span>
            <span>
              <svg className="icon">
                <use href="#i-sparkles" />
              </svg>
              Chatbot
            </span>
          </div>
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
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    data: conversations,
    isPending,
    error,
    refetch,
  } = useListContext<Conversation>();
  const { fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfinitePaginationContext();
  const slots = useConversationCapabilitySlots();
  const [adapterPresentations, setAdapterPresentations] = useState<
    ReadonlyMap<string, ConversationRowPresentation>
  >(new Map());
  const [snippets, setSnippets] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const hasNeedsAttentionFilter =
    searchParams.get("needs_attention") === "true";
  const hasServerFilter =
    isAttentionReason(searchParams.get("reason")) || hasNeedsAttentionFilter;
  const clearSearchAndFilters = useCallback(() => {
    setQuery("");
    setSearchParams(
      (prev) => {
        prev.delete("reason");
        prev.delete("needs_attention");
        return prev;
      },
      { replace: true },
    );
  }, [setSearchParams]);
  // Defer the query used for filtering so fast typing never blocks the input;
  // the immediate `query` still drives the search box value.
  const deferredQuery = useDeferredValue(query);
  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const conversationIdsKey = useMemo(
    () => conversations?.map((c) => c.id).join("|") ?? "",
    [conversations],
  );

  // Core snippets always load from the conversation API. Optional capability
  // enrichment is invoked only when that source-owned slot was compiled.
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    const controller = new AbortController();
    (async () => {
      try {
        const [enrichment, snips] = await Promise.all([
          slots.row?.load(conversations, controller.signal) ??
            Promise.resolve(new Map()),
          loadConversationSnippets(conversations),
        ]);
        if (controller.signal.aborted) return;
        setAdapterPresentations(enrichment);
        setSnippets((prev) => {
          if (
            Object.entries(snips).every(([key, value]) => prev[key] === value)
          ) {
            return prev;
          }
          return { ...prev, ...snips };
        });
      } catch {
        // Leave previously loaded enrichment/snippets intact on error.
      }
    })();
    return () => controller.abort();
  }, [conversationIdsKey, conversations, slots.row]);

  // Per-id view-model cache. The list renders the raw conversation records, so
  // their identity is stable while the list data is; the `presentation`/`snippet`
  // pair the memoized row also depends on is resolved through this cache, which
  // reuses an entry while every input it was derived from is unchanged.
  const rowViewModelCache = useMemo(
    () => new Map<string, ConversationRowViewModelCacheEntry>(),
    [],
  );
  const getRowViewModel = useCallback(
    (conversation: Conversation) =>
      resolveConversationRowViewModel(
        rowViewModelCache,
        conversation,
        adapterPresentations.get(conversation.id),
        snippets,
      ),
    [adapterPresentations, rowViewModelCache, snippets],
  );

  // Drop view-models for conversations that left the list (deleted rows, server
  // filters that no longer match) so the cache cannot grow without bound.
  useEffect(() => {
    pruneConversationRowViewModelCache(rowViewModelCache, conversations);
  }, [conversations, rowViewModelCache]);

  const orderedConversations = useMemo(() => {
    if (!conversations) return [];
    return conversations
      .filter((conversation) => {
        if (!deferredQuery) return true;
        const viewModel = getRowViewModel(conversation);
        const haystack = [
          conversation.zalo_chat_id ?? conversation.id,
          viewModel.presentation.searchText,
          viewModel.snippet,
        ]
          .filter(Boolean)
          .join(" ");
        return vietnameseSearchIncludes(haystack, deferredQuery);
      })
      .sort((first, second) => compareConversationRows(first, second, readIds));
  }, [conversations, deferredQuery, getRowViewModel, readIds]);

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
  }, [
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    orderedConversations.length,
  ]);

  return (
    <aside className="panel left-panel" aria-label="Danh sách cuộc trò chuyện">
      <WorkspaceRail
        adapterSlot={
          <ChannelAdapterSelector
            provider={getEffectiveConversationChannelProvider(searchParams)}
            searchParams={searchParams}
            onSearchParamsChange={(next) =>
              setSearchParams(next, { replace: true })
            }
          />
        }
        searchSlot={
          <div className="inbox-toolbar">
            <label className="search">
              <span className="sr-only">
                {slots.row ? "Tìm ứng viên hoặc số điện thoại" : "Tìm liên hệ"}
              </span>
              <svg className="icon">
                <use href="#i-search" />
              </svg>
              <input
                type="search"
                className="tt-input"
                placeholder="Tìm kiếm"
                aria-label={
                  slots.row ? "Tìm ứng viên hoặc số điện thoại" : "Tìm liên hệ"
                }
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
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
        ) : orderedConversations.length === 0 ? (
          <ListEmptyState
            kind={query || hasServerFilter ? "filtered" : "empty"}
            onAction={
              query || hasServerFilter ? clearSearchAndFilters : undefined
            }
          />
        ) : (
          orderedConversations.map((conversation) => {
            const viewModel = getRowViewModel(conversation);
            return (
              <ConversationListItem
                key={conversation.id}
                conversation={conversation}
                presentation={viewModel.presentation}
                snippet={viewModel.snippet}
                isRead={readIds.has(conversation.id)}
                isActive={selectedId === conversation.id}
                onSelect={onSelect}
              />
            );
          })
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

const WorkspaceRail = ({
  adapterSlot,
  searchSlot,
}: {
  adapterSlot: ReactNode;
  searchSlot: ReactNode;
}) => (
  <div className="workspace-rail" aria-label="Tin nhắn">
    <div className="workspace-title">
      <div className="workspace-title-copy">
        <span className="workspace-rail-kicker">Tương tác đa kênh</span>
        <div className="workspace-title-row">
          <h1 className="workspace-heading">Hộp thư</h1>
        </div>
      </div>
    </div>
    {adapterSlot}
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
  const conversationFromCurrentPage =
    conversations?.find((conversation) => conversation.id === urlId) ?? null;
  const shouldLoadDeepLink = Boolean(
    urlId && conversations && !conversationFromCurrentPage,
  );
  const {
    data: deepLinkedConversation,
    isPending: isDeepLinkPending,
    isError: isDeepLinkError,
  } = useGetOne<Conversation>(
    "conversations",
    { id: urlId ?? "" },
    { enabled: shouldLoadDeepLink },
  );
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
    if (!conversations) return;
    const hasUrlConversation = Boolean(
      urlId &&
        (conversationFromCurrentPage || deepLinkedConversation?.id === urlId),
    );
    const hasSelectedConversation = !!findSelectedConversation(
      conversations,
      selectedId,
      deepLinkedConversation,
    );

    if (urlId && shouldLoadDeepLink && isDeepLinkPending) return;

    // A stale deep link (?id= for a deleted/invalid conversation) would leave
    // detailOpen true with no selectable conversation, stranding the user on
    // an empty detail pane. Clear it so the list shows instead.
    if (
      isMobile &&
      urlId &&
      !hasUrlConversation &&
      (!shouldLoadDeepLink || isDeepLinkError)
    ) {
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

    if (!isMobile && conversations.length > 0) {
      const firstId = (conversations[0] as Conversation).id;
      setSelectedId(firstId);
      if (
        urlId &&
        !hasUrlConversation &&
        (!shouldLoadDeepLink || isDeepLinkError)
      ) {
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
  }, [
    conversations,
    conversationFromCurrentPage,
    deepLinkedConversation,
    isDeepLinkError,
    isDeepLinkPending,
    isMobile,
    selectedId,
    setSearchParams,
    shouldLoadDeepLink,
    urlId,
  ]);

  const selected = findSelectedConversation(
    conversations,
    selectedId,
    deepLinkedConversation,
  );

  // `setSearchParams` is memoized on `location.search` (react-router 7), so its
  // identity changes on every navigation. Depending on it directly would
  // re-create `onSelect` whenever the URL changes and re-render every memoized
  // row — including the rows that a plain "open this one" click must not touch.
  // Keep the latest setter in a ref: event handlers only run after the commit
  // that refreshed it.
  const setSearchParamsRef = useRef(setSearchParams);
  useEffect(() => {
    setSearchParamsRef.current = setSearchParams;
  }, [setSearchParams]);

  // Stable identity so memoized ConversationListItem children don't re-render
  // on every list state change (the parent re-renders on search/selection, but
  // `onSelect` itself never needs to change — it only calls stable setters).
  const openConversation = useCallback((c: Conversation) => {
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
    setSearchParamsRef.current((prev) =>
      conversationSelectionParams(prev, c.id),
    );
  }, []);

  const backToList = () => {
    setSearchParams((prev) => conversationSelectionParams(prev, null), {
      replace: true,
    });
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
              onDeleted={backToList}
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
  const [searchParams, setSearchParams] = useSearchParams();
  const provider = getEffectiveConversationChannelProvider(searchParams);
  const rawProvider = searchParams.get("channel_provider");
  useEffect(() => {
    if (rawProvider === null || rawProvider === provider) return;
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete("channel_provider");
        return next;
      },
      { replace: true },
    );
  }, [provider, rawProvider, setSearchParams]);
  const serverFilter = getConversationListServerFilter(searchParams);
  // When the reason changes (or clears), remount cleanly so no stale rows from
  // the previous reason linger and react-admin's permanent-filter bookkeeping
  // resets. Acceptable per the spec note.
  const listKey = getConversationListKey(serverFilter);
  return (
    // Infinite pagination keeps the inbox light while removing visible page
    // controls. Row previews come from /conversations/last-messages/batch for
    // the loaded rows only.
    <InfiniteListBase
      key={listKey}
      perPage={25}
      sort={CONVERSATION_LIST_SORT}
      filter={serverFilter}
    >
      <ConversationListContent />
    </InfiniteListBase>
  );
};
