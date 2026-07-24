import { createReportingReads } from "./application/reportingReads";
import { reportingApi } from "./infrastructure/reportingApi";

export const {
  getAttentionDashboard,
  getDashboardCandidates,
  getDashboardConversations,
  getDashboardMetrics,
  getPerformanceMetrics,
} = createReportingReads(reportingApi);
