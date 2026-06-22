import type { BotRun } from "../types";
import { BotRunList } from "./BotRunList";
import { BotRunShow } from "./BotRunShow";

// Read-only ops resource over the `bot_runs` table (takeover race-guard audit
// trail). Both roles can view; writes are bot-side only.
export default {
  list: BotRunList,
  show: BotRunShow,
  recordRepresentation: (record?: BotRun) => `Run #${record?.id ?? "?"}`,
};
