import { useEffect, useState, useRef } from "react";
import { useRecordContext, useDataProvider, useNotify, useTranslate, useGetList, ShowBase } from "ra-core";
import type { Conversation, Message, Lead } from "../types";
import { CrmDataProvider } from "../providers/supabase/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { getLeadStatusColor } from "./ConversationList";
import { chatRepository } from "./chatRepository";

const classify = (msg: Message): "user" | "bot" | "agent" | "system" | "event" => {
  if (msg.type === "system") return "system";
  if (msg.type === "inbound") return "user";
  if (msg.data?.recruiter_id) return "agent";
  return "bot";
};

const formatTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(d);
};

const tryLoadDemoMessages = async (zaloChatId: string): Promise<Message[]> => {
  if (!import.meta.env.DEV) return [];
  try {
    const fakerest = await import("../providers/fakerest");
    const { dataProvider } = fakerest;
    const { data: convs } = await dataProvider.getList("conversations", {
      filter: { zalo_chat_id: zaloChatId },
      pagination: { page: 1, perPage: 1 },
    });
    const convId = (convs?.[0] as any)?.id;
    if (!convId) return [];
    const { data } = await dataProvider.getList("messages", {
      filter: { conversation_id: convId },
      pagination: { page: 1, perPage: 1000 },
      sort: { field: "created_at", order: "ASC" },
    });
    return Array.isArray(data) ? (data as Message[]) : [];
  } catch {
    return [];
  }
};

const useConversationRealtime = (zaloChatId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!zaloChatId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);

    const fetchInitial = async () => {
      try {
        const mapped = await chatRepository.getConversationMessages(zaloChatId);
        if (cancelled) return;
        setMessages(mapped);
      } catch (err) {
        if (cancelled) return;
        if (import.meta.env.DEV) {
          const demo = await tryLoadDemoMessages(zaloChatId);
          if (cancelled) return;
          setMessages(demo);
        } else {
          setMessages([]);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    fetchInitial();

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(zaloChatId, (newMsg) => {
        setMessages((prev) => prev.some((m) => m.id === newMsg.id) ? prev : [...prev, newMsg]);
      });
    } catch {}

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [zaloChatId]);

  return { messages, isLoading };
};

