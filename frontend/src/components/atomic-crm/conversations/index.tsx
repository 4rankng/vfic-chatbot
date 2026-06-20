import { ConversationList } from "./ConversationList";
import { ConversationShow } from "./ConversationShow";
import type { Conversation } from "../types";

export default {
  list: ConversationList,
  show: ConversationShow,
  recordRepresentation: (record: Conversation) => record?.zalo_chat_id,
};
