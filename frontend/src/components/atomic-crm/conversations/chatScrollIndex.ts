import type { Message } from "../types";

export const INITIAL_CHAT_FIRST_ITEM_INDEX = 100_000;
const ESTIMATED_CHAT_CHARS_PER_LINE = 44;
const CHAT_LINE_HEIGHT_PX = 20;
const CHAT_MESSAGE_VERTICAL_CHROME_PX = 30;
const CHAT_SYSTEM_VERTICAL_CHROME_PX = 24;
const CHAT_MIN_MESSAGE_ROW_HEIGHT_PX = 48;
const CHAT_MIN_SYSTEM_ROW_HEIGHT_PX = 40;
const CHAT_MAX_ESTIMATED_ROW_HEIGHT_PX = 720;

export const firstItemIndexAfterPrepend = (
  currentFirstItemIndex: number,
  prependedCount: number,
) => Math.max(0, currentFirstItemIndex - Math.max(0, prependedCount));

export type MessageHeightCache = Map<string, number>;

export const measuredOrEstimatedMessageRowHeight = (
  message: Pick<Message, "id" | "content" | "type">,
  measuredHeights: MessageHeightCache,
) =>
  measuredHeights.get(String(message.id)) ?? estimateMessageRowHeight(message);

const estimateWrappedLineCount = (content: string) => {
  const normalized = content.replace(/\t/g, "    ").trim();
  if (!normalized) return 1;

  return normalized.split(/\r?\n/).reduce((lineCount, rawLine) => {
    const line = rawLine.replace(/\s+/g, " ").trim();
    if (!line) return lineCount + 1;
    return lineCount + Math.ceil(line.length / ESTIMATED_CHAT_CHARS_PER_LINE);
  }, 0);
};

export const estimateMessageRowHeight = (
  message: Pick<Message, "content" | "type">,
) => {
  const lineCount = estimateWrappedLineCount(message.content ?? "");
  const isSystem = message.type === "system";
  const minHeight = isSystem
    ? CHAT_MIN_SYSTEM_ROW_HEIGHT_PX
    : CHAT_MIN_MESSAGE_ROW_HEIGHT_PX;
  const chromeHeight = isSystem
    ? CHAT_SYSTEM_VERTICAL_CHROME_PX
    : CHAT_MESSAGE_VERTICAL_CHROME_PX;

  return Math.min(
    CHAT_MAX_ESTIMATED_ROW_HEIGHT_PX,
    Math.max(minHeight, lineCount * CHAT_LINE_HEIGHT_PX + chromeHeight),
  );
};
