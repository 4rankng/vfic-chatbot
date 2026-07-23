import { apiJson } from "../../providers/rest/api";

export const reportingApi = {
  getJson<T>(path: string) {
    return apiJson<T>(path);
  },
};