export const ConversationShowContent = ({ onOpenList, onOpenProfile }: { onOpenList?: () => void, onOpenProfile?: () => void }) => {
  const record = useRecordContext<Conversation>();
  const { messages } = useConversationRealtime(record?.zalo_chat_id);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { isBotMode, handleTakeover, handleRelease } = useConversationActions(record);

  const { data: leadData } = useGetList(
    "leads",
    { filter: { zalo_id: record?.zalo_chat_id }, pagination: { page: 1, perPage: 1 } },
    { enabled: !!record?.zalo_chat_id }
  );
  const lead = leadData?.[0] as Lead | undefined;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reply.trim() || isBotMode) return;

    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(record!.zalo_chat_id, reply);
      setReply("");
    } catch (e: unknown) {
      const status = e instanceof HumanReplyError ? e.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), { type: "error" });
    } finally {
      setIsSending(false);
    }
  };

  const name = lead?.name || `Khách hàng · ${(record?.zalo_chat_id || "").slice(-4)}`;
  const colors = getLeadStatusColor(lead);

  return (
    <section className="panel center-panel" aria-label="Nội dung trò chuyện">
      <header className="chat-header">
        <button className="icon-btn mobile-toggle list-toggle" onClick={onOpenList} aria-label="Mở danh sách hội thoại">
          <svg className="icon"><use href="#i-menu"/></svg>
        </button>
        <div className="header-person">
          <div className="header-avatar" style={{ background: colors.bg, color: colors.ink, backgroundImage: 'none' }}>
            <svg className="icon" style={{ width: '24px', height: '24px' }}><use href="#i-user"/></svg>
          </div>
          <div className="person-copy">
            <div className="person-name-row">
              <span className="person-name">{name}</span>
              <span className="online-dot"></span>
            </div>
            <div className="person-meta">
              <svg className="icon"><use href="#i-briefcase"/></svg>
              <span>{lead?.desired_job || "Khách hàng mới"}</span>
            </div>
          </div>
        </div>
        <div className="header-actions">
          <button className="icon-btn small" aria-label="Ghi chú"><svg className="icon"><use href="#i-note"/></svg></button>
          <button className="icon-btn small mobile-toggle profile-toggle" onClick={onOpenProfile} aria-label="Mở hồ sơ ứng viên">
            <svg className="icon"><use href="#i-panel"/></svg>
          </button>
          <button 
            className={`takeover-btn ${!isBotMode ? 'taken' : ''}`} 
            onClick={isBotMode ? handleTakeover : handleRelease}
          >
            <svg className="icon"><use href={!isBotMode ? "#i-check" : "#i-user"}/></svg>
            <span>{!isBotMode ? "Đã tiếp nhận" : "Tiếp nhận"}</span>
          </button>
        </div>
      </header>

      <div className="chat-scroller" ref={scrollRef}>
        <div id="messageStream">
          {messages.map((m) => {
            const kind = classify(m);
            if (kind === "system" || kind === "event") {
              return (
                <div key={m.id} className={kind === "system" ? "day-marker" : "system-event"}>
                  {kind === "event" && <svg className="icon"><use href="#i-sparkles"/></svg>}
                  <span>{m.content}</span>
                </div>
              );
            }
            
            const senderLabel = kind === 'bot' ? 'AI Bot' : kind === 'agent' ? 'Tư vấn viên' : 'Ứng viên';
            const avatarIcon = kind === 'bot' ? 'i-bot' : 'i-user';
            
            return (
              <div key={m.id} className={`message-row ${kind}`}>
                {kind === "user" && (
                  <span className="message-avatar"><svg className="icon"><use href={`#${avatarIcon}`}/></svg></span>
                )}
                <div className="bubble">
                  <div className="bubble-meta">
                    <svg className="icon"><use href={`#${avatarIcon}`}/></svg>
                    <span>{senderLabel}</span>
                    <span className="bubble-time">{formatTime(m.created_at)}</span>
                  </div>
                  <p>{m.content}</p>
                </div>
                {kind !== "user" && (
                  <span className="message-avatar"><svg className="icon"><use href={`#${avatarIcon}`}/></svg></span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <footer className="composer-wrap">
        <div className="handoff-note">
          <svg className="icon"><use href={!isBotMode ? "#i-check" : "#i-lock"}/></svg>
          <span>{!isBotMode ? <><span className="strong">Bạn đang phụ trách</span> cuộc trò chuyện này.</> : <>AI đang phụ trách. <span className="strong">Tiếp nhận</span> để trả lời thủ công.</>}</span>
        </div>
        <form className={`composer ${isBotMode ? 'disabled' : ''}`} onSubmit={handleSend}>
          <button type="button" className="composer-action" aria-label="Đính kèm" disabled={isBotMode}>
            <svg className="icon"><use href="#i-paperclip"/></svg>
          </button>
          <textarea 
            rows={1} 
            placeholder={isBotMode ? "Tiếp nhận cuộc trò chuyện để trả lời…" : "Nhập tin nhắn..."}
            disabled={isBotMode || isSending}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(e); }
            }}
          />
          <button type="button" className="composer-action" aria-label="Biểu tượng cảm xúc" disabled={isBotMode}>
            <svg className="icon"><use href="#i-smile"/></svg>
          </button>
          <button type="submit" className="composer-action send" aria-label="Gửi tin nhắn" disabled={isBotMode || isSending || !reply.trim()}>
            <svg className="icon"><use href="#i-send"/></svg>
          </button>
        </form>
      </footer>
    </section>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
