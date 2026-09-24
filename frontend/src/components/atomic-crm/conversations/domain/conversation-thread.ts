import type { ConversationMessage } from "./conversation-message";

const OPTIMISTIC_ID_PREFIX = "optimistic-";
const OPTIMISTIC_CONFIRM_WINDOW_MS = 5 * 60 * 1000;

export const isOptimisticMessageId = (messageId: string) =>
  messageId.startsWith(OPTIMISTIC_ID_PREFIX);

export const keepConversationMessages = (
  messages: ConversationMessage[],
  conversationId: string,
) => messages.filter((message) => message.conversation_id === conversationId);

const parseMessageTime = (message: ConversationMessage) => {
  const value = Date.parse(message.created_at);
  return Number.isFinite(value) ? value : null;
};

const isConfirmedHumanReply = (message: ConversationMessage) =>
  message.type === "outbound" &&
  Boolean(message.data?.recruiter_id) &&
  !isOptimisticMessageId(message.id);

export const findConfirmedOptimisticIds = ({
  confirmedMessages,
  pendingMessages,
}: {
  confirmedMessages: ConversationMessage[];
  pendingMessages: Iterable<ConversationMessage>;
}): string[] => {
  const pendingById = new Map(
    Array.from(pendingMessages, (message) => [message.id, message]),
  );
  if (pendingById.size === 0) return [];

  const matchedTempIds = new Set<string>();
  for (const confirmed of confirmedMessages.filter(isConfirmedHumanReply)) {
    const confirmedAt = parseMessageTime(confirmed);
    let bestMatch: { delta: number; id: string } | null = null;

    for (const [tempId, temp] of pendingById.entries()) {
      if (matchedTempIds.has(tempId)) continue;
      if (temp.content !== confirmed.content) continue;
      if (temp.type !== confirmed.type) continue;
      if (temp.data?.recruiter_id !== confirmed.data?.recruiter_id) continue;

      const tempAt = parseMessageTime(temp);
      const delta =
        confirmedAt != null && tempAt != null
          ? Math.abs(confirmedAt - tempAt)
          : 0;
      if (delta > OPTIMISTIC_CONFIRM_WINDOW_MS) continue;
      if (!bestMatch || delta < bestMatch.delta) {
        bestMatch = { delta, id: tempId };
      }
    }

    if (bestMatch) matchedTempIds.add(bestMatch.id);
  }

  return Array.from(matchedTempIds);
};

/**
 * Phase-02 unseen-content contract. The strong "Tin nhắn mới" emphasis applies
 * only to arrivals a reader can't anticipate: candidate inbound, bot replies,
 * and replies from *other* recruiters. The current recruiter's own optimistic
 * send (intent to go to latest), its server echo, system events, and history
 * prepends never qualify. Author/type is the discriminator — not id change.
 *
 * Consumed by ChatThread; exported for focused unit testing of the contract.
 */
export const isUnseenWorthyArrival = (
  message: ConversationMessage,
  currentRecruiterId: string | number | null | undefined,
): boolean => {
  if (isOptimisticMessageId(message.id)) return false;
  if (message.type === "system") return false;
  if (message.type === "inbound") return true;

  const authorId = message.data?.recruiter_id;
  if (!authorId) return true;
  if (currentRecruiterId == null) return true;
  return String(authorId) !== String(currentRecruiterId);
};
