// FE-05 — identity contract of the inbox row view-model cache.
//
// `ConversationListItem` is memoized, so the view-model object handed to a row
// must keep its identity while every input it was derived from is unchanged.
// These tests pin that contract directly, including the snippet case: the list
// replaces the whole snippet map on every fetch, so unchanged rows must keep
// their view-model (and therefore skip re-rendering).

import { describe, expect, it } from "vitest";

import type { ConversationRowPresentation } from "../../capabilities/types";
import type { Conversation } from "../../types";
import {
  pruneConversationRowViewModelCache,
  resolveConversationRowViewModel,
  type ConversationRowViewModelCache,
} from "./conversation-row-view-model";

const conversation = (patch: Partial<Conversation> = {}): Conversation => ({
  id: "conv-1",
  zalo_chat_id: "zalo-1",
  mode: "human",
  needs_human: false,
  assigned_recruiter_id: null,
  last_inbound_at: "2026-09-01T00:00:00.000Z",
  last_outbound_at: null,
  created_at: "2026-09-01T00:00:00.000Z",
  updated_at: "2026-09-01T00:00:00.000Z",
  unread_count: 0,
  contact: {
    id: "contact-1",
    display_name: "Ứng viên Một",
    primary_phone: "0901234567",
    primary_email: null,
    avatar_url: null,
  },
  channel_identity: null,
  ...patch,
});

const presentation = (displayName: string): ConversationRowPresentation => ({
  displayName,
  subtitle: "0901234567",
  searchText: displayName,
});

describe("resolveConversationRowViewModel", () => {
  it("reuses the view-model while the row's own inputs are unchanged", () => {
    const cache: ConversationRowViewModelCache = new Map();
    const row = conversation();

    const first = resolveConversationRowViewModel(cache, row, undefined, {});
    const second = resolveConversationRowViewModel(cache, row, undefined, {});

    expect(second).toBe(first);
  });

  it("keeps unchanged rows when the snippet map is replaced wholesale", () => {
    const cache: ConversationRowViewModelCache = new Map();
    const row = conversation();

    const first = resolveConversationRowViewModel(cache, row, undefined, {
      "zalo-1": "tin nhắn cũ",
    });
    const refetched = resolveConversationRowViewModel(cache, row, undefined, {
      "zalo-1": "tin nhắn cũ",
    });
    expect(refetched).toBe(first);

    const changed = resolveConversationRowViewModel(cache, row, undefined, {
      "zalo-1": "tin nhắn mới",
    });
    expect(changed).not.toBe(first);
    expect(changed.snippet).toBe("tin nhắn mới");
  });

  it("reuses the row while the adapter presentation object is unchanged", () => {
    const cache: ConversationRowViewModelCache = new Map();
    const row = conversation();
    const adapterPresentation = presentation("Ứng viên từ adapter");

    const first = resolveConversationRowViewModel(
      cache,
      row,
      adapterPresentation,
      {},
    );
    const second = resolveConversationRowViewModel(
      cache,
      row,
      adapterPresentation,
      {},
    );

    expect(second).toBe(first);
    expect(second.presentation).toBe(adapterPresentation);
  });

  it("serves a replaced adapter presentation instead of the cached one", () => {
    const cache: ConversationRowViewModelCache = new Map();
    const row = conversation();

    resolveConversationRowViewModel(
      cache,
      row,
      presentation("Ứng viên cũ"),
      {},
    );
    const updated = resolveConversationRowViewModel(
      cache,
      row,
      presentation("Ứng viên mới"),
      {},
    );

    expect(updated.presentation.displayName).toBe("Ứng viên mới");
  });

  it("derives the fallback presentation from the current conversation record", () => {
    const cache: ConversationRowViewModelCache = new Map();

    resolveConversationRowViewModel(cache, conversation(), undefined, {});
    const updated = resolveConversationRowViewModel(
      cache,
      conversation({
        contact: {
          id: "contact-1",
          display_name: "Ứng viên đổi tên",
          primary_phone: "0901234567",
          primary_email: null,
          avatar_url: null,
        },
      }),
      undefined,
      {},
    );

    expect(updated.presentation.displayName).toBe("Ứng viên đổi tên");
  });
});

describe("pruneConversationRowViewModelCache", () => {
  it("drops view-models for conversations that left the list", () => {
    const cache: ConversationRowViewModelCache = new Map();
    const kept = conversation({ id: "conv-2", zalo_chat_id: "zalo-2" });
    resolveConversationRowViewModel(cache, conversation(), undefined, {});
    const keptViewModel = resolveConversationRowViewModel(
      cache,
      kept,
      undefined,
      {},
    );

    pruneConversationRowViewModelCache(cache, [kept]);
    expect([...cache.keys()]).toEqual(["conv-2"]);
    expect(
      resolveConversationRowViewModel(cache, kept, undefined, {}),
    ).toBe(keptViewModel);

    pruneConversationRowViewModelCache(cache, []);
    expect(cache.size).toBe(0);
  });
});
