import type {
  ConversationMode,
  EditableConversationMode,
} from "../domain/conversation-mode";

export type ConversationModeWriter = {
  setConversationMode: (
    conversationId: string,
    mode: EditableConversationMode,
  ) => Promise<unknown>;
};

export type ChangeConversationModeResult =
  | { kind: "unchanged" }
  | { kind: "changed"; mode: EditableConversationMode }
  | { kind: "failed"; mode: EditableConversationMode };

/**
 * Changes a conversation's reply mode through its supplied persistence port.
 * Presentation concerns such as optimistic state, notifications, and cache
 * refresh remain with the caller.
 */
export const changeConversationMode = async ({
  conversationId,
  currentMode,
  needsClaim,
  nextMode,
  writer,
}: {
  conversationId?: string;
  currentMode: ConversationMode | undefined;
  needsClaim: boolean;
  nextMode: EditableConversationMode;
  writer: ConversationModeWriter;
}): Promise<ChangeConversationModeResult> => {
  if (
    !conversationId ||
    (currentMode === nextMode && !(nextMode === "human" && needsClaim))
  ) {
    return { kind: "unchanged" };
  }

  try {
    await writer.setConversationMode(conversationId, nextMode);
    return { kind: "changed", mode: nextMode };
  } catch {
    return { kind: "failed", mode: nextMode };
  }
};
