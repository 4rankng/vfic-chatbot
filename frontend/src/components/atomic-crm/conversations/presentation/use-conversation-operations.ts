// The conversation writes the thread performs, bound to the react-admin data
// provider in one place.
//
// The port itself is declared by the application layer
// (`application/conversation-operations`); the REST data provider implements
// it. Thread presentation depends on this narrow port instead of the
// react-admin `DataProvider` surface, so the data-access edge into
// `providers/rest` stays behind the application layer.

import { type DataProvider, useDataProvider } from "ra-core";

import type {
  MarkConversationReadPort,
  RetryConversationReplyPort,
  SendConversationReplyPort,
} from "../application/conversation-operations";

/** Clear unread on open, send a human reply, retry a failed send. */
export type ConversationOperationsPort = MarkConversationReadPort &
  SendConversationReplyPort &
  RetryConversationReplyPort;

export const useConversationOperations = (): ConversationOperationsPort =>
  useDataProvider<DataProvider & ConversationOperationsPort>();
