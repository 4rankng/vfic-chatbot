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
import { MemoryRouter } from "react-router";

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
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  useDataProvider: () => dataProviderMock,
  useNotify: () => notifyMock,
  usePermissions: () => ({
    permissions: permissionState.value,
    loading: false,
  }),
  useRecordContext: () => recordState.record,
  useRefresh: () => refreshMock,
  ShowBase: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
  useIsWideDesktop: () => false,
}));

vi.mock("./presentation/use-conversation-actions", () => ({
  useConversationActions: (_record?: Conversation) => ({
    ...modeState,
    setConversationMode: changeModeMock,
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
    <>
      {children({
        displayName: "Tester",
        panelLabel: "Dữ liệu ứng viên",
        renderPanel: capabilityState.hasPanel
          ? ({ open, onClose }: { open: boolean; onClose: () => void }) => (
              <div
                id="conversation-context-panel"
                data-testid="candidate-panel-state"
              >
                {open ? "candidate-panel-open" : "candidate-panel-closed"}
                {open ? (
                  <button
                    type="button"
                    onClick={() => {
                      onClose();
                    }}
                  >
                    Đóng hồ sơ thử nghiệm
                  </button>
                ) : null}
              </div>
            )
          : undefined,
      })}
    </>
  ),
}));

vi.mock("./useConversationCapabilitySlots", () => ({
  useConversationCapabilitySlots: () => ({ actions: null }),
}));

vi.mock("./presentation/ChatThread", () => ({
  ChatThread: ({ composerToolbar }: { composerToolbar?: ReactNode }) => (
    <div data-testid="chat-thread-stub">
      <footer className="composer-wrap">{composerToolbar}</footer>
    </div>
  ),
}));

vi.mock("../automation/DecisionTracePanel", () => ({
  DecisionTracePanel: () => null,
}));

import { ConversationShowContent } from "./presentation/ConversationShow";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

// --- State holder so the ra-core `useRecordContext` mock can be re-keyed --
const permissionState = { value: "admin" };
const capabilityState = { hasPanel: true };
const modeState = {
  effectiveMode: "bot" as Conversation["mode"],
  isBotMode: true,
  needsClaim: false,
  canHumanReply: false,
  isChangingMode: false,
};
const changeModeMock = vi.fn();
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
  permissionState.value = "admin";
  capabilityState.hasPanel = true;
  Object.assign(modeState, {
    effectiveMode: "bot",
    isBotMode: true,
    needsClaim: false,
    canHumanReply: false,
    isChangingMode: false,
  });
  changeModeMock.mockReset();
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
      <MemoryRouter>
        <ConversationShowContent
          onOpenList={vi.fn()}
          onDeleted={onDeleted}
          showWorkspacePanel={false}
        />
      </MemoryRouter>,
    );

    await screen.getByRole("button", { name: "Thao tác hội thoại" }).click();
    await screen.getByRole("menuitem", { name: "Xoá hội thoại" }).click();
    await screen.getByRole("button", { name: "Xóa vĩnh viễn" }).click();

    // Flush the async deleteConversation handler.
    await vi.waitFor(() => expect(dataProviderMock.delete).toHaveBeenCalled());
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalled());

    expect(dataProviderMock.delete).toHaveBeenCalledWith("conversations", {
      id: "conv-1",
      previousData: recordState.record,
    });
    expect(notifyMock).toHaveBeenCalledWith("Đã xóa vĩnh viễn hội thoại.", {
      type: "success",
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it("does NOT call onDeleted when the delete fails so the row stays in view", async () => {
    dataProviderMock.delete.mockRejectedValueOnce(new Error("boom"));
    const onDeleted = vi.fn();
    const screen = await render(
      <MemoryRouter>
        <ConversationShowContent
          onOpenList={vi.fn()}
          onDeleted={onDeleted}
          showWorkspacePanel={false}
        />
      </MemoryRouter>,
    );

    await screen.getByRole("button", { name: "Thao tác hội thoại" }).click();
    await screen.getByRole("menuitem", { name: "Xoá hội thoại" }).click();
    await screen.getByRole("button", { name: "Xóa vĩnh viễn" }).click();

    await vi.waitFor(() => expect(dataProviderMock.delete).toHaveBeenCalled());
    // Give the rejection a tick to settle before asserting the negative.
    await new Promise((r) => setTimeout(r, 0));

    expect(onDeleted).not.toHaveBeenCalled();
    expect(refreshMock).not.toHaveBeenCalled();
    expect(notifyMock).toHaveBeenCalledWith("boom", { type: "error" });
  });
});

