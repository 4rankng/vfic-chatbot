import { useEffect, useState } from "react";
import {
  type DataProvider,
  useDataProvider,
  useNotify,
  useRefresh,
} from "ra-core";
import type { Conversation } from "../../types";
import {
  changeConversationMode,
  type ConversationModeWriter,
} from "../application/conversation-actions";
import {
  deriveConversationModeState,
  type ConversationMode,
  type EditableConversationMode,
} from "../domain/conversation-mode";

export type { ConversationMode } from "../domain/conversation-mode";

/**
 * Shared takeover/release logic for a conversation record. Used by the
 * transcript header so mode changes stay optimistic and refresh cleanly.
 *
 * Optimistic-then-refresh: after a successful RPC the local mode is updated for
 * snappy UX, and `useRefresh` re-fetches the record so the authoritative mode
 * converges across every consumer reading `record.mode`.
 */
export const useConversationActions = (record?: Conversation) => {
  const modeWriter = useDataProvider<DataProvider & ConversationModeWriter>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [localMode, setLocalMode] = useState<ConversationMode | undefined>(
    undefined,
  );
  const [locallyClaimed, setLocallyClaimed] = useState(false);

  useEffect(() => {
    setLocalMode(undefined);
  }, [record?.id]);

  useEffect(() => {
    setLocallyClaimed(false);
  }, [record?.id, record?.assigned_recruiter_id]);

  const { effectiveMode, isBotMode, needsClaim, canHumanReply } =
    deriveConversationModeState({
      record,
      localMode,
      locallyClaimed,
    });

  const setConversationMode = async (nextMode: EditableConversationMode) => {
    const result = await changeConversationMode({
      conversationId: record?.id,
      currentMode: effectiveMode,
      needsClaim,
      nextMode,
      writer: modeWriter,
    });

    if (result.kind === "changed") {
      setLocalMode(nextMode);
      setLocallyClaimed(nextMode === "human");
      const key =
        nextMode === "human"
          ? "conversations.takeover.success"
          : nextMode === "semi_auto"
            ? "conversations.semi_auto.success"
            : "conversations.release.success";
      notify(key, { type: "success" });
      refresh();
    } else if (result.kind === "failed") {
      const errorKey =
        nextMode === "human"
          ? "conversations.takeover.error"
          : nextMode === "semi_auto"
            ? "conversations.semi_auto.error"
            : "conversations.release.error";
      notify(errorKey, { type: "error" });
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
    needsClaim,
    canHumanReply,
    setConversationMode,
    handleTakeover,
    handleRelease,
  };
};
