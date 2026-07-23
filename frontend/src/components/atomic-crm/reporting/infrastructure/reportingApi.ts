import { apiJson } from "../../providers/rest/api";
import type { ReportingReadPort } from "../application/ports";

export const reportingApi: ReportingReadPort = {
  getAttentionDashboard: <T>() =>
    apiJson<T>("/api/v1/dashboard/attention"),
  getDashboardCandidates: <T>() =>
    apiJson<T>(
      "/api/v1/leads?page=1&per_page=200&sort=created_at&order=DESC",
    ),
  getDashboardMetrics: <T>() =>
    apiJson<T>("/api/v1/dashboard/metrics"),
  getPerformanceMetrics: <T>(window: string) =>
    apiJson<T>(
      `/api/v1/admin/performance?window=${encodeURIComponent(window)}`,
    ),
};
