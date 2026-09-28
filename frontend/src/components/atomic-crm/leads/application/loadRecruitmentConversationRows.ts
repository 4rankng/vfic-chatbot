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

export const mapLeadsByContactId = (leads: Lead[]) => {
  const leadByContact = new Map<string, Lead>();
  for (const lead of leads) {
    if (lead.contact_id && !leadByContact.has(lead.contact_id)) {
      leadByContact.set(lead.contact_id, lead);
    }
  }
  return leadByContact;
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
  // Messenger rows are contact-keyed (Alembic 0047) and carry a NULL
  // zalo_chat_id, so a zalo-only lookup could never resolve them: every such
  // row rendered as "Ứng viên · <PSID tail>" even after the lead had a name,
  // because the row never received a lead to read the name from.
  const contactIds = Array.from(
    new Set(
      conversations
        .map((conversation) => conversation.contact_id)
        .filter((value): value is string => Boolean(value)),
    ),
  );
  const [zaloLeads, contactLeads] = await Promise.all([
    zaloIds.length === 0 ? [] : port.listByZaloIds(zaloIds, signal),
    contactIds.length === 0 ? [] : port.listByContactIds(contactIds, signal),
  ]);
  const leadByZalo = mapLeadsByZaloId(zaloLeads);
  const leadByContact = mapLeadsByContactId(contactLeads);
  const presentations = new Map<string, RecruitmentConversationRow>();

  for (const conversation of conversations) {
    // contact_id is the canonical key, so it wins when both resolve; zalo_id
    // stays as the fallback for a lead that predates contact keying.
    const lead =
      (conversation.contact_id
        ? leadByContact.get(conversation.contact_id)
        : undefined) ??
      (conversation.zalo_chat_id
        ? leadByZalo.get(conversation.zalo_chat_id)
        : undefined);
    presentations.set(conversation.id, {
      lead,
      presentation: buildRecruitmentRowPresentation(conversation, lead),
    });
  }

  return presentations;
};
