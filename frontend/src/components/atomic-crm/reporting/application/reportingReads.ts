import type { ReportingReadPort } from "./ports";

export const createReportingReads = (port: ReportingReadPort) => ({
  getAttentionDashboard: <T>() => port.getAttentionDashboard<T>(),
  getDashboardCandidates: <T>() => port.getDashboardCandidates<T>(),
  getDashboardMetrics: <T>() => port.getDashboardMetrics<T>(),
  getPerformanceMetrics: <T>(window: string) =>
    port.getPerformanceMetrics<T>(window),
});
