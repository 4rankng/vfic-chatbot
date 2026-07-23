import { createReportingReads } from "./application/reportingReads";
import { reportingApi } from "./infrastructure/reportingApi";

export const {
  getAttentionDashboard,
  getDashboardCandidates,
  getDashboardMetrics,
  getPerformanceMetrics,
} = createReportingReads(reportingApi);
