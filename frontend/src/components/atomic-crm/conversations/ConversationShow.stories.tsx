import type { Meta } from "@storybook/react-vite";

import { ConversationShowContent } from "./ConversationShow";

import { StoryWrapper, buildConversation } from "@/test/StoryWrapper";

const meta = {
  title: "Atomic CRM/Conversations/Conversation Show",
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta;

export default meta;

const successConversations = [
  buildConversation({
    id: "conv-1",
    zalo_chat_id: "zalo-12345",
    mode: "bot",
    assigned_recruiter_id: null,
  }),
];

export const DesktopSuccess = () => (
  <StoryWrapper data={{ conversations: successConversations }}>
    <ConversationShowContent />
  </StoryWrapper>
);
