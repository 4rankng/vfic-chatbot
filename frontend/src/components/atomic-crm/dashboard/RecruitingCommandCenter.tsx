import { MessageCircle, Phone, RefreshCw, UserRound } from "lucide-react";
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
  attentionError: boolean;
  contactsError: boolean;
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
  if (conversation.mode === "semi_auto") return "Chờ nhân viên";
  if (conversation.mode === "human") return "Cần phản hồi";
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
  const [attentionResult, recentResult, contactsResult] = await Promise.allSettled([
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
  const attentionBody =
    attentionResult.status === "fulfilled" ? attentionResult.value : null;
  const recentBody =
    recentResult.status === "fulfilled" ? recentResult.value : null;
  const contactsBody =
    contactsResult.status === "fulfilled" ? contactsResult.value : null;

  const waitingConversations = uniqueConversations([
    ...(attentionBody?.data ?? []),
    ...(recentBody?.data ?? []),
  ])
    .filter(isWaitingForHuman)
    .slice(0, DASHBOARD_LIST_LIMIT);

  const [leadsResult, snippetsResult] = await Promise.allSettled([
    chatRepository.getLeadsByZaloIds(
      waitingConversations.map((conversation) => conversation.zalo_chat_id),
    ),
    chatRepository.getLastMessages(waitingConversations),
  ]);
  const leads = leadsResult.status === "fulfilled" ? leadsResult.value : [];
  const snippets =
    snippetsResult.status === "fulfilled" ? snippetsResult.value : {};

  const leadByZalo = new Map<string, Lead>();
  for (const lead of leads) {
    if (lead.zalo_id && !leadByZalo.has(lead.zalo_id)) {
      leadByZalo.set(lead.zalo_id, lead);
    }
  }

  const contacts = (contactsBody?.data ?? [])
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
    attentionError:
      attentionResult.status === "rejected" || recentResult.status === "rejected",
    contactsError: contactsResult.status === "rejected",
  };
};

export const RecruitingCommandCenter = ({
  variant = "desktop",
}: RecruitingCommandCenterProps) => {
  const navigate = useNavigate();
  const { data, isPending, refetch, dataUpdatedAt } = useQuery({
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
          <span className="recruiting-eyebrow">Theo dõi trực tiếp</span>
          <h1>Tổng quan tuyển dụng</h1>
          <p>
            {dataUpdatedAt
              ? `Cập nhật lúc ${formatTime(new Date(dataUpdatedAt).toISOString())}`
              : "Đang tải các hàng đợi tuyển dụng"}
          </p>
        </div>
        <button
          type="button"
          className="dashboard-refresh"
          onClick={() => void refetch()}
          disabled={isPending}
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          Làm mới
        </button>
      </header>

      {data && (data.attentionError || data.contactsError) ? (
        <div className="dashboard-inline-error" role="status">
          <span>
            {data.attentionError && data.contactsError
              ? "Không thể cập nhật đầy đủ hàng đợi. Dữ liệu đã tải vẫn được giữ lại."
              : data.attentionError
                ? "Không thể cập nhật hàng đợi cần phản hồi. Danh sách liên hệ vẫn dùng được."
                : "Không thể cập nhật danh sách liên hệ. Hàng đợi cần phản hồi vẫn dùng được."}
          </span>
          <button type="button" onClick={() => void refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}

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
              <>
                {attentionRows.map((row) => (
                  <AttentionRow
                    key={row.conversation.id}
                    row={row}
                    onClick={() =>
                      navigate(`/conversations?id=${row.conversation.id}`)
                    }
                  />
                ))}
                {data?.attentionError ? (
                  <DashboardQueueError
                    label="Một phần hàng đợi cần phản hồi chưa tải được."
                    onRetry={refetch}
                  />
                ) : null}
              </>
            ) : data?.attentionError ? (
              <DashboardQueueError label="Không tải được hàng đợi cần phản hồi." onRetry={refetch} />
            ) : (
              <EmptyDashboardList
                label="Không có ứng viên đang chờ. Mọi cuộc trò chuyện đang được xử lý."
                actionLabel="Mở hộp thư"
                onAction={() => navigate("/conversations")}
              />
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
            ) : data?.contactsError ? (
              <DashboardQueueError label="Không tải được danh sách liên hệ." onRetry={refetch} />
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

const EmptyDashboardList = ({
  label,
  actionLabel,
  onAction,
}: {
  label: string;
  actionLabel?: string;
  onAction?: () => void;
}) => (
  <div className="dashboard-empty-list">
    <UserRound className="size-4" />
    <span>{label}</span>
    {actionLabel && onAction ? (
      <button type="button" onClick={onAction}>
        {actionLabel}
      </button>
    ) : null}
  </div>
);

const DashboardQueueError = ({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => void;
}) => (
  <div className="dashboard-empty-list" role="status">
    <span>{label}</span>
    <button type="button" onClick={() => void onRetry()}>
      Thử lại
    </button>
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
