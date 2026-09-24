import type { ReactNode } from "react";

import type {
  ConversationContextAdapterProps,
  ConversationContextValue,
} from "../capabilities/types";
import type { Conversation } from "../types";
import { getGenericConversationContext } from "./presentation/conversation-presentation";
import { useConversationCapabilitySlots } from "./useConversationCapabilitySlots";

export const GenericConversationContextAdapter = ({
  conversation,
  children,
}: ConversationContextAdapterProps) => (
  <>{children(getGenericConversationContext(conversation))}</>
);

export const ConversationContextAdapter = ({
  children,
  conversation,
}: {
  children: (value: ConversationContextValue) => ReactNode;
  conversation: Conversation | undefined;
}) => {
  const ContextAdapter =
    useConversationCapabilitySlots().context ??
    GenericConversationContextAdapter;
  return (
    <ContextAdapter conversation={conversation}>{children}</ContextAdapter>
  );
};
