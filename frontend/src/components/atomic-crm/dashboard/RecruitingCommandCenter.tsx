import {
  AlertTriangle,
  Bot,
  Clock3,
  MessageCircle,
  Phone,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";

import { useDashboardStats, type DashboardStats } from "./useDashboardStats";

type RecruitingCommandCenterProps = {
  variant?: "desktop" | "mobile";
};

type CommandMetric = {
  label: string;
  value: string;
  tone: "danger" | "good" | "warn" | "info";
  Icon: LucideIcon;
  href: string;
};

const formatCount = (value: number) =>
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value);

const formatPercent = (value: number) => `${Math.round(value)}%`;

const buildMetrics = (stats: DashboardStats): CommandMetric[] => [
  {
    label: "Cần xử lý",
    value: formatCount(stats.unreadConversationCount),
    tone: stats.unreadConversationCount > 0 ? "danger" : "good",
    Icon: AlertTriangle,
    href: "/conversations",
  },
  {
    label: "Ứng viên gọi",
    value: formatCount(stats.qualifiedCount),
    tone: "good",
    Icon: Phone,
    href: "/leads",
  },
  {
    label: "Đang mở",
    value: formatCount(stats.openConversations),
    tone: "info",
    Icon: MessageCircle,
    href: "/conversations",
  },
  {
    label: "Semi-auto",
    value: formatCount(stats.activeTurns),
    tone: stats.activeTurns > 0 ? "warn" : "info",
    Icon: Clock3,
    href: "/conversations",
  },
];

export const RecruitingCommandCenter = ({
  variant = "desktop",
}: RecruitingCommandCenterProps) => {
  const navigate = useNavigate();
  const stats = useDashboardStats();
  const metrics = useMemo(() => buildMetrics(stats), [stats]);
  const shellClass =
    variant === "mobile"
      ? "recruiting-command recruiting-command-mobile"
      : "recruiting-command";

  return (
    <div className={shellClass}>
      <header className="recruiting-hero compact">
        <div className="recruiting-hero-copy">
          <span className="recruiting-eyebrow">Dashboard</span>
          <h1>Tuyển dụng</h1>
        </div>
        <div className="recruiting-hero-actions">
          <button
            type="button"
            className="recruiting-action primary"
            onClick={() => navigate("/conversations")}
          >
            <MessageCircle className="size-4" />
            Mở chat
          </button>
          <button
            type="button"
            className="recruiting-action"
            onClick={() => navigate("/leads")}
          >
            <Users className="size-4" />
            Ứng viên
          </button>
        </div>
      </header>

      <section className="recruiting-metric-grid" aria-label="Chỉ số chính">
        {metrics.map(({ label, value, tone, Icon, href }) => (
          <button
            key={label}
            type="button"
            className={`recruiting-metric ${tone}`}
            onClick={() => navigate(href)}
          >
            <span className="metric-topline">
              <span>{label}</span>
              <Icon className="size-4" />
            </span>
            {stats.isPending ? (
              <Skeleton className="mt-3 h-8 w-20 rounded-md" />
            ) : (
              <strong>{value}</strong>
            )}
          </button>
        ))}
      </section>

      <section className="recruiting-two-column">
        <article className="recruiting-panel">
          <div className="recruiting-panel-header">
            <div>
              <span className="recruiting-eyebrow">Chat</span>
              <h2>Cần người xử lý</h2>
            </div>
            <button type="button" onClick={() => navigate("/conversations")}>
              Xem chat
            </button>
          </div>
          <div className="recruiting-queue-list">
            <QueueRow
              Icon={AlertTriangle}
              tone="danger"
              title="Chờ trả lời"
              value={stats.unreadConversationCount}
              onClick={() => navigate("/conversations")}
            />
            <QueueRow
              Icon={Bot}
              tone="warn"
              title={`Bot tạm dừng ${formatPercent(stats.botSuppressionRate * 100)}`}
              value={stats.botSuppressedCount}
              onClick={() => navigate("/conversations")}
            />
            <QueueRow
              Icon={MessageCircle}
              tone="info"
              title="Đang mở"
              value={stats.openConversations}
              onClick={() => navigate("/conversations")}
            />
          </div>
        </article>

        <article className="recruiting-panel">
          <div className="recruiting-panel-header">
            <div>
              <span className="recruiting-eyebrow">Ứng viên</span>
              <h2>Có thông tin liên hệ</h2>
            </div>
            <button type="button" onClick={() => navigate("/leads")}>
              Xem ứng viên
            </button>
          </div>
          <div className="recruiting-queue-list">
            <QueueRow
              Icon={Phone}
              tone="good"
              title="Đủ liên hệ"
              value={stats.qualifiedCount}
              onClick={() => navigate("/leads")}
            />
            <QueueRow
              Icon={Users}
              tone="info"
              title="Ưu tiên"
              value={stats.hotLeads}
              onClick={() => navigate("/leads")}
            />
            <QueueRow
              Icon={Clock3}
              tone="warn"
              title="Follow-up"
              value={stats.pendingFollowups}
              onClick={() => navigate("/leads")}
            />
          </div>
        </article>
      </section>
    </div>
  );
};

const QueueRow = ({
  Icon,
  title,
  value,
  tone,
  onClick,
}: {
  Icon: LucideIcon;
  title: string;
  value: number;
  tone: "danger" | "good" | "warn" | "info";
  onClick: () => void;
}) => (
  <button
    type="button"
    className={`queue-command-row ${tone}`}
    onClick={onClick}
  >
    <span className="queue-command-icon">
      <Icon className="size-4" />
    </span>
    <span>
      <strong>{title}</strong>
    </span>
    <b>{formatCount(value)}</b>
  </button>
);
