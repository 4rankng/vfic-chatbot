import { describe, expect, it, vi } from "vitest";

import { changeConversationMode } from "./conversation-actions";

describe("changeConversationMode", () => {
  it("writes an eligible mode change through the supplied port", async () => {
    const writer = {
      setConversationMode: vi.fn().mockResolvedValue(undefined),
    };

    await expect(
      changeConversationMode({
        conversationId: "conversation-1",
        currentMode: "bot",
        needsClaim: false,
        nextMode: "semi_auto",
        writer,
      }),
    ).resolves.toEqual({ kind: "changed", mode: "semi_auto" });

    expect(writer.setConversationMode).toHaveBeenCalledWith(
      "conversation-1",
      "semi_auto",
    );
  });

  it("skips an unchanged mode unless human mode still needs a claim", async () => {
    const writer = {
      setConversationMode: vi.fn().mockResolvedValue(undefined),
    };

    await expect(
      changeConversationMode({
        conversationId: "conversation-1",
        currentMode: "human",
        needsClaim: false,
        nextMode: "human",
        writer,
      }),
    ).resolves.toEqual({ kind: "unchanged" });

    await expect(
      changeConversationMode({
        conversationId: "conversation-1",
        currentMode: "human",
        needsClaim: true,
        nextMode: "human",
        writer,
      }),
    ).resolves.toEqual({ kind: "changed", mode: "human" });

    expect(writer.setConversationMode).toHaveBeenCalledTimes(1);
    expect(writer.setConversationMode).toHaveBeenCalledWith(
      "conversation-1",
      "human",
    );
  });

  it("returns a failed result when the writer rejects", async () => {
    const writer = {
      setConversationMode: vi.fn().mockRejectedValue(new Error("conflict")),
    };

    await expect(
      changeConversationMode({
        conversationId: "conversation-1",
        currentMode: "bot",
        needsClaim: false,
        nextMode: "human",
        writer,
      }),
    ).resolves.toEqual({ kind: "failed", mode: "human" });
  });
});
