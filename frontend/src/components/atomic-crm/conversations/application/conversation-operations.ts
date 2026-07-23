export type HumanReplyStatus =
  | "disabled"
  | "unauthorized"
  | "forbidden"
  | "conflict"
  | "unavailable"
  | "provider"
  | "network"
  | "error";

export type HumanReplyFailure = Error & {
  status: HumanReplyStatus;
  httpStatus?: number;
};

export const isHumanReplyFailure = (
  error: unknown,
): error is HumanReplyFailure =>
  error instanceof Error &&
  typeof (error as Partial<HumanReplyFailure>).status === "string";

export interface DeleteConversationPort {
  deleteConversation(conversationId: string): Promise<unknown>;
}

export interface MarkConversationReadPort {
  markAsRead(conversationId: string): Promise<unknown>;
}

export interface SendConversationReplyPort {
  sendHumanReply(conversationId: string, message: string): Promise<unknown>;
}

export interface RetryConversationReplyPort {
  retryHumanReply(conversationId: string, messageId: string): Promise<unknown>;
}

export const deleteConversation = (
  port: DeleteConversationPort,
  conversationId: string,
): Promise<unknown> => port.deleteConversation(conversationId);

export const markConversationAsRead = (
  port: MarkConversationReadPort,
  conversationId: string,
): Promise<unknown> => port.markAsRead(conversationId);

export const sendConversationReply = (
  port: SendConversationReplyPort,
  conversationId: string,
  message: string,
): Promise<unknown> => port.sendHumanReply(conversationId, message);

export const retryConversationReply = (
  port: RetryConversationReplyPort,
  conversationId: string,
  messageId: string,
): Promise<unknown> => port.retryHumanReply(conversationId, messageId);
