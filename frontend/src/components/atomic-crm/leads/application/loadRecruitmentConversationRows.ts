import type { Conversation, Lead } from "../../types";
import { buildRecruitmentRowPresentation } from "../domain/recruitmentPresentation";
import type { LeadDirectoryPort } from "./ports";

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
  signal?: AbortSignal,
) => {
  const zaloIds = Array.from(
    new Set(
      conversations
        .map((conversation) => conversation.zalo_chat_id)
        .filter((value): value is string => Boolean(value)),
    ),
  );
  if (zaloIds.length === 0) return new Map();

  const leadByZalo = mapLeadsByZaloId(
    await port.listByZaloIds(zaloIds, signal),
  );
  const presentations = new Map<string, RecruitmentConversationRow>();

  for (const conversation of conversations) {
    const chatKey = conversation.zalo_chat_id ?? conversation.id;
    const lead = leadByZalo.get(chatKey);
    presentations.set(
      conversation.id,
      {
        lead,
        presentation: buildRecruitmentRowPresentation(conversation, lead),
      },
    );
  }

  return presentations;
};
