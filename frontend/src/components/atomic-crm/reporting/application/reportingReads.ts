import type { ReportingReadPort } from "./ports";

export const createReportingReads = (port: ReportingReadPort) => ({
  getJson<T>(path: string) {
    return port.getJson<T>(path);
  },
});
