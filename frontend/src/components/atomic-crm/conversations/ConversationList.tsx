import { useState, useMemo, useEffect } from "react";
import {
  ListBase,
  useListContext,
  useDataProvider,
  RecordContextProvider,
} from "ra-core";
import { useSearchParams } from "react-router";
import type { Conversation, Lead, Message } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { InboxIcons } from "./InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import MobileHeader from "../layout/MobileHeader";
import "./inbox.css";

type ModeFilter = "all" | "bot" | "handoff";

type ConversationRow = Conversation & {
  _lead?: Lead | null;
  _lastMessage?: Message | null;
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
  const lastMessage = conversation._lastMessage;
  const preview = lastMessage?.content?.slice(0, 80) ?? "Chưa có tin nhắn";
  const time = getRelativeTimeString(
    conversation.last_inbound_at ?? conversation.updated_at,
  );

  const name =
    lead?.name || `Ứng viên · ${(conversation.zalo_chat_id || "").slice(-4)}`;
  const colors = getLeadStatusColor(lead);

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
        <span className="conv-preview">{preview}</span>
        <span className="conv-bottom">
          {conversation.mode === "human" && (
            <span className={`mini-chip handoff`}>
              <svg className="icon">
                <use href="#i-user" />
              </svg>
              {statusLabel}
            </span>
          )}
        </span>
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
  const dataProvider = useDataProvider<any>();
  const [leads, setLeads] = useState<Record<string, Lead | null>>({});
  const [lastMessages, setLastMessages] = useState<
    Record<string, Message | null>
  >({});
  const [query, setQuery] = useState("");
  const mode: ModeFilter = "all";

  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    let cancelled = false;
    (async () => {
      const zaloIds = Array.from(
        new Set(conversations.map((c) => c.zalo_chat_id).filter(Boolean)),
      );
      const fetchedLeads: Record<string, Lead | null> = {};
      await Promise.all(
        zaloIds.map(async (zaloId) => {
          try {
            const { data } = await dataProvider.getList("leads", {
              filter: { zalo_id: zaloId },
              pagination: { page: 1, perPage: 1 },
              sort: { field: "updated_at", order: "DESC" },
            });
            fetchedLeads[zaloId] = (data?.[0] as Lead) ?? null;
          } catch {
            fetchedLeads[zaloId] = null;
          }
        }),
      );
      if (cancelled) return;
      setLeads((prev) => ({ ...prev, ...fetchedLeads }));
    })();
    return () => {
      cancelled = true;
    };
  }, [conversations, dataProvider]);

  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    let cancelled = false;
    (async () => {
      const fetched: Record<string, Message | null> = {};
      await Promise.all(
        conversations.map(async (c) => {
          try {
            let msg: Message | null = null;
            if (import.meta.env.DEV) {
              const { dataProvider: fakeProvider } = await import(
                "../providers/fakerest"
              );
              try {
                const all = await fakeProvider.getList("messages", {
                  filter: { conversation_id: c.id },
                  pagination: { page: 1, perPage: 1 },
                  sort: { field: "created_at", order: "DESC" },
                });
                msg = (all?.data?.[0] as Message) ?? null;
              } catch {}
            }
            if (!msg) {
              const { chatRepository } = await import("./chatRepository");
              msg = await chatRepository.getLastMessage(c.zalo_chat_id);
            }
            fetched[c.id] = msg;
          } catch {
            fetched[c.id] = null;
          }
        }),
      );
      if (cancelled) return;
      setLastMessages((prev) => ({ ...prev, ...fetched }));
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
        _lastMessage: lastMessages[c.id] ?? null,
      }))
      .filter((c) => {
        if (mode !== "all") {
          const m = c.mode === "bot" ? "bot" : "handoff";
          if (m !== mode) return false;
        }
        if (query) {
          const q = query.toLowerCase();
          const haystack = [
            c.zalo_chat_id,
            c._lead?.name,
            c._lead?.phone,
            c._lastMessage?.content,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(q)) return false;
        }
        return true;
      });
  }, [conversations, leads, lastMessages, mode, query]);

  return (
    <aside className="panel left-panel" aria-label="Danh sách cuộc trò chuyện">
      <div className="inbox-tools">
        <label className="search">
          <svg className="icon">
            <use href="#i-search" />
          </svg>
          <input
            type="search"
            placeholder="Tìm ứng viên hoặc tin nhắn"
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
          rows.map((c) => (
            <ConversationListItem
              key={c.id}
              conversation={c}
              isActive={selectedId === c.id}
              onSelect={onSelect}
            />
          ))
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
