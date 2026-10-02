import { useEffect, useLayoutEffect, useRef, useState } from "react";
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

type LocalModeState = {
  conversationId: string;
  mode: EditableConversationMode;
  claimed: boolean;
  version?: number;
  previousMode: ConversationMode;
  previousAssignee: string | null;
};

const conversationVersion = (value: unknown, conversationId: string) => {
  if (!value || typeof value !== "object") return undefined;
  const row = value as { id?: unknown; version?: unknown };
  if (
    row.id !== conversationId ||
    typeof row.version !== "number" ||
    !Number.isSafeInteger(row.version) ||
    row.version < 1
  ) {
    return undefined;
  }
  return row.version;
};

const hasAuthoritativeModeUpdate = (
  record: Conversation | undefined,
  local: LocalModeState,
) => {
  if (record?.id !== local.conversationId) return true;
  const version = conversationVersion(record, record.id);
  if (version !== undefined && local.version !== undefined) {
    return version >= local.version;
  }
  // Partial/custom records may omit version. Keep the accepted local mode
  // until the authoritative mode or assignment actually changes.
  return (
    record.mode !== local.previousMode ||
    record.assigned_recruiter_id !== local.previousAssignee
  );
};

/**
 * Shared takeover/release logic for a conversation record. Used by the
 * transcript header and the reusable thread's takeover affordance.
 *
 * An accepted action's version protects its local mode against stale refreshes.
 * Once the API/realtime record reaches that version, it owns mode and claim
 * state again. Writes are serialized and cannot complete into another thread.
 */
export const useConversationActions = (record?: Conversation) => {
  const modeWriter = useDataProvider<DataProvider & ConversationModeWriter>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [localState, setLocalState] = useState<LocalModeState>();
  const [pendingConversationId, setPendingConversationId] = useState<string>();
  const activeRecordRef = useRef(record);
  const pendingRequestRef = useRef<{ conversationId: string } | undefined>(
    undefined,
  );

  useLayoutEffect(() => {
    activeRecordRef.current = record;
    if (
      pendingRequestRef.current &&
      pendingRequestRef.current.conversationId !== record?.id
    ) {
      pendingRequestRef.current = undefined;
      setPendingConversationId(undefined);
    }
  }, [record]);

  useEffect(
    () => () => {
      pendingRequestRef.current = undefined;
      activeRecordRef.current = undefined;
    },
    [],
  );

  const hasAuthoritativeUpdate =
    localState && hasAuthoritativeModeUpdate(record, localState);
  const activeLocalState = hasAuthoritativeUpdate ? undefined : localState;

  useEffect(() => {
    if (hasAuthoritativeUpdate) setLocalState(undefined);
  }, [hasAuthoritativeUpdate]);

  const { effectiveMode, isBotMode, needsClaim, canHumanReply } =
    deriveConversationModeState({
      record,
      localMode: activeLocalState?.mode,
      locallyClaimed: activeLocalState?.claimed ?? false,
    });

  const setConversationMode = async (nextMode: EditableConversationMode) => {
    if (!record || pendingRequestRef.current) return;
    const request = { conversationId: record.id };
    pendingRequestRef.current = request;
    setPendingConversationId(record.id);
    let acceptedRecord: unknown;

    try {
      const result = await changeConversationMode({
        conversationId: record.id,
        currentMode: effectiveMode,
        needsClaim,
        nextMode,
        writer: {
          setConversationMode: async (id, mode) => {
            acceptedRecord = await modeWriter.setConversationMode(id, mode);
            return acceptedRecord;
          },
        },
      });
      if (
        pendingRequestRef.current !== request ||
        activeRecordRef.current?.id !== request.conversationId
      ) {
        return;
      }

      if (result.kind === "changed") {
        setLocalState({
          conversationId: record.id,
          mode: nextMode,
          claimed: nextMode === "human",
          version: conversationVersion(acceptedRecord, record.id),
          previousMode: record.mode,
          previousAssignee: record.assigned_recruiter_id,
        });
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
    } finally {
      if (pendingRequestRef.current === request) {
        pendingRequestRef.current = undefined;
        setPendingConversationId(undefined);
      }
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
    isChangingMode: pendingConversationId === record?.id && !!record,
    setConversationMode,
    handleTakeover,
    handleRelease,
  };
};
