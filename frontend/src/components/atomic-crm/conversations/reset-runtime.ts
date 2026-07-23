import {
  bindConversationApplication,
  getConversationMessageState,
} from "./application/conversation-runtime";
import { chatRepository } from "./infrastructure/chat-repository";
import { conversationMessageStatePort } from "./infrastructure/message-store";
import { bindConversationRuntimeEpoch } from "./infrastructure/runtime-epoch-adapter";

export { bindConversationRuntimeEpoch };

bindConversationApplication({
  messageRepository: chatRepository,
  messageStatePort: conversationMessageStatePort,
});

export const resetConversationRuntimeState = (): void => {
  getConversationMessageState().getState().resetAll();
};
