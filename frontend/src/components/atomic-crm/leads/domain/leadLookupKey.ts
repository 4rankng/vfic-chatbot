/**
 * The key the conversation panel uses to fetch a thread's lead.
 *
 * zalo_id first: every Zalo/OA conversation keeps the exact request it always
 * made. A Messenger row has no zalo_chat_id at all, so the contact filter is
 * the only path to its lead — the regression that left Messenger candidates
 * showing no lead. Keys are taken individually rather than as a Conversation so
 * the caller's memo depends on primitives and stays identity-stable.
 */
export const leadFilterFor = (
  zaloChatId?: string | null,
  contactId?: string | null,
) => {
  if (zaloChatId) return { zalo_id: zaloChatId };
  if (contactId) return { contact_id: contactId };
  return {};
};
