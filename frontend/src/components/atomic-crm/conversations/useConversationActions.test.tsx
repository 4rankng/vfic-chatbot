import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";

import type { Conversation } from "../types";

const dataProvider = {
  setConversationMode: vi.fn(() => Promise.resolve()),
};
const notify = vi.fn();
const refresh = vi.fn();

vi.mock("ra-core", () => ({
  useDataProvider: () => dataProvider,
  useNotify: () => notify,
  useRefresh: () => refresh,
}));

import { useConversationActions } from "./useConversationActions";

const unassignedHuman = {
  id: "conv-1",
  mode: "human",
  assigned_recruiter_id: null,
} as Conversation;

const Harness = ({
  conversation = unassignedHuman,
}: {
  conversation?: Conversation;
}) => {
  const { needsClaim, canHumanReply, handleTakeover } =
    useConversationActions(conversation);
  return (
    <div>
      <span>{needsClaim ? "needs-claim" : "claimed"}</span>
      <span>{canHumanReply ? "can-reply" : "cannot-reply"}</span>
      <button type="button" onClick={() => void handleTakeover()}>
        Tiếp quản
      </button>
    </div>
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  dataProvider.setConversationMode.mockResolvedValue(undefined);
});

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
});