describe("ConversationShowContent — candidate profile deep link", () => {
  it("keeps reply mode near the composer and gives recruiters one candidate action", async () => {
    permissionState.value = "recruiter";
    recordState.record = baseConversation({
      channel_identity: {
        id: "identity-1",
        provider: "zalo_oa",
        account_key: "***",
        external_id: "candidate-1",
        display_channel: "tingting_oa",
      },
    });
    const screen = await render(
      <MemoryRouter>
        <ConversationShowContent onOpenList={vi.fn()} showWorkspacePanel />
      </MemoryRouter>,
    );
    expect(
      screen.container.querySelectorAll(".conversation-header-identity-button"),
    ).toHaveLength(1);
    expect(
      screen.container.querySelector(".conversation-header-actions-button"),
    ).toBeNull();
    expect(
      screen.container.querySelector(".chat-header .reply-mode-trigger"),
    ).toBeNull();
    expect(
      screen.container.querySelector(".composer-wrap .reply-mode-trigger"),
    ).not.toBeNull();
    const channel = screen.container.querySelector<HTMLImageElement>(
      ".composer-wrap .composer-channel-icon",
    )!;
    expect(channel.alt).toBe("TingTing OA");
    expect(channel.title).toBe("TingTing OA");
    expect(channel.nextElementSibling?.matches(".reply-mode-trigger")).toBe(
      true,
    );
    expect(
      screen.container.querySelector(".chat-header .composer-channel-icon"),
    ).toBeNull();
  });

  it("offers no dead candidate action when the host does not render the panel", async () => {
    const screen = await render(
      <MemoryRouter>
        <ConversationShowContent
          onOpenList={vi.fn()}
          showWorkspacePanel={false}
        />
      </MemoryRouter>,
    );
    expect(
      screen.container.querySelector(".conversation-header-identity-button"),
    ).toBeNull();
    expect(
      screen.container.querySelector("#conversation-context-panel"),
    ).toBeNull();
    await screen.getByRole("button", { name: "Thao tác hội thoại" }).click();
    expect(document.querySelector('[data-key="candidate-panel"]')).toBeNull();
    await expect
      .element(screen.getByRole("menuitem", { name: "Xoá hội thoại" }))
      .toBeVisible();
  });

  it("offers no dead candidate action when the capability has no panel", async () => {
    capabilityState.hasPanel = false;
    const screen = await render(
      <MemoryRouter>
        <ConversationShowContent onOpenList={vi.fn()} showWorkspacePanel />
      </MemoryRouter>,
    );
    expect(
      screen.container.querySelector(".conversation-header-identity-button"),
    ).toBeNull();
    expect(
      screen.container.querySelector("#conversation-context-panel"),
    ).toBeNull();
    await screen.getByRole("button", { name: "Thao tác hội thoại" }).click();
    expect(document.querySelector('[data-key="candidate-panel"]')).toBeNull();
    await expect
      .element(screen.getByRole("menuitem", { name: "Xoá hội thoại" }))
      .toBeVisible();
  });

  it("opens Dữ liệu ứng viên from one identity button and restores focus", async () => {
    const screen = await render(
      <MemoryRouter>
        <ConversationShowContent onOpenList={vi.fn()} showWorkspacePanel />
      </MemoryRouter>,
    );

    await expect
      .element(screen.getByTestId("candidate-panel-state"))
      .toHaveTextContent("candidate-panel-closed");

    const avatarTrigger = screen.getByRole("button", {
      name: "Xem thông tin ứng viên của Tester",
    });
    await avatarTrigger.click();

    await expect
      .element(screen.getByTestId("candidate-panel-state"))
      .toHaveTextContent("candidate-panel-open");
    await expect
      .element(avatarTrigger)
      .toHaveAttribute("aria-expanded", "true");

    await screen.getByRole("button", { name: "Đóng hồ sơ thử nghiệm" }).click();
    await expect.element(avatarTrigger).toHaveFocus();
  });

  it("opens Dữ liệu ứng viên when the dashboard supplies panel=candidate", async () => {
    const screen = await render(
      <MemoryRouter
        initialEntries={["/conversations?id=conv-1&panel=candidate"]}
      >
        <ConversationShowContent onOpenList={vi.fn()} showWorkspacePanel />
      </MemoryRouter>,
    );

    await expect
      .element(screen.getByTestId("candidate-panel-state"))
      .toHaveTextContent("candidate-panel-open");
  });
});
