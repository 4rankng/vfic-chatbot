export interface ReportingReadPort {
  getJson<T>(path: string): Promise<T>;
}
