import type { Meta } from "@storybook/react-vite";

import { ConversationShowContent } from "./ConversationShow";

import { StoryWrapper, buildConversation } from "@/test/StoryWrapper";

const meta = {
  title: "Atomic CRM/Conversations/Conversation Show/Mobile",
  parameters: {
    layout: "fullscreen",
  },
  globals: {
    viewport: { value: "mobile1", isRotated: false },
  },
} satisfies Meta;

export default meta;

const successConversations = [
  buildConversation({
    id: "conv-1",
    zalo_chat_id: "zalo-12345",
    mode: "human",
    assigned_recruiter_id: "user-1",
  }),
];

export const MobileSuccess = () => (
  <StoryWrapper data={{ conversations: successConversations }}>
    <ConversationShowContent />
  </StoryWrapper>
);
