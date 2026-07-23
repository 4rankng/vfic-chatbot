export interface ReportingReadPort {
  getAttentionDashboard<T>(): Promise<T>;
  getDashboardCandidates<T>(): Promise<T>;
  getDashboardMetrics<T>(): Promise<T>;
  getPerformanceMetrics<T>(window: string): Promise<T>;
}
