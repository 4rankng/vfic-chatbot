import { useEffect, useState, useRef, useMemo } from "react";
import {
  ShowBase,
  useRecordContext,
  useDataProvider,
  useNotify,
  useRefresh,
} from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertTriangle,
  Bot,
  Inbox,
  Lock,
  Send,
  Sparkles,
  UserCircle,
  User as UserIcon,
} from "lucide-react";
import { getSupabaseClient } from "../providers/supabase/supabase";
import { cn } from "@/lib/utils";
import type { Conversation, Message } from "../types";
import { CrmDataProvider } from "../providers/supabase/dataProvider";

type SenderKind = "candidate" | "bot" | "recruiter" | "system";

const classify = (msg: Message): SenderKind => {
  if (msg.type === "system") return "system";
  if (msg.type === "inbound") return "candidate";
  if (msg.data?.recruiter_id) return "recruiter";
  return "bot";
};

const SENDER_META: Record<
  SenderKind,
  {
    label: string;
    icon: typeof Bot;
    bubble: string;
    align: "start" | "end" | "center";
  }
> = {
  candidate: {
    label: "Candidate",
    icon: UserIcon,
    bubble: "bg-muted text-foreground",
    align: "start",
  },
  bot: {
    label: "AI Bot",
    icon: Bot,
    bubble: "bg-blue-100 text-blue-950 dark:bg-blue-900/40 dark:text-blue-50",
    align: "end",
  },
  recruiter: {
    label: "Recruiter",
    icon: UserCircle,
    bubble: "bg-primary text-primary-foreground",
    align: "end",
  },
  system: {
    label: "System",
    icon: Sparkles,
    bubble: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100",
    align: "center",
  },
};

const formatTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
};

const extractText = (value: unknown): string => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) =>
        part && typeof part === "object" && "text" in part
          ? String((part as { text: unknown }).text ?? "")
          : String(part),
      )
      .join("")
      .trim();
  }
  return String(value);
};

/**
 * vfic_chat_histories.message is { type: "ai"|"human"|"tool", content, data? }.
 * Direction cannot come from type alone: candidate-inbound AND recruiter-outbound
 * are both "human". Discriminator = message.data.recruiter_id (set by the n8n
 * "VFIC Human Reply" workflow on recruiter replies).
 */
const toMessage = (row: any): Message | null => {
  const msg = row?.message ?? {};
  const type = String(msg.type ?? "").toLowerCase();
  if (type !== "ai" && type !== "human") return null; // hide tool / unknown
  const recruiterId = msg.data?.recruiter_id;
  const isRecruiter = type === "human" && Boolean(recruiterId);
  const rawContent = isRecruiter
    ? (msg.data?.content ?? msg.content)
    : msg.content;
  return {
    id: String(row.id),
    zalo_message_id: String(row.id),
    conversation_id: row.session_id,
    type: type === "ai" || isRecruiter ? "outbound" : "inbound",
    content: extractText(rawContent),
    data: { recruiter_id: recruiterId },
    created_at:
      msg.data?.created_at ?? row.created_at ?? new Date().toISOString(),
  };
};

const tryLoadDemoMessages = async (
  zaloChatId: string,
): Promise<Message[]> => {
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!zaloChatId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    const fetchInitial = async () => {
      try {
        const { data, error: err } = await getSupabaseClient()
          .from("vfic_chat_histories")
          .select("*")
          .eq("session_id", zaloChatId)
          .order("id", { ascending: true });
        if (cancelled) return;
        if (err) {
          // Supabase unreachable / table missing → fall through to demo data.
          const demo = await tryLoadDemoMessages(zaloChatId);
          if (cancelled) return;
          setMessages(demo);
          setIsLoading(false);
          return;
        }
        const mapped = (data ?? [])
          .map(toMessage)
          .filter((m): m is Message => m != null);
        setMessages(mapped);
        setIsLoading(false);
      } catch {
        // No Supabase at all → use demo data.
        if (cancelled) return;
        const demo = await tryLoadDemoMessages(zaloChatId);
        if (cancelled) return;
        setMessages(demo);
        setIsLoading(false);
      }
    };
    fetchInitial();

    let cleanup: (() => void) | undefined;
    try {
      const channel = getSupabaseClient()
        .channel(`chat_${zaloChatId}`)
        .on(
          "postgres_changes",
          {
            event: "INSERT",
            schema: "public",
            table: "vfic_chat_histories",
            filter: `session_id=eq.${zaloChatId}`,
          },
          (payload) => {
            const newMsg = toMessage(payload.new);
            if (!newMsg) return;
            setMessages((prev) =>
              prev.some((m) => m.id === newMsg.id) ? prev : [...prev, newMsg],
            );
          },
        )
        .subscribe();
      cleanup = () => getSupabaseClient().removeChannel(channel);
    } catch {
      // Supabase not available in demo — skip realtime.
    }

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [zaloChatId]);

  return { messages, isLoading, error };
};

const MessageBubble = ({
  msg,
  showTime,
}: {
  msg: Message;
  showTime?: boolean;
}) => {
  const kind = classify(msg);
  const meta = SENDER_META[kind];
  const Icon = meta.icon;
  const isCentered: boolean = meta.align === "center";

  if (isCentered) {
    return (
      <div className="flex justify-center">
        <div
          className={cn(
            "max-w-md rounded-lg px-4 py-2 text-center text-xs shadow-sm",
            meta.bubble,
          )}
        >
          <div className="mb-0.5 flex items-center justify-center gap-1 font-semibold uppercase tracking-wide opacity-70">
            <Icon className="size-3" />
            {meta.label}
          </div>
          <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex w-full",
        (meta.align as string) === "end" ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 shadow-sm",
          meta.bubble,
        )}
      >
        <div
          className={cn(
            "mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide",
            "opacity-70",
          )}
        >
          <Icon className="size-3" />
          {meta.label}
          {showTime && msg.created_at && (
            <span className="ml-1 font-normal normal-case opacity-80">
              • {formatTime(msg.created_at)}
            </span>
          )}
        </div>
        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {msg.content}
        </div>
      </div>
    </div>
  );
};

