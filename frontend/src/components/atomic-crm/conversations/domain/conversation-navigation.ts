export const conversationSelectionParams = (
  current: URLSearchParams,
  conversationId: string | null,
): URLSearchParams => {
  const next = new URLSearchParams(current);
  if (conversationId) {
    next.set("id", conversationId);
  } else {
    next.delete("id");
  }
  next.delete("panel");
  return next;
};

export const findSelectedConversation = <Conversation extends { id: string }>(
  conversations: readonly Conversation[] | undefined,
  selectedId: string | null,
  deepLinkedConversation?: Conversation,
): Conversation | null => {
  if (!selectedId) return null;
  return (
    conversations?.find((conversation) => conversation.id === selectedId) ??
    (deepLinkedConversation?.id === selectedId ? deepLinkedConversation : null)
  );
};
