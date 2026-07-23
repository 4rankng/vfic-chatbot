import { createReportingReads } from "./application/reportingReads";
import { reportingApi } from "./infrastructure/reportingApi";

export const { getJson: getReportingJson } = createReportingReads(reportingApi);
