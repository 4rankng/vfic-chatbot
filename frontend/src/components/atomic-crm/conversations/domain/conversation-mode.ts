export type ConversationMode = "bot" | "human" | "semi_auto" | "closed";
export type EditableConversationMode = Extract<
  ConversationMode,
  "bot" | "human" | "semi_auto"
>;

export type ConversationModeRecord = {
  mode: ConversationMode;
  assigned_recruiter_id: string | null;
};

export type ConversationModeState = {
  effectiveMode: ConversationMode | undefined;
  isBotMode: boolean;
  needsClaim: boolean;
  canHumanReply: boolean;
};

export const deriveConversationModeState = ({
  localMode,
  locallyClaimed,
  record,
}: {
  record?: ConversationModeRecord;
  localMode?: ConversationMode;
  locallyClaimed: boolean;
}): ConversationModeState => {
  const effectiveMode: ConversationMode | undefined = localMode ?? record?.mode;
  const isBotMode = effectiveMode === "bot";
  const needsClaim =
    effectiveMode === "human" &&
    !record?.assigned_recruiter_id &&
    !locallyClaimed;
  const canHumanReply =
    (effectiveMode === "human" && !needsClaim) || effectiveMode === "semi_auto";

  return {
    effectiveMode,
    isBotMode,
    needsClaim,
    canHumanReply,
  };
};
