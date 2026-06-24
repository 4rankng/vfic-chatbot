import { useState } from "react";
import { useDataProvider, useNotify, useRefresh } from "ra-core";
import type { Conversation } from "../types";
import type { CrmDataProvider } from "../providers/supabase/dataProvider";

export type ConversationMode = Conversation["mode"];

/**
 * Shared takeover/release logic for a conversation record. Used by both the
 * transcript header (ConversationShowContent) and the lead-profile drawer
 * (LeadProfilePanel) so the two action surfaces stay behaviourally identical.
 *
 * Optimistic-then-refresh: after a successful RPC the local mode is updated for
 * snappy UX, and `useRefresh` re-fetches the record so the authoritative mode
 * converges across every consumer reading `record.mode`.
 */
export const useConversationActions = (record?: Conversation) => {
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [localMode, setLocalMode] = useState<ConversationMode | undefined>(
    undefined,
  );

  const effectiveMode: ConversationMode | undefined = localMode ?? record?.mode;
  const isBotMode = effectiveMode === "bot";

  const handleTakeover = async () => {
    if (!record) return;
    try {
      await dataProvider.takeOverConversation(record.id);
      setLocalMode("human");
      notify("conversations.takeover.success", { type: "success" });
      refresh();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "conversations.takeover.error", {
        type: "error",
      });
    }
  };

  const handleRelease = async () => {
    if (!record) return;
    try {
      await dataProvider.releaseConversation(record.id);
      setLocalMode("bot");
      notify("conversations.release.success", { type: "success" });
      refresh();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "conversations.release.error", {
        type: "error",
      });
    }
  };

  return { effectiveMode, isBotMode, handleTakeover, handleRelease };
};
