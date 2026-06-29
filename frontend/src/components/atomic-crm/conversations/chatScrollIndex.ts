export const INITIAL_CHAT_FIRST_ITEM_INDEX = 100_000;

export const firstItemIndexAfterPrepend = (
  currentFirstItemIndex: number,
  prependedCount: number,
) => Math.max(0, currentFirstItemIndex - Math.max(0, prependedCount));
