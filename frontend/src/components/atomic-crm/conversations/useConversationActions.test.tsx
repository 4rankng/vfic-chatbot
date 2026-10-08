import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import { StrictMode } from "react";

import type { Conversation } from "../types";
import type { ConversationModeWriter } from "./application/conversation-actions";

const dataProvider = {
  setConversationMode: vi.fn<ConversationModeWriter["setConversationMode"]>(
    () => Promise.resolve(),
  ),
  botReply: vi.fn(() => Promise.resolve()),
};
const notify = vi.fn();
const refresh = vi.fn();

vi.mock("ra-core", () => ({
  useDataProvider: () => dataProvider,
  useNotify: () => notify,
  useRefresh: () => refresh,
}));

import { useConversationActions } from "./presentation/use-conversation-actions";

const unassignedHuman = {
  id: "conv-1",
  mode: "human",
  assigned_recruiter_id: null,
  version: 10,
  updated_at: "2026-10-02T00:00:00Z",
} as Conversation;

const Harness = ({
  conversation = unassignedHuman,
}: {
  conversation?: Conversation;
}) => {
  const {
    effectiveMode,
    needsClaim,
    canHumanReply,
    isChangingMode,
    handleTakeover,
    handleBotReply,
  } = useConversationActions(conversation);
  return (
    <div>
      <span>{needsClaim ? "needs-claim" : "claimed"}</span>
      <span>{canHumanReply ? "can-reply" : "cannot-reply"}</span>
      <span>{isChangingMode ? "pending" : "ready"}</span>
      <span>{`mode-${effectiveMode}`}</span>
      <button type="button" onClick={() => void handleTakeover()}>
        Tiếp quản
      </button>
      <button type="button" onClick={() => void handleBotReply()}>
        Bot đọc hội thoại
      </button>
    </div>
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  dataProvider.setConversationMode.mockResolvedValue(undefined);
  dataProvider.botReply.mockResolvedValue(undefined);
});

const deferred = () => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise<unknown>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

afterEach(async () => {
  await cleanup();
});

