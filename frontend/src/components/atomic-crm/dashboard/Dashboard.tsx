import { useGetList } from "ra-core";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { TopToolbar } from "../layout/TopToolbar";
import {
  Users,
  UserCheck,
  TrendingUp,
  Activity,
  AlertCircle,
} from "lucide-react";
import { LEAD_STAGES } from "../leads/LeadListContent";
import type { Lead, Conversation } from "../types";
import { useNavigate } from "react-router-dom";

export const Dashboard = () => {
  const navigate = useNavigate();

  // Fetch metrics
  const { data: allLeads, isPending: isLoadingLeads } = useGetList<Lead>(
    "leads",
    {
      pagination: { page: 1, perPage: 1000 },
    },
  );

  const { data: allConversations, isPending: isLoadingConversations } =
    useGetList<Conversation>("conversations", {
      pagination: { page: 1, perPage: 1000 },
    });

  // Calculate stats
  const totalLeadsCount = allLeads?.length || 0;
  const qualifiedLeads =
    allLeads?.filter((l) => l.lead_stage === "QUALIFIED").length || 0;
  const unreadConvs =
    allConversations?.filter((c) => c.mode === "human").length || 0; // Simple heuristic for now

  const hiredLeads =
    allLeads?.filter((l) => l.lead_stage === "HIRED").length || 0;
  const hiredRate = totalLeadsCount
    ? Math.round((hiredLeads / totalLeadsCount) * 100)
    : 0;

  return (
    <div className="flex flex-col gap-6 mx-auto w-full pb-8">
      <TopToolbar className="flex-col items-start md:flex-row md:items-end gap-4 pb-5 mb-2">
        <div className="mr-auto">
          <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground">
            Tổng quan phân tích
          </h2>
          <p className="text-muted-foreground text-sm font-medium mt-1">
            Hiệu suất tuyển dụng trên mọi quy trình đang hoạt động
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <span>Tất cả quy trình</span>
          <span>•</span>
          <span>30 ngày qua</span>
          <span>•</span>
          <span>Cập nhật 5 phút trước</span>
        </div>
      </TopToolbar>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard
          title="Tổng khách hàng"
          value={
            isLoadingLeads ? "..." : totalLeadsCount.toString().padStart(2, "0")
          }
          description="Trên tất cả quy trình"
          icon={<Users className="w-4 h-4" />}
          trend="+12%"
          trendUp={true}
        />
        <KpiCard
          title="Cần phản hồi"
          value={
            isLoadingConversations
              ? "..."
              : unreadConvs.toString().padStart(2, "0")
          }
          description="Đợi nhân viên phản hồi"
          icon={<AlertCircle className="w-4 h-4" />}
          trend={unreadConvs > 0 ? `${unreadConvs} đang xử lý` : undefined}
          trendUp={false}
          neutral={unreadConvs === 0}
        />
        <KpiCard
          title="Ứng viên đạt chuẩn"
          value={
            isLoadingLeads ? "..." : qualifiedLeads.toString().padStart(2, "0")
          }
          description="Sẵn sàng tuyển dụng"
          icon={<UserCheck className="w-4 h-4" />}
          trend="+5%"
          trendUp={true}
        />
        <KpiCard
          title="Tỷ lệ chuyển đổi"
          value={isLoadingLeads ? "..." : `${hiredRate}%`}
          description="Tỷ lệ khách hàng thành tuyển dụng"
          icon={<TrendingUp className="w-4 h-4" />}
          trend={hiredRate === 0 ? "Giai đoạn đầu" : "Đang hoạt động"}
          trendUp={hiredRate > 0}
          neutral={hiredRate === 0}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Main Chart */}
        <Card className="md:col-span-2 border-0 bg-card shadow-sm hover:shadow-md transition-all duration-300">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Phân bổ quy trình
              </span>
            </CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Tổng quan khách hàng trên các giai đoạn
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3">
              {isLoadingLeads ? (
                <div className="w-full h-[200px] flex items-center justify-center text-muted-foreground">
                  <Activity className="w-8 h-8 animate-spin" />
                </div>
              ) : (
                LEAD_STAGES.map((stage) => {
                  const count =
                    allLeads?.filter((l) => l.lead_stage === stage.value)
                      .length || 0;
                  const percentage = totalLeadsCount
                    ? Math.round((count / totalLeadsCount) * 100)
                    : 0;
                  // extract color for bg
                  const bgClass = stage.color;
                  return (
                    <div
                      key={stage.value}
                      className="flex items-center gap-4 cursor-pointer hover:bg-muted/40 p-2.5 rounded-xl transition-all"
                      onClick={() =>
                        navigate(
                          `/leads?filter=%7B"lead_stage"%3A"${stage.value}"%7D`,
                        )
                      }
                    >
                      <div className="w-24 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {stage.label}
                      </div>
                      <div className="w-8 text-sm font-semibold font-mono text-right">
                        {count}
                      </div>
                      <div className="flex-1 h-2 bg-muted/60 rounded-full overflow-hidden flex">
                        <div
                          className={`h-full ${bgClass} rounded-full`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <div className="w-12 text-xs font-semibold font-mono text-muted-foreground text-right">
                        {percentage}%
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </CardContent>
        </Card>

        {/* Side Panel */}
        <Card className="border-0 bg-card shadow-sm hover:shadow-md transition-all duration-300 flex flex-col">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Hoạt động hệ thống
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col gap-6">
            <div
              className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2"
              onClick={() => navigate("/conversations")}
            >
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-amber-500" />
                Cần chú ý
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                {unreadConvs} cuộc trò chuyện cần phản hồi
              </p>
            </div>

            <div
              className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2"
              onClick={() =>
                navigate(`/leads?filter=%7B"lead_stage"%3A"QUALIFIED"%7D`)
              }
            >
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-cyan-500" />
                Khách hàng đạt chuẩn
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                {qualifiedLeads} ứng viên cần xem xét
              </p>
            </div>

            <div className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-500" />
                Hoạt động gần đây
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                Quy trình cập nhật · 12 phút trước
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

// Reusable KPI Component
const KpiCard = ({
  title,
  value,
  description,
  icon,
  trend,
  trendUp,
  neutral,
}: {
  title: string;
  value: string;
  description: string;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
  neutral?: boolean;
}) => (
  <Card className="border-0 bg-card shadow-sm hover:shadow-md transition-all duration-300 group overflow-hidden relative">
    <CardHeader className="flex flex-row items-center justify-between pb-3">
      <CardTitle className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        {title}
      </CardTitle>
      <div className="p-2 bg-muted/40 text-muted-foreground border border-border/50 rounded-lg group-hover:bg-primary/10 group-hover:text-primary group-hover:border-primary/20 transition-colors">
        {icon}
      </div>
    </CardHeader>
    <CardContent className="pb-4">
      <div className="text-4xl font-semibold font-mono tracking-tight text-foreground">
        {value}
      </div>
      <div className="flex items-center mt-2 space-x-2">
        <p className="text-[11px] font-medium text-muted-foreground/80">
          {description}
        </p>
        {trend && (
          <span
            className={`text-[10px] font-bold font-mono px-2 py-0.5 rounded-full ${
              neutral
                ? "bg-muted-dim/15 text-muted-dim"
                : trendUp
                  ? "bg-green/12 text-green"
                  : "bg-destructive/12 text-destructive"
            }`}
          >
            {trend}
          </span>
        )}
      </div>
    </CardContent>
  </Card>
);
