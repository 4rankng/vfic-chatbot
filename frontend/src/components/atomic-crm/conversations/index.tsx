import { lazy } from "react";
import type { Conversation } from "../types";

const ConversationList = lazy(() =>
  import("./presentation/conversation-list").then((m) => ({
    default: m.ConversationList,
  })),
);
const ConversationShow = lazy(() =>
  import("./presentation/ConversationShow").then((m) => ({
    default: m.ConversationShow,
  })),
);

export default {
  list: ConversationList,
  show: ConversationShow,
  recordRepresentation: (record: Conversation) =>
    record?.zalo_chat_id ?? record?.id ?? "Hội thoại",
};