describe("useConversationActions — unassigned HUMAN", () => {
  it("keeps replies disabled until takeover succeeds", async () => {
    const screen = await render(<Harness />);
    await expect.element(screen.getByText("needs-claim")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();

    await screen.getByRole("button", { name: "Tiếp quản" }).click();

    expect(dataProvider.setConversationMode).toHaveBeenCalledWith(
      "conv-1",
      "human",
    );
    expect(notify).toHaveBeenCalledWith("conversations.takeover.success", {
      type: "success",
    });
    expect(refresh).toHaveBeenCalledOnce();
    expect(
      dataProvider.setConversationMode.mock.invocationCallOrder[0],
    ).toBeLessThan(notify.mock.invocationCallOrder[0]);
    expect(notify.mock.invocationCallOrder[0]).toBeLessThan(
      refresh.mock.invocationCallOrder[0],
    );
    await expect.element(screen.getByText("claimed")).toBeVisible();
    await expect.element(screen.getByText("can-reply")).toBeVisible();
  });

  it("does not unlock replies when takeover fails", async () => {
    dataProvider.setConversationMode.mockRejectedValueOnce(
      new Error("conflict"),
    );
    const screen = await render(<Harness />);

    await screen.getByRole("button", { name: "Tiếp quản" }).click();

    expect(notify).toHaveBeenCalledWith("conversations.takeover.error", {
      type: "error",
    });
    expect(refresh).not.toHaveBeenCalled();
    await expect.element(screen.getByText("needs-claim")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it("does not leak optimistic mode into the next selected conversation", async () => {
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("can-reply")).toBeVisible();

    const nextConversation = {
      ...unassignedHuman,
      id: "conv-2",
      mode: "bot",
    } as Conversation;
    await screen.rerender(<Harness conversation={nextConversation} />);

    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it("follows a newer authoritative mode for the same conversation", async () => {
    dataProvider.setConversationMode.mockResolvedValue({
      ...unassignedHuman,
      version: 11,
      assigned_recruiter_id: "recruiter-1",
    });
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("can-reply")).toBeVisible();

    await screen.rerender(
      <Harness
        conversation={
          {
            ...unassignedHuman,
            mode: "bot",
            version: 12,
          } as Conversation
        }
      />,
    );
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it("serializes repeated takeover clicks while the write is pending", async () => {
    const write = deferred();
    dataProvider.setConversationMode.mockReturnValue(write.promise);
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("pending")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    expect(dataProvider.setConversationMode).toHaveBeenCalledOnce();
    write.resolve(undefined);
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    await expect.element(screen.getByText("ready")).toBeVisible();
  });

  it("discards a late takeover completion after selecting another conversation", async () => {
    const write = deferred();
    dataProvider.setConversationMode.mockReturnValue(write.promise);
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await screen.rerender(
      <Harness
        conversation={{
          ...unassignedHuman,
          id: "conv-2",
          mode: "bot",
        }}
      />,
    );
    write.resolve(undefined);
    await vi.waitFor(() =>
      expect(dataProvider.setConversationMode).toHaveBeenCalledOnce(),
    );
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
    expect(notify).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("keeps accepted local state through an older refresh and then follows the caught-up row", async () => {
    const original = { ...unassignedHuman, mode: "bot" as const };
    const accepted = {
      ...unassignedHuman,
      version: 11,
      assigned_recruiter_id: "recruiter-1",
    };
    dataProvider.setConversationMode.mockResolvedValue(accepted);
    const screen = await render(<Harness conversation={original} />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("mode-human")).toBeVisible();

    await screen.rerender(<Harness conversation={{ ...original }} />);
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    await screen.rerender(<Harness conversation={accepted} />);
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    await screen.rerender(
      <Harness conversation={{ ...original, version: 12, mode: "closed" }} />,
    );
    await expect.element(screen.getByText("mode-closed")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it("resets the local claim when the server requires human verification again", async () => {
    dataProvider.setConversationMode.mockResolvedValue({
      ...unassignedHuman,
      version: 11,
      assigned_recruiter_id: "recruiter-1",
    });
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    await screen.rerender(
      <Harness conversation={{ ...unassignedHuman, version: 12 }} />,
    );
    await expect.element(screen.getByText("needs-claim")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it("keeps a newer server transition that arrived before the action response", async () => {
    const write = deferred();
    dataProvider.setConversationMode.mockReturnValue(write.promise);
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await screen.rerender(
      <Harness
        conversation={{ ...unassignedHuman, version: 12, mode: "closed" }}
      />,
    );
    write.resolve({
      ...unassignedHuman,
      version: 11,
      assigned_recruiter_id: "recruiter-1",
    });
    await expect.element(screen.getByText("ready")).toBeVisible();
    await expect.element(screen.getByText("mode-closed")).toBeVisible();
    await expect.element(screen.getByText("cannot-reply")).toBeVisible();
  });

  it.each([undefined, 0, NaN, "11"])(
    "reconciles by mode and assignment when the accepted version is %s",
    async (version) => {
      dataProvider.setConversationMode.mockResolvedValue(
        version === undefined
          ? undefined
          : {
              ...unassignedHuman,
              version,
              assigned_recruiter_id: "recruiter-1",
            },
      );
      const screen = await render(<Harness />);
      await screen.getByRole("button", { name: "Tiếp quản" }).click();
      await expect.element(screen.getByText("can-reply")).toBeVisible();
      await screen.rerender(<Harness conversation={{ ...unassignedHuman }} />);
      await expect.element(screen.getByText("can-reply")).toBeVisible();
      await screen.rerender(
        <Harness
          conversation={{
            ...unassignedHuman,
            assigned_recruiter_id: "recruiter-1",
          }}
        />,
      );
      await expect.element(screen.getByText("can-reply")).toBeVisible();
      await screen.rerender(<Harness conversation={{ ...unassignedHuman }} />);
      await expect.element(screen.getByText("needs-claim")).toBeVisible();
    },
  );

  it("does not clear the next conversation's pending write when an old response finishes", async () => {
    const previous = deferred();
    const current = deferred();
    dataProvider.setConversationMode
      .mockReturnValueOnce(previous.promise)
      .mockReturnValueOnce(current.promise);
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await screen.rerender(
      <Harness conversation={{ ...unassignedHuman, id: "conv-2" }} />,
    );
    await expect.element(screen.getByText("ready")).toBeVisible();
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    previous.resolve(undefined);
    await expect.element(screen.getByText("pending")).toBeVisible();
    expect(notify).not.toHaveBeenCalled();
    current.resolve(undefined);
    await expect.element(screen.getByText("ready")).toBeVisible();
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    expect(notify).toHaveBeenCalledOnce();
  });

  it("discards an action response after the hook unmounts", async () => {
    const write = deferred();
    dataProvider.setConversationMode.mockReturnValue(write.promise);
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await cleanup();
    write.resolve(undefined);
    await write.promise;
    await new Promise<void>((resolve) => queueMicrotask(resolve));
    expect(notify).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("accepts a current action after StrictMode replays mount cleanup", async () => {
    const screen = await render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect.element(screen.getByText("can-reply")).toBeVisible();
    expect(dataProvider.setConversationMode).toHaveBeenCalledOnce();
    expect(notify).toHaveBeenCalledOnce();
  });
});

describe("useConversationActions — bot review", () => {
  const botConversation = {
    ...unassignedHuman,
    mode: "bot",
    assigned_recruiter_id: null,
  } as Conversation;

  it("asks the bot to review the thread and refreshes on success", async () => {
    const screen = await render(<Harness conversation={botConversation} />);

    await screen.getByRole("button", { name: "Bot đọc hội thoại" }).click();

    expect(dataProvider.botReply).toHaveBeenCalledWith("conv-1");
    expect(notify).toHaveBeenCalledWith("conversations.bot_reply.success", {
      type: "success",
    });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("reports a refused review and refreshes nothing", async () => {
    dataProvider.botReply.mockRejectedValueOnce(new Error("conflict"));
    const screen = await render(<Harness conversation={botConversation} />);

    await screen.getByRole("button", { name: "Bot đọc hội thoại" }).click();

    expect(notify).toHaveBeenCalledWith("conversations.bot_reply.error", {
      type: "error",
    });
    expect(refresh).not.toHaveBeenCalled();
  });
});
