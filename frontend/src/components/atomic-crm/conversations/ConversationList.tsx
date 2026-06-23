import { useState, useMemo, useEffect } from "react";
import { ListBase, useListContext, RecordContextProvider } from "ra-core";
import { useSearchParams } from "react-router";
import type { Conversation, Lead } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { InboxIcons } from "./InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import MobileHeader from "../layout/MobileHeader";
import { chatRepository } from "./chatRepository";
import "./inbox.css";

// How many contact rows to render at a time. The list still loads (and client
// search still covers) every conversation; we only gate the rendered subset so
// the first paint stays instant even with hundreds of contacts.
const VISIBLE_PAGE_SIZE = 50;

type ConversationRow = Conversation & {
  _lead?: Lead | null;
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

const ConversationListItem = ({
  conversation,
  isActive,
  onSelect,
}: {
  conversation: ConversationRow;
  isActive: boolean;
  onSelect: (c: Conversation) => void;
}) => {
  const lead = conversation._lead;
  const time = getRelativeTimeString(
    conversation.last_inbound_at ?? conversation.updated_at,
  );

  const name =
    lead?.name || `Ứng viên · ${(conversation.zalo_chat_id || "").slice(-4)}`;
  const colors = getLeadStatusColor(lead);
  // Contacts-only inbox: no chat-history probe. Show the contact's phone as a
  // muted subtitle when available; otherwise the row is just name + time.
  const subtitle = lead?.phone || "";

  const statusLabel = conversation.mode === "human" ? "Cần tiếp quản" : "";

  return (
    <button
      className={`conversation ${isActive ? "active" : ""}`}
      onClick={() => onSelect(conversation)}
      aria-label={`Mở hội thoại với ${name}`}
    >
      <span
        className="avatar round"
        style={{ "--avatar-bg": colors.bg, "--avatar-ink": colors.ink } as any}
      >
        <svg className="icon" style={{ width: "22px", height: "22px" }}>
          <use href="#i-user" />
        </svg>
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
};

const ConversationListPanel = ({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (c: Conversation) => void;
}) => {
  const { data: conversations } = useListContext<Conversation>();
  const [leads, setLeads] = useState<Record<string, Lead | null>>({});
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(VISIBLE_PAGE_SIZE);

  // Resolve contact (lead) details for every conversation in ONE batched
  // request, replacing the old per-zalo_id N+1 that fired hundreds of leads
  // requests on mount. getLeadsByZaloIds orders by updated_at DESC, so the
  // first lead seen per zalo_id is the most recent (same rule as data?.[0]).
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    let cancelled = false;
    (async () => {
      const zaloIds = Array.from(
        new Set(conversations.map((c) => c.zalo_chat_id).filter(Boolean)),
      );
      try {
        const all = await chatRepository.getLeadsByZaloIds(zaloIds);
        if (cancelled) return;
        const byZalo: Record<string, Lead | null> = {};
        for (const lead of all) {
          const key = lead.zalo_id;
          if (key && byZalo[key] === undefined) byZalo[key] = lead;
        }
        setLeads((prev) => ({ ...prev, ...byZalo }));
      } catch {
        // Leave previously loaded leads intact on error.
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
  }, [conversations, leads, query]);

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

      <div className="conversations">
        {rows.length === 0 ? (
          <div className="empty-state">Không tìm thấy hội thoại phù hợp.</div>
        ) : (
          <>
            {rows.slice(0, visibleCount).map((c) => (
              <ConversationListItem
                key={c.id}
                conversation={c}
                isActive={selectedId === c.id}
                onSelect={onSelect}
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

  const openConversation = (c: Conversation) => {
    setSelectedId(c.id);
    // Push (not replace) so each opened conversation is a history entry and the
    // browser back button returns to the list.
    setSearchParams((prev) => {
      prev.set("id", c.id);
      return prev;
    });
  };

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
