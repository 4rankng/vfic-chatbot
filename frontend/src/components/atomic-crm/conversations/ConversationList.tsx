import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { ListBase, useListContext, RecordContextProvider } from "ra-core";
import { useSearchParams } from "react-router";
import type { Conversation, Lead } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { InboxIcons } from "./InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import MobileHeader from "../layout/MobileHeader";
import { chatRepository } from "./chatRepository";
import { Skeleton } from "@/components/ui/skeleton";
import "./inbox.css";

// How many contact rows to render at a time. The list still loads (and client
// search still covers) every conversation; we only gate the rendered subset so
// the first paint stays instant even with hundreds of contacts.
const VISIBLE_PAGE_SIZE = 50;

type ConversationRow = Conversation & {
  _lead?: Lead | null;
  _snippet?: string;
};

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead || (!lead.name && !lead.phone))
    return { bg: "var(--surface-solid)", ink: "var(--ink-faint)" };
  if (!lead.phone || !lead.desired_job)
    return { bg: "var(--brand-light)", ink: "var(--brand)" };
  return { bg: "var(--success-light)", ink: "var(--success)" };
};

const getRelativeTimeString = (dateStr?: string) => {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
};

// Hoisted static style objects so list rows don't allocate brand-new objects on
// every render (defeats React.memo). These have no per-row variance.
const UNREAD_BADGE_DOT_STYLE: React.CSSProperties = {
  position: "absolute",
  top: -2,
  right: -2,
  width: 12,
  height: 12,
  borderRadius: 9999,
  background: "var(--ember)",
  boxShadow: "0 0 0 2px var(--card)",
} as const;

const UNREAD_BADGE_COUNT_STYLE: React.CSSProperties = {
  position: "absolute",
  top: -6,
  right: -6,
  minWidth: 18,
  height: 18,
  padding: "0 4px",
  borderRadius: 9999,
  background: "var(--ember)",
  color: "#fff",
  fontSize: 10,
  fontWeight: 700,
  lineHeight: "18px",
  textAlign: "center",
  boxShadow: "0 0 0 2px var(--card)",
} as const;

