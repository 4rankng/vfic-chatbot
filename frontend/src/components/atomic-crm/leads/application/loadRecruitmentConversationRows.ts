import type { Conversation, Lead } from "../../types";
import { buildRecruitmentRowPresentation } from "../domain/recruitmentPresentation";
import type { CancellationSignal, LeadDirectoryPort } from "./ports";

export type RecruitmentConversationRow = {
  lead?: Lead;
  presentation: ReturnType<typeof buildRecruitmentRowPresentation>;
};

export const mapLeadsByZaloId = (leads: Lead[]) => {
  const leadByZalo = new Map<string, Lead>();
  for (const lead of leads) {
    if (lead.zalo_id && !leadByZalo.has(lead.zalo_id)) {
      leadByZalo.set(lead.zalo_id, lead);
    }
  }
  return leadByZalo;
};

export const loadRecruitmentConversationRows = async (
  conversations: Conversation[],
  port: LeadDirectoryPort,
  signal?: CancellationSignal,
) => {
  const zaloIds = Array.from(
    new Set(
      conversations
        .map((conversation) => conversation.zalo_chat_id)
        .filter((value): value is string => Boolean(value)),
    ),
  );
  // A Messenger conversation carries no zalo_chat_id and therefore no lead to
  // batch-fetch, but it still has a channel profile to present. Skip the fetch,
  // never the presentation — otherwise the row renders nameless and with a
  // placeholder avatar.
  const leadByZalo =
    zaloIds.length === 0
      ? new Map<string, Lead>()
      : mapLeadsByZaloId(await port.listByZaloIds(zaloIds, signal));
  const presentations = new Map<string, RecruitmentConversationRow>();

  for (const conversation of conversations) {
    const chatKey = conversation.zalo_chat_id ?? conversation.id;
    const lead = leadByZalo.get(chatKey);
    presentations.set(conversation.id, {
      lead,
      presentation: buildRecruitmentRowPresentation(conversation, lead),
    });
  }

  return presentations;
};
