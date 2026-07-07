import { MessageCircle, Phone, UserRound } from "lucide-react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";

import { chatRepository } from "../conversations/chatRepository";
import { apiJson } from "../providers/rest/api";
import type { Conversation, Lead } from "../types";

type RecruitingCommandCenterProps = {
  variant?: "desktop" | "mobile";
};

type ListEnvelope<T> = {
  data: T[];
  total: number;
};

type AttentionCandidate = {
  conversation: Conversation;
  lead: Lead | null;
  snippet: string;
  reason: string;
};

type DashboardQueues = {
  attention: AttentionCandidate[];
  contacts: Lead[];
};

const DASHBOARD_LIST_LIMIT = 8;

const isWaitingForHuman = (conversation: Conversation): boolean => {
  if (conversation.needs_human) return true;
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

const attentionReason = (conversation: Conversation): string => {
  if (conversation.needs_human) return "Bot cần người";
  if (conversation.mode === "semi_auto") return "Semi-auto";
  if (conversation.mode === "human") return "Human mode";
  return "Cần phản hồi";
};

const normalizeText = (value: string | null | undefined): string =>
  value?.trim() ?? "";

const compactIdentifier = (value: string | null | undefined): string => {
  const clean = normalizeText(value);
  if (!clean) return "";
  return clean.length > 4 ? clean.slice(-4) : clean;
};

const candidateName = (lead: Lead | null, fallback: string): string => {
  const name = normalizeText(lead?.name);
  if (name) return name;
  const suffix = compactIdentifier(lead?.phone || fallback);
  return suffix ? `Ứng viên ${suffix}` : "Ứng viên chưa định danh";
};

const initialsFor = (name: string): string => {
  const words = name
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean);
  if (words.length === 0) return "UV";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
};

const formatTime = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const uniqueConversations = (rows: Conversation[]): Conversation[] => {
  const seen = new Set<string>();
  const result: Conversation[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    result.push(row);
  }
  return result;
};

const fetchDashboardQueues = async (): Promise<DashboardQueues> => {
  const [attentionBody, recentBody, contactsBody] = await Promise.all([
    apiJson<ListEnvelope<Conversation>>(
      "/api/v1/conversations?needs_attention=true&per_page=12&sort=last_inbound_at&order=DESC",
    ),
    apiJson<ListEnvelope<Conversation>>(
      "/api/v1/conversations?status=OPEN&per_page=40&sort=last_inbound_at&order=DESC",
    ),
    apiJson<ListEnvelope<Lead>>(
      "/api/v1/leads?per_page=80&sort=updated_at&order=DESC",
    ),
  ]);

  const waitingConversations = uniqueConversations([
    ...(attentionBody.data ?? []),
    ...(recentBody.data ?? []),
  ])
    .filter(isWaitingForHuman)
    .slice(0, DASHBOARD_LIST_LIMIT);

  const [leads, snippets] = await Promise.all([
    chatRepository.getLeadsByZaloIds(
      waitingConversations.map((conversation) => conversation.zalo_chat_id),
    ),
    chatRepository.getLastMessages(waitingConversations),
  ]);

  const leadByZalo = new Map<string, Lead>();
  for (const lead of leads) {
    if (lead.zalo_id && !leadByZalo.has(lead.zalo_id)) {
      leadByZalo.set(lead.zalo_id, lead);
    }
  }

  const contacts = (contactsBody.data ?? [])
    .filter((lead) => normalizeText(lead.name) && normalizeText(lead.phone))
    .slice(0, DASHBOARD_LIST_LIMIT);

  return {
    attention: waitingConversations.map((conversation) => ({
      conversation,
      lead: leadByZalo.get(conversation.zalo_chat_id) ?? null,
      snippet: snippets[conversation.zalo_chat_id] ?? "",
      reason: attentionReason(conversation),
    })),
    contacts,
  };
};

