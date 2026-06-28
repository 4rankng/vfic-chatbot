import { useState } from "react";
import { useDataProvider, useNotify, useRefresh } from "ra-core";
import type { Conversation } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";

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
  const canHumanReply =
    effectiveMode === "human" || effectiveMode === "semi_auto";

  const setConversationMode = async (
    nextMode: Extract<ConversationMode, "bot" | "human" | "semi_auto">,
  ) => {
    if (!record || effectiveMode === nextMode) return;
    try {
      await dataProvider.setConversationMode(record.id, nextMode);
      setLocalMode(nextMode);
      const key =
        nextMode === "human"
          ? "conversations.takeover.success"
          : nextMode === "semi_auto"
            ? "Đã bật chế độ bán tự động"
            : "conversations.release.success";
      notify(key, { type: "success" });
      refresh();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "Không thể đổi chế độ hội thoại", {
        type: "error",
      });
    }
  };

  const handleTakeover = async () => {
    await setConversationMode("human");
  };

  const handleRelease = async () => {
    await setConversationMode("bot");
  };

  return {
    effectiveMode,
    isBotMode,
    canHumanReply,
    setConversationMode,
    handleTakeover,
    handleRelease,
  };
};
