import { random } from "faker/locale/en_US";

import type { Conversation, Lead } from "../../../types";
import type { Db } from "./types";
import { randomDate } from "./utils";

export const generateConversations = (
  db: Db,
  size = 500,
): Conversation[] => {
  const leads = db.leads ?? [];
  const conversations: Conversation[] = [];

  for (let i = 0; i < size; i++) {
    const linkedLead: Lead | undefined = leads[i % Math.max(leads.length, 1)];
    const lastInboundAt = randomDate(
      new Date(Date.now() - 1000 * 60 * 60 * 24 * 30),
      new Date(),
    );
    const createdAt = randomDate(
      new Date(Date.now() - 1000 * 60 * 60 * 24 * 90),
      new Date(lastInboundAt),
    );

    conversations.push({
      id: `conv-${i + 1}`,
      zalo_chat_id: linkedLead?.zalo_id ?? `zalo-${random.number({ min: 100000, max: 999999 })}`,
      mode: random.arrayElement(["bot", "human"]) as "bot" | "human",
      last_inbound_at: lastInboundAt.toISOString(),
      assigned_recruiter_id: null,
      created_at: createdAt.toISOString(),
      updated_at: lastInboundAt.toISOString(),
    });
  }

  return conversations;
};