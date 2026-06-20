import { useGetList, useTranslate } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { TopToolbar } from "../layout/TopToolbar";
import { Users, MessageCircle, UserCheck, TrendingUp, Activity, BarChart2 } from "lucide-react";
import { ResponsiveBar } from "@nivo/bar";
import { LEAD_STAGES } from "../leads/LeadListContent";
import { useTheme } from "@/components/admin/use-theme";
import type { Lead } from "../types";

export const Dashboard = () => {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const translate = useTranslate();

  // Fetch metrics
  const { data: allLeads, isPending: isLoadingLeads } = useGetList<Lead>("leads", {
    pagination: { page: 1, perPage: 1000 },
  });

  const { total: totalConversations, isPending: isLoadingConversations } = useGetList("conversations", {
    pagination: { page: 1, perPage: 1 },
  });

  // Calculate stats
  const totalLeads = allLeads?.length || 0;
  const hiredLeads = allLeads?.filter((l) => l.lead_stage === "HIRED").length || 0;
  const rejectedLeads = allLeads?.filter((l) => l.lead_stage === "REJECTED").length || 0;
  const activeLeads = totalLeads - hiredLeads - rejectedLeads;
  const hiredRate = totalLeads ? Math.round((hiredLeads / totalLeads) * 100) : 0;

  // Prepare Funnel Data for Nivo
  const funnelData = LEAD_STAGES.map((stage) => {
    const count = allLeads?.filter((l) => l.lead_stage === stage.value).length || 0;
    return {
      stage: stage.label,
      count,
      // Color logic based on stage
      color: stage.value === "HIRED" ? "hsl(var(--primary))" 
           : stage.value === "REJECTED" ? "hsl(var(--destructive))"
           : "hsl(var(--chart-1))"
    };
  });

  // Theme settings for Nivo
  const nivoTheme = {
    textColor: isDark ? "#e2e8f0" : "#334155",
    fontSize: 12,
    axis: {
      domain: { line: { stroke: isDark ? "#475569" : "#cbd5e1" } },
      ticks: { line: { stroke: isDark ? "#475569" : "#cbd5e1" } },
    },
    grid: {
      line: { stroke: isDark ? "#334155" : "#e2e8f0" },
    },
    tooltip: {
      container: {
        background: isDark ? "#1e293b" : "#ffffff",
        color: isDark ? "#f8fafc" : "#0f172a",
        fontSize: "13px",
        borderRadius: "8px",
        boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
      },
    },
  };

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto w-full pb-8">
      <TopToolbar>
        <h2 className="text-3xl font-bold tracking-tight mr-auto bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent pb-1">
          {translate("crm.dashboard.title")}
        </h2>
      </TopToolbar>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard
          title={translate("crm.dashboard.total_leads")}
          value={isLoadingLeads ? "..." : totalLeads.toString()}
          description={translate("crm.dashboard.across_pipelines")}
          icon={<Users className="w-5 h-5" />}
          trend="+12%"
          trendUp={true}
        />
        <KpiCard
          title={translate("crm.dashboard.active_conversations")}
          value={isLoadingConversations ? "..." : totalConversations?.toString() || "0"}
          description={translate("crm.dashboard.engaged")}
          icon={<MessageCircle className="w-5 h-5" />}
          trend="+5%"
          trendUp={true}
        />
        <KpiCard
          title={translate("crm.dashboard.hired_candidates")}
          value={isLoadingLeads ? "..." : hiredLeads.toString()}
          description={translate("crm.dashboard.success_placements")}
          icon={<UserCheck className="w-5 h-5" />}
        />
        <KpiCard
          title={translate("crm.dashboard.conversion_rate")}
          value={isLoadingLeads ? "..." : `${hiredRate}%`}
          description={translate("crm.dashboard.lead_to_hired")}
          icon={<TrendingUp className="w-5 h-5" />}
          trend="Healthy"
          trendUp={hiredRate > 0}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Chart */}
        <Card className="lg:col-span-2 shadow-sm border-border/50 hover:shadow-md transition-shadow duration-300">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart2 className="w-5 h-5 text-primary" />
              {translate("crm.dashboard.pipeline")}
            </CardTitle>
            <CardDescription>
              {translate("crm.dashboard.pipeline_desc")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[350px] w-full">
              {isLoadingLeads ? (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  <Activity className="w-8 h-8 animate-spin" />
                </div>
              ) : (
                <ResponsiveBar
                  data={funnelData}
                  keys={["count"]}
                  indexBy="stage"
                  margin={{ top: 20, right: 20, bottom: 50, left: 40 }}
                  padding={0.3}
                  valueScale={{ type: "linear" }}
                  indexScale={{ type: "band", round: true }}
                  colors={({ data }) => data.color}
                  theme={nivoTheme}
                  borderRadius={4}
                  borderColor={{ from: "color", modifiers: [["darker", 1.6]] }}
                  axisTop={null}
                  axisRight={null}
                  axisBottom={{
                    tickSize: 5,
                    tickPadding: 5,
                    tickRotation: -25,
                  }}
                  axisLeft={{
                    tickSize: 5,
                    tickPadding: 5,
                    tickRotation: 0,
                  }}
                  labelSkipWidth={12}
                  labelSkipHeight={12}
                  labelTextColor={isDark ? "#ffffff" : "#ffffff"}
                  role="application"
                  ariaLabel="Pipeline Funnel"
                  animate={true}
                  motionConfig="stiff"
                />
              )}
            </div>
          </CardContent>
        </Card>

        {/* Side Panel */}
        <Card className="shadow-sm border-border/50 hover:shadow-md transition-shadow duration-300 flex flex-col">
          <CardHeader>
            <CardTitle>{translate("crm.dashboard.system_activity")}</CardTitle>
            <CardDescription>{translate("crm.dashboard.snapshot")}</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col justify-center gap-8">
            <div className="flex items-center justify-between p-4 rounded-xl bg-secondary/50">
              <div className="space-y-1">
                <p className="text-sm font-medium leading-none">{translate("crm.dashboard.active_leads")}</p>
                <p className="text-2xl font-bold">{activeLeads}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                <Activity className="text-primary w-6 h-6" />
              </div>
            </div>

            <div className="flex items-center justify-between p-4 rounded-xl bg-secondary/50">
              <div className="space-y-1">
                <p className="text-sm font-medium leading-none">{translate("crm.dashboard.drop_off")}</p>
                <p className="text-2xl font-bold">
                  {totalLeads ? Math.round((rejectedLeads / totalLeads) * 100) : 0}%
                </p>
              </div>
              <div className="h-12 w-12 rounded-full bg-destructive/10 flex items-center justify-center">
                <TrendingUp className="text-destructive w-6 h-6 rotate-180" />
              </div>
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
  trendUp 
}: { 
  title: string; 
  value: string; 
  description: string; 
  icon: React.ReactNode; 
  trend?: string;
  trendUp?: boolean;
}) => (
  <Card className="shadow-sm border-border/50 hover:shadow-md transition-all duration-300 group overflow-hidden relative">
    {/* Decorative background gradient */}
    <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/50 to-primary opacity-0 group-hover:opacity-100 transition-opacity" />
    
    <CardHeader className="flex flex-row items-center justify-between pb-2">
      <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      <div className="p-2 bg-primary/10 text-primary rounded-lg">
        {icon}
      </div>
    </CardHeader>
    <CardContent>
      <div className="text-3xl font-bold tracking-tight">{value}</div>
      <div className="flex items-center mt-1 space-x-2">
        <p className="text-xs text-muted-foreground">{description}</p>
        {trend && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${trendUp ? 'bg-emerald-500/10 text-emerald-500' : 'bg-rose-500/10 text-rose-500'}`}>
            {trend}
          </span>
        )}
      </div>
    </CardContent>
  </Card>
);
