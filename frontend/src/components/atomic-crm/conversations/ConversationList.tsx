import { useState, useMemo, useEffect } from "react";
import {
  ListBase,
  useListContext,
  useDataProvider,
  RecordContextProvider,
} from "ra-core";
import { useLocation } from "react-router";
import type { Conversation, Lead, Message } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";
import { InboxIcons } from "./InboxIcons";
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
  const location = useLocation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [layoutState, setLayoutState] = useState<
    "" | "list-open" | "profile-open"
  >("");

  useEffect(() => {
    if (conversations && conversations.length > 0 && !selectedId) {
      const match = location.pathname.match(/\/conversations\/([^/]+)/);
      setSelectedId(match ? match[1] : (conversations[0] as Conversation).id);
    }
  }, [conversations, location.pathname, selectedId]);

  const selected = conversations?.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="inbox-bg-container">
      <InboxIcons />
      <main className={`app ${layoutState}`} id="app">
        <ConversationListPanel
          selectedId={selected?.id ?? null}
          onSelect={(c) => {
            setSelectedId(c.id);
            setLayoutState("");
          }}
        />

        {selected ? (
          <RecordContextProvider value={selected}>
            <ConversationShowContent
              onOpenList={() => setLayoutState("list-open")}
              onOpenProfile={() =>
                setLayoutState(
                  layoutState === "profile-open" ? "" : "profile-open",
                )
              }
            />
            <LeadProfilePanel />
          </RecordContextProvider>
        ) : (
          <section className="panel center-panel">
            <div className="empty-state">
              Vui lòng chọn một cuộc trò chuyện từ danh sách.
            </div>
          </section>
        )}

        <div className="backdrop" onClick={() => setLayoutState("")}></div>
      </main>
    </div>
  );
};

export const ConversationList = () => (
  <ListBase perPage={500} sort={{ field: "updated_at", order: "DESC" }}>
    <ConversationListContent />
  </ListBase>
);
