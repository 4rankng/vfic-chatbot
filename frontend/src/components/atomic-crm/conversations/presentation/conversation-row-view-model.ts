import type { ConversationRowPresentation } from "../../capabilities/types";
import type { Conversation } from "../../types";
import { getGenericConversationPresentation } from "../conversation-capability";

/**
 * Everything an inbox row renders beyond the conversation record itself.
 *
 * `ConversationListItem` is memoized, so a view-model object must keep its
 * identity while the inputs it was derived from are unchanged. Building a fresh
 * `{...conversation, _presentation, _snippet}` per conversation on every list
 * render changed the identity of every row prop, which defeated the memo on
 * each deferred search keystroke, every optimistic read and every refetch.
 */
export type ConversationRowViewModel = {
  presentation: ConversationRowPresentation;
  snippet: string;
};

export type ConversationRowViewModelCacheEntry = {
  /** Adapter-provided presentation, or `null` when the generic fallback is used. */
  presentationSource: ConversationRowPresentation | null;
  /** Conversation the generic fallback presentation was derived from. */
  conversation: Conversation;
  /** Key the snippet was looked up with (`zalo_chat_id ?? id`). */
  snippetKey: string;
  viewModel: ConversationRowViewModel;
};

export type ConversationRowViewModelCache = Map<
  string,
  ConversationRowViewModelCacheEntry
>;

/**
 * Resolve the view-model for one conversation, reusing the previously built
 * object whenever every input it was derived from is unchanged: the adapter
 * presentation object (or, for the generic fallback, the conversation object it
 * is derived from), the snippet lookup key and the snippet value.
 *
 * Read state is deliberately NOT an input — it reaches the row as its own
 * `isRead` boolean — so marking one row read cannot invalidate the others.
 */
export const resolveConversationRowViewModel = (
  cache: ConversationRowViewModelCache,
  conversation: Conversation,
  adapterPresentation: ConversationRowPresentation | undefined,
  snippets: Record<string, string>,
): ConversationRowViewModel => {
  const presentationSource = adapterPresentation ?? null;
  const snippetKey = conversation.zalo_chat_id ?? conversation.id;
  const snippet = snippets[snippetKey] ?? "";
  const cached = cache.get(conversation.id);
  if (
    cached &&
    cached.presentationSource === presentationSource &&
    cached.snippetKey === snippetKey &&
    cached.viewModel.snippet === snippet &&
    // An adapter presentation does not depend on the conversation record, so a
    // refetched (but equivalent) record can keep the same view-model. The
    // generic fallback is derived from the record, so it needs the same object.
    (presentationSource !== null || cached.conversation === conversation)
  ) {
    return cached.viewModel;
  }

  const viewModel: ConversationRowViewModel = {
    presentation:
      presentationSource ?? getGenericConversationPresentation(conversation),
    snippet,
  };
  cache.set(conversation.id, {
    presentationSource,
    conversation,
    snippetKey,
    viewModel,
  });
  return viewModel;
};

/**
 * Drop view-models for conversations that left the list (deleted rows, changed
 * server filters) so the per-id cache cannot grow without bound.
 */
export const pruneConversationRowViewModelCache = (
  cache: ConversationRowViewModelCache,
  conversations: readonly Conversation[] | undefined,
) => {
  if (!conversations || conversations.length === 0) {
    cache.clear();
    return;
  }
  const liveIds = new Set(conversations.map((conversation) => conversation.id));
  for (const id of cache.keys()) {
    if (!liveIds.has(id)) cache.delete(id);
  }
};
