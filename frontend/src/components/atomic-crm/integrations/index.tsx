import { lazy } from "react";
import { KeyRound } from "lucide-react";

const ZaloIntegrationPage = lazy(() =>
  import("./ZaloIntegrationPage").then((m) => ({ default: m.ZaloIntegrationPage })),
);

export default {
  list: ZaloIntegrationPage,
  icon: KeyRound,
};
