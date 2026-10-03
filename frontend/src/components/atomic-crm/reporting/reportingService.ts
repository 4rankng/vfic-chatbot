import { createReportingReads } from "./application/reportingReads";
import { reportingApi } from "./infrastructure/reportingApi";

export const {
  getAttentionDashboard,
  getDashboardCandidates,
  getDashboardConversations,
  getDashboardConversationsByContactIds,
  getDashboardMetrics,
  getPerformanceMetrics,
} = createReportingReads(reportingApi);
