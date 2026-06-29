import type { Message } from "../types";

export const compareMessages = (a: Message, b: Message) => {
  const at = Date.parse(a.created_at);
  const bt = Date.parse(b.created_at);
  if (Number.isFinite(at) && Number.isFinite(bt) && at !== bt) return at - bt;
  const aid = Number(a.id);
  const bid = Number(b.id);
  if (Number.isFinite(aid) && Number.isFinite(bid) && aid !== bid)
    return aid - bid;
  return String(a.id).localeCompare(String(b.id));
};

export const sortMessagesChronologically = (messages: Message[]) => {
  if (messages.length < 2) return messages;
  for (let i = 1; i < messages.length; i += 1) {
    if (compareMessages(messages[i - 1], messages[i]) > 0) {
      return [...messages].sort(compareMessages);
    }
  }
  return messages;
};

export const sameMessage = (a: Message, b: Message) =>
  a.id === b.id &&
  a.content === b.content &&
  a.type === b.type &&
  a.created_at === b.created_at &&
  a.data?.recruiter_id === b.data?.recruiter_id;

export const mergeChronological = (current: Message[], incoming: Message[]) => {
  const byId = new Map<string, Message>();
  for (const msg of current) byId.set(msg.id, msg);
  for (const msg of incoming) {
    const existing = byId.get(msg.id);
    byId.set(msg.id, existing && sameMessage(existing, msg) ? existing : msg);
  }
  const merged = Array.from(byId.values()).sort(compareMessages);
  if (
    merged.length === current.length &&
    merged.every((msg, index) => msg === current[index])
  ) {
    return current;
  }
  return merged;
};

export const mergeRealtimePage = (
  current: Message[],
  latestPage: Message[],
) => {
  if (current.length === 0) return sortMessagesChronologically(latestPage);
  const earliestLoaded = current[0];
  const inLoadedWindow = latestPage.filter(
    (msg) => compareMessages(msg, earliestLoaded) >= 0,
  );
  return mergeChronological(current, inLoadedWindow);
};
