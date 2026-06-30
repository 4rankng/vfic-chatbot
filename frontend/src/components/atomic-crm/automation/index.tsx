import { lazy } from "react";
import type { BotRun } from "../types";

const BotRunList = lazy(() =>
  import("./BotRunList").then((m) => ({ default: m.BotRunList })),
);
const BotRunShow = lazy(() =>
  import("./BotRunShow").then((m) => ({ default: m.BotRunShow })),
);

// Read-only ops resource over the `bot_runs` table (takeover race-guard audit
// trail). Both roles can view; writes are bot-side only.
export default {
  list: BotRunList,
  show: BotRunShow,
  recordRepresentation: (record?: BotRun) => `Run #${record?.id ?? "?"}`,
};
