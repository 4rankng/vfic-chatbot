import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Users,
  UserCheck,
  TrendingUp,
  AlertCircle,
  Activity,
} from "lucide-react";
import MobileHeader from "../layout/MobileHeader";
import { MobileContent } from "../layout/MobileContent";
import { useNavigate } from "react-router";
import { useDashboardStats } from "./useDashboardStats";

const Wrapper = ({ children }: { children: React.ReactNode }) => {
  return (
    <>
      <MobileHeader>
        <div className="flex items-center gap-2 py-1">
          <img
            src="/light-logo.png"
            className="h-12 w-auto dark:hidden"
            alt="Logo"
          />
          <img
            src="/dark-logo.png"
            className="h-12 w-auto hidden dark:block"
            alt="Logo"
          />
        </div>
      </MobileHeader>
      <MobileContent>{children}</MobileContent>
    </>
  );
};

export const MobileDashboard = () => {
  const navigate = useNavigate();

  const {
    totalLeads: totalLeadsCount,
    qualifiedCount: qualifiedLeads,
    unreadConversationCount: unreadConvs,
    hiredRate,
    stageBreakdown,
    isPending: isLoading,
  } = useDashboardStats();

  return (
    <Wrapper>
      <div className="flex flex-col gap-5 mt-2 pb-6">
        {/* Analytics Title for Mobile */}
        <div>
          <h2 className="font-display text-2xl font-extrabold tracking-wide uppercase text-foreground">
            Tổng quan phân tích
          </h2>
          <p className="text-muted-foreground text-xs font-medium mt-0.5">
            Hiệu suất tuyển dụng
          </p>
        </div>

        {/* KPI Cards (2 columns layout) */}
        <div className="grid grid-cols-2 gap-3.5">
          <MobileKpiCard
            title="Tổng khách hàng"
            value={
              isLoading
                ? "..."
                : totalLeadsCount.toString().padStart(2, "0")
            }
            icon={<Users className="size-4" />}
            description="Tất cả quy trình"
          />
          <MobileKpiCard
            title="Cần phản hồi"
            value={
              isLoading
                ? "..."
                : unreadConvs.toString().padStart(2, "0")
            }
            icon={<AlertCircle className="size-4" />}
            description="Đợi phản hồi"
          />
          <MobileKpiCard
            title="Đạt chuẩn"
            value={
              isLoading
                ? "..."
                : qualifiedLeads.toString().padStart(2, "0")
            }
            icon={<UserCheck className="size-4" />}
            description="Sẵn sàng tuyển dụng"
          />
          <MobileKpiCard
            title="Tỷ lệ tuyển"
            value={isLoading ? "..." : `${hiredRate}%`}
            icon={<TrendingUp className="size-4" />}
            description="Tỷ lệ chuyển đổi"
          />
        </div>

        {/* Pipeline Distribution snapshot */}
        <Card className="border border-border bg-card shadow-xs">
          <CardHeader className="pb-3 pt-4 px-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-base font-bold tracking-wider uppercase text-foreground">
                Phân bổ quy trình
              </span>
            </CardTitle>
            <CardDescription className="text-[11px] text-muted-foreground">
              Tổng quan khách hàng theo giai đoạn
            </CardDescription>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="flex flex-col gap-2.5">
              {isLoading ? (
                <div className="w-full h-[120px] flex items-center justify-center text-muted-foreground">
                  <Activity className="size-6 animate-spin" />
                </div>
              ) : (
                stageBreakdown.map((stage) => {
                  const count = stage.count;
                  const percentage = stage.percentage;
                  const bgClass = stage.color;
                  return (
                    <div
                      key={stage.value}
                      className="flex items-center gap-3 cursor-pointer hover:bg-muted/40 p-1.5 rounded-lg transition-all"
                      onClick={() =>
                        navigate(
                          `/leads?filter=%7B"lead_stage"%3A"${stage.value}"%7D`,
                        )
                      }
                    >
                      <div className="w-20 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground truncate">
                        {stage.label}
                      </div>
                      <div className="w-6 text-xs font-semibold font-mono text-right">
                        {count}
                      </div>
                      <div className="flex-1 h-1.5 bg-muted/60 rounded-full overflow-hidden flex">
                        <div
                          className={`h-full ${bgClass} rounded-full`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <div className="w-8 text-[10px] font-semibold font-mono text-muted-foreground text-right">
                        {percentage}%
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </CardContent>
        </Card>

        {/* System Activity */}
        <Card className="border border-border bg-card shadow-xs">
          <CardHeader className="pb-3 pt-4 px-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-base font-bold tracking-wider uppercase text-foreground">
                Hoạt động hệ thống
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 flex flex-col gap-4">
            <div
              className="space-y-1 cursor-pointer hover:bg-muted/50 p-1.5 rounded-md transition-colors"
              onClick={() => navigate("/conversations")}
            >
              <h4 className="text-xs font-semibold flex items-center gap-2">
                <AlertCircle className="size-3.5 text-amber-500" />
                Cần chú ý
              </h4>
              <p className="text-[10px] text-muted-foreground ml-5.5">
                {unreadConvs} cuộc trò chuyện cần phản hồi
              </p>
            </div>

            <div
              className="space-y-1 cursor-pointer hover:bg-muted/50 p-1.5 rounded-md transition-colors"
              onClick={() =>
                navigate(`/leads?filter=%7B"lead_stage"%3A"QUALIFIED"%7D`)
              }
            >
              <h4 className="text-xs font-semibold flex items-center gap-2">
                <UserCheck className="size-3.5 text-cyan-500" />
                Ứng viên đạt chuẩn
              </h4>
              <p className="text-[10px] text-muted-foreground ml-5.5">
                {qualifiedLeads} ứng viên cần xem xét
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </Wrapper>
  );
};

const MobileKpiCard = ({
  title,
  value,
  icon,
  description,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
  description: string;
}) => (
  <Card className="border border-border bg-card shadow-xs p-3">
    <div className="flex items-center justify-between">
      <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground truncate mr-1">
        {title}
      </span>
      <div className="p-1 bg-muted/40 text-muted-foreground border border-border/50 rounded-md shrink-0">
        {icon}
      </div>
    </div>
    <div className="text-xl font-semibold font-mono tracking-tight text-foreground mt-1.5">
      {value}
    </div>
    <p className="text-[9px] font-medium text-muted-foreground/80 mt-1 truncate">
      {description}
    </p>
  </Card>
);