const AVATAR_ICON_STYLE: React.CSSProperties = {
  width: "22px",
  height: "22px",
} as const;

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
  ({ conversation, isActive, onSelect, readIds }: ConversationListItemProps) => {
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

    const statusLabel = conversation.mode === "human" ? "Cần tiếp quản" : "";
    // Unread badge: optimistically cleared once opened (readIds); otherwise the
    // live counter kept in sync by the vfic_chat_histories_unread trigger.
    const unread = readIds.has(conversation.id)
      ? 0
      : conversation.unread_count ?? 0;

    return (
      <button
        className={`conversation ${isActive ? "active" : ""}`}
        onClick={() => onSelect(conversation)}
        aria-label={`Mở hội thoại với ${name}`}
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
          <svg className="icon" style={AVATAR_ICON_STYLE}>
            <use href="#i-user" />
          </svg>
          {unread > 0 && (
            <span
              aria-label={`${unread} tin nhắn chưa đọc`}
              style={
                unread === 1
                  ? UNREAD_BADGE_DOT_STYLE
                  : UNREAD_BADGE_COUNT_STYLE
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
          {subtitle && <span className="conv-preview">{subtitle}</span>}
          {conversation.mode === "human" && (
            <span className="conv-bottom">
              <span className={`mini-chip handoff`}>
                <svg className="icon">
                  <use href="#i-user" />
                </svg>
                {statusLabel}
              </span>
            </span>
          )}
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
      className="!rounded-full"
      style={{ width: 36, height: 36, flexShrink: 0 }}
    />
    <div
      className="conv-body"
      style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}
    >
      <Skeleton shimmer style={{ height: 13, width: "55%", borderRadius: 6 }} />
      <Skeleton shimmer style={{ height: 12, width: "85%", borderRadius: 6 }} />
    </div>
  </div>
);

const ConversationListPanel = ({
  selectedId,
  onSelect,
  readIds,
}: {
  selectedId: string | null;
  onSelect: (c: Conversation) => void;
  readIds: Set<string>;
}) => {
  const { data: conversations, isPending } = useListContext<Conversation>();
  const [leads, setLeads] = useState<Record<string, Lead | null>>({});
  const [snippets, setSnippets] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(VISIBLE_PAGE_SIZE);

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
        setLeads((prev) => ({ ...prev, ...byZalo }));
        setSnippets((prev) => ({ ...prev, ...snips }));
      } catch {
        // Leave previously loaded leads/snippets intact on error.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversations]);

  const rows: ConversationRow[] = useMemo(() => {
    if (!conversations) return [];
    return conversations
      .map((c) => ({
        ...c,
        _lead: leads[c.zalo_chat_id] ?? null,
        _snippet: snippets[c.zalo_chat_id] ?? "",
      }))
      .filter((c) => {
        if (query) {
          const q = query.toLowerCase();
          const haystack = [c.zalo_chat_id, c._lead?.name, c._lead?.phone]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(q)) return false;
        }
        return true;
      });
  }, [conversations, leads, snippets, query]);

  return (
    <aside className="panel left-panel" aria-label="Danh sách cuộc trò chuyện">
      <div className="inbox-tools">
        <label className="search">
          <svg className="icon">
            <use href="#i-search" />
          </svg>
          <input
            type="search"
            placeholder="Tìm ứng viên hoặc số điện thoại"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="search-key">⌘K</span>
        </label>
      </div>

      <div className="section-label">
        <span>Hộp thư đến</span>
        <span>{rows.length} cuộc trò chuyện</span>
      </div>

      <div className="conversations animate-in fade-in-0 duration-300">
        {isPending ? (
          Array.from({ length: 6 }).map((_, i) => (
            <ConversationListItemSkeleton key={i} />
          ))
        ) : rows.length === 0 ? (
          <div className="empty-state">Không tìm thấy hội thoại phù hợp.</div>
        ) : (
          <>
            {rows.slice(0, visibleCount).map((c) => (
              <ConversationListItem
                key={c.id}
                conversation={c}
                isActive={selectedId === c.id}
                onSelect={onSelect}
                readIds={readIds}
              />
            ))}
            {rows.length > visibleCount && (
              <button
                type="button"
                className="load-more-btn"
                onClick={() => setVisibleCount((c) => c + VISIBLE_PAGE_SIZE)}
              >
                Tải thêm ({rows.length - visibleCount} còn lại)
              </button>
            )}
          </>
        )}
      </div>
    </aside>
  );
};

const ConversationListContent = () => {
  const { data: conversations } = useListContext<Conversation>();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Optimistic unread-clears. Reset whenever the list refreshes so the server
  // state stays authoritative (markAsRead has reset unread_count) — otherwise a
  // fresh inbound that bumps the count back above 0 would stay hidden for the
  // whole session after a chat is opened once.
  const [pendingReadIds, setPendingReadIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    setPendingReadIds(new Set());
  }, [conversations]);

  const urlId = searchParams.get("id");
  // On mobile the detail pane is shown iff a conversation id is in the URL, so
  // the browser back button naturally returns to the list. Desktop always shows
  // the detail alongside the list.
  const detailOpen = !isMobile || !!urlId;

  // Seed the selection: a deep link (?id=) opens that conversation; otherwise
  // desktop auto-selects the first for an immediate detail view, while mobile
  // stays list-first until the user taps a row.
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;

    // A stale deep link (?id= for a deleted/invalid conversation) would leave
    // detailOpen true with no selectable conversation, stranding the user on
    // an empty detail pane. Clear it so the list shows instead.
    if (isMobile && urlId && !conversations.some((c) => c.id === urlId)) {
      setSearchParams(
        (prev) => {
          prev.delete("id");
          return prev;
        },
        { replace: true },
      );
      return;
    }

    if (selectedId) return;
    if (urlId && conversations.some((c) => c.id === urlId)) {
      setSelectedId(urlId);
    } else if (!isMobile) {
      setSelectedId((conversations[0] as Conversation).id);
    }
  }, [conversations, urlId, selectedId, isMobile, setSearchParams]);

  const selected = conversations?.find((c) => c.id === selectedId) ?? null;

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
    setSearchParams((prev) => {
      prev.set("id", c.id);
      return prev;
    });
  }, []);

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
    <div className="inbox-bg-container">
      {isMobile && <MobileHeader />}
      <InboxIcons />
      <main className={`app ${detailOpen ? "detail-open" : ""}`} id="app">
        <ConversationListPanel
          selectedId={selected?.id ?? null}
          onSelect={openConversation}
          readIds={pendingReadIds}
        />

        {selected ? (
          <RecordContextProvider value={selected}>
            <ConversationShowContent onOpenList={backToList} />
          </RecordContextProvider>
        ) : (
          <section className="panel center-panel">
            <div className="empty-state">
              Vui lòng chọn một cuộc trò chuyện từ danh sách.
            </div>
          </section>
        )}

        <div className="backdrop" onClick={backToList}></div>
      </main>
    </div>
  );
};

export const ConversationList = () => (
  <ListBase perPage={500} sort={{ field: "updated_at", order: "DESC" }}>
    <ConversationListContent />
  </ListBase>
);
