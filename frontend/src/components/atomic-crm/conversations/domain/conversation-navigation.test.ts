import { describe, expect, it } from "vitest";

import {
  conversationSelectionParams,
  findSelectedConversation,
} from "./conversation-navigation";

describe("conversationSelectionParams", () => {
  it("clears the candidate-panel deep link when another conversation is selected", () => {
    const result = conversationSelectionParams(
      new URLSearchParams("id=conversation-1&panel=candidate"),
      "conversation-2",
    );

    expect(result.toString()).toBe("id=conversation-2");
  });

  it("clears both conversation and panel when returning to the list", () => {
    const result = conversationSelectionParams(
      new URLSearchParams("id=conversation-1&panel=candidate"),
      null,
    );

    expect(result.toString()).toBe("");
  });

  it("selects a fetched deep-link conversation outside the current inbox page", () => {
    const visibleConversations = [{ id: "hang-do" }];
    const deepLinkedConversation = { id: "bui-hai-anh" };

    expect(
      findSelectedConversation(
        visibleConversations,
        "bui-hai-anh",
        deepLinkedConversation,
      ),
    ).toBe(deepLinkedConversation);
  });
});
