import { useState, useMemo, useEffect } from "react";
import { ListBase, useListContext, useDataProvider } from "ra-core";
import { useLocation } from "react-router";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  Bot,
  Filter,
  Inbox,
  MessageSquare,
  Search,
  UserCircle,
} from "lucide-react";
import { TopToolbar } from "../layout/TopToolbar";

import type { Conversation, Lead, Message } from "../types";
import { ConversationShowContent } from "./ConversationShow";
import { RecordContextProvider } from "ra-core";
import { getRelativeTimeString } from "../leads/leadUtils";
import { LeadAvatar } from "../leads/LeadAvatar";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";

type ModeFilter = "all" | "bot" | "human";

type ConversationRow = Conversation & {
  _lead?: Lead | null;
  _lastMessage?: Message | null;
};

const ModeBadge = ({ mode }: { mode: "bot" | "human" }) => (
  <Badge
    variant={mode === "human" ? "default" : "secondary"}
    className="gap-1 text-[10px] font-semibold uppercase tracking-wide"
  >
    {mode === "human" ? (
      <>
        <UserCircle className="size-3" /> Human
      </>
    ) : (
      <>
        <Bot className="size-3" /> Bot
      </>
    )}
  </Badge>
);

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
  const preview = lastMessage?.content?.slice(0, 80) ?? "No messages yet";
  const time = getRelativeTimeString(
    conversation.last_inbound_at ?? conversation.updated_at,
  );
  const senderKind: "candidate" | "recruiter" | "bot" | "system" = lastMessage
    ? lastMessage.type === "inbound"
      ? "candidate"
      : lastMessage.type === "system"
        ? "system"
        : lastMessage.data?.recruiter_id
          ? "recruiter"
          : "bot"
    : "bot";

  return (
    <button
      type="button"
      onClick={() => onSelect(conversation)}
      className={cn(
        "flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors",
        isActive
          ? "bg-accent"
          : "hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none",
      )}
    >
      <LeadAvatar record={lead as any} size="md" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold">
            {lead?.name ||
              `Unknown lead · ending ${(conversation.zalo_chat_id || "").slice(-4)}`}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">{time}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {senderKind === "candidate"
              ? "👤"
              : senderKind === "recruiter"
                ? "🧑‍💼"
                : senderKind === "system"
                  ? "🔹"
                  : "🤖"}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {preview}
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <ModeBadge mode={conversation.mode} />
          {lead?.lead_stage && (
            <Badge variant="outline" className="text-[10px]">
              {lead.lead_stage}
            </Badge>
          )}
        </div>
      </div>
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
  const { data: conversations, isPending } = useListContext<Conversation>();
  const dataProvider = useDataProvider<any>();
  const [leads, setLeads] = useState<Record<string, Lead | null>>({});
  const [lastMessages, setLastMessages] = useState<
    Record<string, Message | null>
  >({});
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ModeFilter>("all");

  // Hydrate leads + last messages for visible conversations.
  useEffect(() => {
    if (!conversations || conversations.length === 0) return;
    let cancelled = false;
    (async () => {
      const zaloIds = Array.from(
        new Set(
          conversations
            .map((c) => c.zalo_chat_id)
            .filter((id): id is string => Boolean(id)),
        ),
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

  // Fetch the last message for each conversation for the preview snippet.
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
              // Try real Supabase query
              const { getSupabaseClient } = await import(
                "../providers/supabase/supabase"
              );
              const { data } = await getSupabaseClient()
                .from("vfic_chat_histories")
                .select("*")
                .eq("session_id", c.zalo_chat_id)
                .order("id", { ascending: false })
                .limit(1);
              if (data && data.length > 0) {
                // need to use the same toMessage logic as ConversationShow
                const row = data[0];
                const msgData = row?.message ?? {};
                const type = String(msgData.type ?? "").toLowerCase();
                const recruiterId = msgData.data?.recruiter_id;
                const isRecruiter = type === "human" && Boolean(recruiterId);
                const rawContent = isRecruiter
                  ? (msgData.data?.content ?? msgData.content)
                  : msgData.content;
                let content = "";
                if (typeof rawContent === "string") content = rawContent;
                else if (Array.isArray(rawContent)) {
                  content = rawContent
                    .map((p) =>
                      p && typeof p === "object" && "text" in p
                        ? String(p.text ?? "")
                        : String(p),
                    )
                    .join("")
                    .trim();
                } else content = String(rawContent ?? "");

                msg = {
                  id: String(row.id),
                  zalo_message_id: String(row.id),
                  conversation_id: row.session_id,
                  type: type === "ai" || isRecruiter ? "outbound" : "inbound",
                  content: content,
                  data: { recruiter_id: recruiterId },
                  created_at:
                    msgData.data?.created_at ??
                    row.created_at ??
                    new Date().toISOString(),
                };
              }
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
    const filtered = conversations
      .map((c) => ({
        ...c,
        _lead: leads[c.zalo_chat_id] ?? null,
        _lastMessage: lastMessages[c.id] ?? null,
      }))
      .filter((c) => {
        if (mode !== "all" && c.mode !== mode) return false;
        if (query) {
          const q = query.toLowerCase();
          const haystack = [
            c.zalo_chat_id,
            c._lead?.name,
            c._lead?.phone,
            c._lead?.desired_job,
            c._lastMessage?.content,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(q)) return false;
        }
        return true;
      });
    return filtered;
  }, [conversations, leads, lastMessages, mode, query]);

  return (
    <div className="flex h-full flex-col">
      {/* Search + filter bar */}
      <div className="flex flex-col gap-2 border-b p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations…"
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="size-3.5 text-muted-foreground" />
          <div className="flex flex-1 gap-1">
            {(["all", "bot", "human"] as ModeFilter[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn(
                  "rounded-md px-2 py-1 text-xs font-medium capitalize transition-colors",
                  mode === m
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
              >
                {m}
              </button>
            ))}
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {rows.length}
          </span>
        </div>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto">
        {isPending ? (
          <div className="flex flex-col">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-start gap-3 border-b p-4">
                <Skeleton className="size-10 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-1/2" />
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-4 w-20" />
                </div>
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
            <Inbox className="size-10 opacity-50" />
            <p className="text-sm font-medium">No conversations</p>
            <p className="text-xs">
              {query
                ? "Try a different search term."
                : "Conversations from Zalo will appear here."}
            </p>
          </div>
        ) : (
          <div>
            {rows.map((c) => (
              <ConversationListItem
                key={c.id}
                conversation={c}
                isActive={selectedId === c.id}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const ConversationDetail = ({
  conversation,
}: {
  conversation: Conversation;
}) => {
  return (
    <RecordContextProvider value={conversation}>
      <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_300px] xl:grid-cols-[1fr_340px]">
        <div className="overflow-hidden">
          <ConversationShowContent />
        </div>
        <aside className="hidden border-l lg:block">
          <LeadProfilePanel />
        </aside>
      </div>
    </RecordContextProvider>
  );
};

const EmptyDetail = () => (
  <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
    <div className="rounded-full bg-muted p-6">
      <MessageSquare className="size-12 text-muted-foreground/60" />
    </div>
    <div>
      <p className="text-base font-medium text-foreground">
        Select a conversation
      </p>
      <p className="mt-1 max-w-sm text-sm">
        Pick a conversation from the list on the left to view its full chat
        history and reply as a recruiter.
      </p>
    </div>
  </div>
);

const ConversationListContent = () => {
  const { data: conversations } = useListContext<Conversation>();
  const location = useLocation();

  // Default to the most recent conversation if none is selected.
  const initialId =
    conversations && conversations.length > 0
      ? (conversations[0] as Conversation).id
      : null;

  const [selectedId, setSelectedId] = useState<string | null>(initialId);

  useEffect(() => {
    // If the URL hash points at a specific conversation, use that.
    const match = location.pathname.match(/\/conversations\/([^/]+)/);
    if (match) setSelectedId(match[1]);
  }, [location.pathname]);

  const selected =
    conversations?.find((c) => c.id === selectedId) ??
    (conversations?.[0] as Conversation | undefined) ??
    null;

  return (
    <>
      <TopToolbar>
        <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground mr-auto">
          Conversations
        </h2>
      </TopToolbar>
      <Card className="mt-4 overflow-hidden p-0 py-0">
        <div className="grid h-[calc(100vh-220px)] min-h-[500px] grid-cols-1 md:grid-cols-[360px_1fr] rounded-[inherit] overflow-hidden">
          <div className="border-r">
            <ConversationListPanel
              selectedId={selected?.id ?? null}
              onSelect={(c) => setSelectedId(c.id)}
            />
          </div>
          <div className="bg-background">
            {selected ? (
              <ConversationDetail conversation={selected} />
            ) : (
              <EmptyDetail />
            )}
          </div>
        </div>
      </Card>
    </>
  );
};

// ListBase provides the ListContext; the consumer that calls useListContext
// must be a child of ListBase, not a sibling rendered alongside it.
export const ConversationList = () => (
  <ListBase perPage={500} sort={{ field: "updated_at", order: "DESC" }}>
    <ConversationListContent />
  </ListBase>
);
