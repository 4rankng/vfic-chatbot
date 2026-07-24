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
