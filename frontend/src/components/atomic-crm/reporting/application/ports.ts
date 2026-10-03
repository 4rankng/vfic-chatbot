export interface ReportingReadPort {
  getAttentionDashboard<T>(): Promise<T>;
  getDashboardCandidates<T>(): Promise<T>;
  getDashboardConversations<T>(zaloIds: string[]): Promise<T>;
  getDashboardConversationsByContactIds<T>(contactIds: string[]): Promise<T>;
  getDashboardMetrics<T>(): Promise<T>;
  getPerformanceMetrics<T>(window: string): Promise<T>;
}
