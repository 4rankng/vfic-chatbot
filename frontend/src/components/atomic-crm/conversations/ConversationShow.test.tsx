// Regression coverage for the "Xoá hội thoại" (delete conversation) flow.
//
// Previously, `deleteConversation` called react-admin's `refresh()` after a
// successful delete but left the master-detail UI pinned to the deleted row:
// the parent's `selectedId` and the `?id=` URL param still pointed at the
// now-deleted conversation, so the inbox looked like the delete did nothing.
// The fix surfaces an `onDeleted` callback the parent uses to clear its
// selection. These tests pin that contract: `onDeleted` MUST fire on success
// and MUST NOT fire on failure (so the recruiter keeps the row in view and
// sees the error toast instead of being bounced to an empty list).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import type { ReactNode } from "react";

import type { Conversation } from "../types";

// --- Mocks -------------------------------------------------------------
// ConversationShowContent pulls a lot of context (record, permissions,
// capability slots, conversation actions). We stub ra-core + the sibling
// hooks so the test focuses on the delete handler's contract with its parent.

const dataProviderMock = {
  delete: vi.fn(() => Promise.resolve()),
};

const notifyMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("ra-core", () => ({
  useDataProvider: () => dataProviderMock,
  useNotify: () => notifyMock,
  usePermissions: () => ({ permissions: "admin", loading: false }),
  useRecordContext: () => recordState.record,
  useRefresh: () => refreshMock,
  useTranslate: () => (key: string) => key,
  ShowBase: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
  useIsWideDesktop: () => false,
}));

vi.mock("./presentation/use-conversation-actions", () => ({
  useConversationActions: (_record?: Conversation) => ({
    effectiveMode: "bot",
    isBotMode: true,
    needsClaim: false,
    canHumanReply: false,
    setConversationMode: vi.fn(),
    handleTakeover: vi.fn(),
    handleRelease: vi.fn(),
  }),
}));

vi.mock("./conversation-capability", () => ({
  ConversationContextAdapter: ({
    children,
  }: {
    children: (ctx: Record<string, unknown>) => ReactNode;
  }) => (
    <>{children({ renderPanel: null, displayName: "Tester" })}</>
  ),
  useConversationCapabilitySlots: () => ({ actions: null }),
}));

vi.mock("./presentation/ChatThread", () => ({
  ChatThread: () => <div data-testid="chat-thread-stub" />,
}));

vi.mock("../automation/DecisionTracePanel", () => ({
  DecisionTracePanel: () => null,
}));

import { ConversationShowContent } from "./presentation/ConversationShow";

// --- State holder so the ra-core `useRecordContext` mock can be re-keyed --
const recordState: { record: Conversation | null } = {
  record: null,
};

const baseConversation = (patch: Partial<Conversation> = {}): Conversation =>
  ({
    id: "conv-1",
    zalo_chat_id: "zalo-1",
    mode: "bot",
    needs_human: false,
    assigned_recruiter_id: null,
    last_inbound_at: null,
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    unread_count: 0,
    ...patch,
  }) as Conversation;

beforeEach(() => {
  recordState.record = baseConversation();
  dataProviderMock.delete.mockReset();
  dataProviderMock.delete.mockResolvedValue(undefined);
  notifyMock.mockReset();
  refreshMock.mockReset();
});

afterEach(async () => {
  await cleanup();
});

describe("ConversationShowContent — delete conversation", () => {
  it("calls onDeleted after a successful delete so the parent drops the stale selection", async () => {
    const onDeleted = vi.fn();
    const screen = await render(
      <ConversationShowContent
        onOpenList={vi.fn()}
        onDeleted={onDeleted}
        showWorkspacePanel={false}
      />,
    );

    await screen
      .getByRole("button", { name: "Thao tác hội thoại" })
      .click();
    await screen.getByRole("menuitem", { name: "Xoá hội thoại" }).click();
    await screen
      .getByRole("button", { name: "Xóa vĩnh viễn" })
      .click();

    // Flush the async deleteConversation handler.
    await vi.waitFor(() => expect(dataProviderMock.delete).toHaveBeenCalled());
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalled());

    expect(dataProviderMock.delete).toHaveBeenCalledWith("conversations", {
      id: "conv-1",
      previousData: recordState.record,
    });
    expect(notifyMock).toHaveBeenCalledWith(
      "Đã xóa vĩnh viễn hội thoại.",
      { type: "success" },
    );
    expect(refreshMock).toHaveBeenCalled();
  });

  it("does NOT call onDeleted when the delete fails so the row stays in view", async () => {
    dataProviderMock.delete.mockRejectedValueOnce(new Error("boom"));
    const onDeleted = vi.fn();
    const screen = await render(
      <ConversationShowContent
        onOpenList={vi.fn()}
        onDeleted={onDeleted}
        showWorkspacePanel={false}
      />,
    );

    await screen
      .getByRole("button", { name: "Thao tác hội thoại" })
      .click();
    await screen.getByRole("menuitem", { name: "Xoá hội thoại" }).click();
    await screen
      .getByRole("button", { name: "Xóa vĩnh viễn" })
      .click();

    await vi.waitFor(() => expect(dataProviderMock.delete).toHaveBeenCalled());
    // Give the rejection a tick to settle before asserting the negative.
    await new Promise((r) => setTimeout(r, 0));

    expect(onDeleted).not.toHaveBeenCalled();
    expect(refreshMock).not.toHaveBeenCalled();
    expect(notifyMock).toHaveBeenCalledWith("boom", { type: "error" });
  });
});
