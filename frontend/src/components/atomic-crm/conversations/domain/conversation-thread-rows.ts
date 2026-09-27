// Grouping rules for the conversation thread's message rows.
//
// Pure: no React, no IO. The thread flattens the stored message array into
// rows and renders one memoized bubble per row, so this module is the single
// place that decides which bubble variant a message gets and whether it
// continues the run above it.

import type { ConversationMessage } from "./conversation-message";

/** Bubble variant (and side of the thread) one message renders as. */
export type ConversationMessageKind =
  | "user"
  | "bot"
  | "agent"
  | "system"
  | "event";

export type ConversationMessageRow = {
  message: ConversationMessage;
  kind: ConversationMessageKind;
  /** Continues the run of same-kind messages directly above it. */
  isGrouped: boolean;
};

/**
 * An inbound message is the candidate ("user"), an outbound message authored by
 * a recruiter is that recruiter ("agent"), any other outbound message is the
 * bot, and a system message takes its own full-width rail.
 */
export const classifyConversationMessage = (
  message: ConversationMessage,
): ConversationMessageKind => {
  if (message.type === "system") return "system";
  if (message.type === "inbound") return "user";
  if (message.data?.recruiter_id) return "agent";
  return "bot";
};

/**
 * Flatten messages into renderable rows, flagging the rows that continue the
 * run of same-kind messages above them — a grouped row drops its avatar and
 * reads as part of the previous turn.
 *
 * Grouping is positional, not temporal: the thread is one continuous scroller,
 * so a run that crosses midnight stays a single run, and any change of kind —
 * including one in the middle of a run — starts a new one.
 */
export const groupConversationMessages = (
  messages: readonly ConversationMessage[],
): ConversationMessageRow[] => {
  const rows: ConversationMessageRow[] = [];
  let previousKind: ConversationMessageKind | null = null;
  for (const message of messages) {
    const kind = classifyConversationMessage(message);
    rows.push({ message, kind, isGrouped: previousKind === kind });
    previousKind = kind;
  }
  return rows;
};