export const ConversationShowContent = () => {
  const record = useRecordContext<Conversation>();
  const { messages, isLoading, error } = useConversationRealtime(
    record?.zalo_chat_id,
  );
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [localMode, setLocalMode] = useState<"bot" | "human" | undefined>(
    undefined,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Group consecutive messages from the same sender for visual cohesion.
  const grouped = useMemo(() => {
    return messages.map((msg, idx) => {
      const prev = messages[idx - 1];
      const sameKind = prev && classify(prev) === classify(msg);
      return { msg, isFirstOfGroup: !sameKind };
    });
  }, [messages]);

  if (!record) return null;

  // After takeover/release the record context is stale until the parent
  // re-fetches; fall back to the locally-tracked mode for snappy UX.
  const effectiveMode = localMode ?? record.mode;
  const isBotMode = effectiveMode === "bot";

  const handleTakeover = async () => {
    try {
      await dataProvider.takeOverConversation(record.id);
      setLocalMode("human");
      notify("Conversation taken over", { type: "success" });
      refresh();
    } catch (e: any) {
      notify(e?.message ?? "Failed to take over", { type: "error" });
    }
  };

  const handleRelease = async () => {
    try {
      await dataProvider.releaseConversation(record.id);
      setLocalMode("bot");
      notify("Conversation released to bot", { type: "success" });
      refresh();
    } catch (e: any) {
      notify(e?.message ?? "Failed to release", { type: "error" });
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reply.trim() || isBotMode) return;

    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(record.id, reply);
      setReply("");
    } catch (e: any) {
      notify(e?.message ?? "Failed to send", { type: "error" });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Card className="flex h-[calc(100vh-220px)] flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b px-4 py-3 md:px-6 md:py-4">
        <div className="flex min-w-0 items-center gap-3">
          <CardTitle className="flex items-center gap-2 truncate text-base">
            <Inbox className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">
              {record.zalo_chat_id || "Conversation"}
            </span>
          </CardTitle>
          <Badge
            variant={isBotMode ? "secondary" : "default"}
            className="shrink-0 gap-1"
          >
            {isBotMode ? (
              <>
                <Bot className="size-3" /> Bot
              </>
            ) : (
              <>
                <UserCircle className="size-3" /> Human
              </>
            )}
          </Badge>
        </div>
        <div className="flex shrink-0 gap-2">
          {isBotMode ? (
            <Button size="sm" onClick={handleTakeover} className="gap-2">
              <UserCircle className="size-4" />
              Take Over
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={handleRelease}
              className="gap-2"
            >
              <Bot className="size-4" />
              Release to Bot
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        {error ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex max-w-sm flex-col items-center gap-2 text-center">
              <AlertTriangle className="size-8 text-destructive" />
              <p className="font-medium">Failed to load messages</p>
              <p className="text-xs text-muted-foreground">{error}</p>
            </div>
          </div>
        ) : isLoading ? (
          <div className="flex flex-1 flex-col gap-3 overflow-hidden p-6">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className={cn(
                  "flex w-full",
                  i % 2 === 0 ? "justify-start" : "justify-end",
                )}
              >
                <Skeleton
                  className={cn(
                    "h-14 rounded-2xl",
                    i % 2 === 0 ? "w-2/5" : "w-1/2",
                  )}
                />
              </div>
            ))}
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="rounded-full bg-muted p-4">
                <Inbox className="size-8 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium">No messages yet</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  The chat history is empty. New messages from Zalo will appear
                  here in real time.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <ScrollArea className="flex-1 px-4 py-4 md:px-6" ref={scrollRef}>
            <div className="flex flex-col gap-2.5">
              {grouped.map(({ msg, isFirstOfGroup }, idx) => (
                <MessageBubble
                  key={msg.id}
                  msg={msg}
                  showTime={isFirstOfGroup || idx === 0}
                />
              ))}
            </div>
          </ScrollArea>
        )}

        <div className="border-t bg-background p-3 md:p-4">
          {isBotMode ? (
            <div className="mb-2 flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
              <Lock className="mt-0.5 size-3.5 shrink-0" />
              <span>
                The bot is currently handling this conversation. Take over to
                start replying manually.
              </span>
            </div>
          ) : null}
          <form onSubmit={handleSend} className="flex items-center gap-2">
            <Input
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder={
                isBotMode
                  ? "Take over the conversation to reply…"
                  : "Type your reply…"
              }
              disabled={isBotMode || isSending}
              className="flex-1"
              autoComplete="off"
            />
            <Button
              type="submit"
              size="icon"
              disabled={isBotMode || isSending || !reply.trim()}
              aria-label="Send message"
              title="Send message"
            >
              <Send className="size-4" />
            </Button>
          </form>
        </div>
      </CardContent>
    </Card>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <TopToolbar>
        <h2 className="mr-auto text-xl font-semibold">Conversation</h2>
      </TopToolbar>
      <ConversationShowContent />
    </ShowBase>
  );
};