export const RecruitingCommandCenter = ({
  variant = "desktop",
}: RecruitingCommandCenterProps) => {
  const navigate = useNavigate();
  const { data, isPending } = useQuery({
    queryKey: ["dashboard-queues"],
    queryFn: fetchDashboardQueues,
    refetchInterval: 30_000,
  });
  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  const attentionRows = data?.attention ?? [];
  const contactRows = data?.contacts ?? [];

  const counts = useMemo(
    () => ({
      attention: attentionRows.length,
      contacts: contactRows.length,
    }),
    [attentionRows.length, contactRows.length],
  );

  return (
    <div className={shellClass}>
      <header className="recruiting-hero recruiting-hero-minimal">
        <div className="recruiting-hero-copy">
          <span className="recruiting-eyebrow">Dashboard</span>
          <h1>Tuyển dụng</h1>
        </div>
      </header>

      <section className="recruiting-two-column">
        <article className="recruiting-panel">
          <div className="recruiting-panel-header">
            <div>
              <span className="recruiting-eyebrow">Cần phản hồi</span>
              <h2>Ứng viên đang chờ</h2>
            </div>
            <span className="dashboard-panel-count">{counts.attention}</span>
          </div>
          <div className="dashboard-candidate-list">
            {isPending ? (
              <DashboardListSkeleton />
            ) : attentionRows.length > 0 ? (
              attentionRows.map((row) => (
                <AttentionRow
                  key={row.conversation.id}
                  row={row}
                  onClick={() =>
                    navigate(`/conversations?id=${row.conversation.id}`)
                  }
                />
              ))
            ) : (
              <EmptyDashboardList label="Không có ứng viên đang chờ." />
            )}
          </div>
        </article>

        <article className="recruiting-panel">
          <div className="recruiting-panel-header">
            <div>
              <span className="recruiting-eyebrow">Có liên hệ</span>
              <h2>Tên và số điện thoại</h2>
            </div>
            <span className="dashboard-panel-count">{counts.contacts}</span>
          </div>
          <div className="dashboard-candidate-list">
            {isPending ? (
              <DashboardListSkeleton />
            ) : contactRows.length > 0 ? (
              contactRows.map((lead) => (
                <ContactRow key={lead.id} lead={lead} />
              ))
            ) : (
              <EmptyDashboardList label="Chưa có ứng viên đủ tên và số điện thoại." />
            )}
          </div>
        </article>
      </section>
    </div>
  );
};

const CandidateAvatar = ({ name }: { name: string }) => (
  <span className="dashboard-candidate-avatar" aria-hidden>
    {initialsFor(name)}
  </span>
);

const AttentionRow = ({
  row,
  onClick,
}: {
  row: AttentionCandidate;
  onClick: () => void;
}) => {
  const name = candidateName(row.lead, row.conversation.zalo_chat_id);
  const phone = normalizeText(row.lead?.phone);
  const time = formatTime(row.conversation.last_inbound_at);

  return (
    <button type="button" className="dashboard-candidate-row" onClick={onClick}>
      <CandidateAvatar name={name} />
      <span className="dashboard-candidate-main">
        <strong>{name}</strong>
        <span>{row.snippet || phone || row.conversation.zalo_chat_id}</span>
      </span>
      <span className="dashboard-candidate-meta">
        <span>{row.reason}</span>
        {time ? <small>{time}</small> : null}
      </span>
    </button>
  );
};

const ContactRow = ({ lead }: { lead: Lead }) => {
  const name = candidateName(lead, lead.zalo_id);
  const phone = normalizeText(lead.phone);

  return (
    <div className="dashboard-candidate-row is-static">
      <CandidateAvatar name={name} />
      <span className="dashboard-candidate-main">
        <strong>{name}</strong>
        <span>{phone}</span>
      </span>
      <span className="dashboard-candidate-meta">
        <Phone className="size-4" />
      </span>
    </div>
  );
};

const EmptyDashboardList = ({ label }: { label: string }) => (
  <div className="dashboard-empty-list">
    <UserRound className="size-4" />
    <span>{label}</span>
  </div>
);

const DashboardListSkeleton = () => (
  <>
    {Array.from({ length: 3 }).map((_, index) => (
      <div key={index} className="dashboard-candidate-row is-skeleton">
        <Skeleton shimmer className="dashboard-candidate-avatar" />
        <span className="dashboard-candidate-main">
          <Skeleton shimmer className="h-4 w-32 rounded-md" />
          <Skeleton shimmer className="h-3 w-48 rounded-md" />
        </span>
        <MessageCircle className="size-4 text-muted-foreground/50" />
      </div>
    ))}
  </>
);
