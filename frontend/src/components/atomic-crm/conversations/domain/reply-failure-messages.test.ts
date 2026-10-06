import { describe, expect, it } from "vitest";

import {
  isUserUnreachableError,
  replyFailureMessageKey,
  replyFailureReasonLabel,
} from "./reply-failure-messages";

describe("replyFailureMessageKey", () => {
  it("keys channel-naming failures to the Messenger catalog", () => {
    expect(
      replyFailureMessageKey("provider", {
        provider: "facebook_messenger",
        account_key: "486833177846024",
      }),
    ).toBe("resources.conversations.reply_messenger.provider");
    expect(
      replyFailureMessageKey("unavailable", {
        provider: "facebook_messenger",
        account_key: "486833177846024",
      }),
    ).toBe("resources.conversations.reply_messenger.unavailable");
  });

  it("keeps Zalo channels on the shared Zalo-worded catalog", () => {
    const zaloIdentity = {
      provider: "zalo_oa",
      account_key: "default:zalo_oa",
    };
    expect(replyFailureMessageKey("provider", zaloIdentity)).toBe(
      "resources.conversations.reply.provider",
    );
    expect(
      replyFailureMessageKey("unavailable", {
        provider: "zalo_oa",
        account_key: "tingting",
      }),
    ).toBe("resources.conversations.reply.unavailable");
  });

  it("keeps neutral statuses on the shared catalog for every channel", () => {
    const messengerIdentity = { provider: "facebook_messenger" };
    expect(replyFailureMessageKey("conflict", messengerIdentity)).toBe(
      "resources.conversations.reply.conflict",
    );
    expect(replyFailureMessageKey("network", messengerIdentity)).toBe(
      "resources.conversations.reply.network",
    );
    expect(replyFailureMessageKey("error", messengerIdentity)).toBe(
      "resources.conversations.reply.error",
    );
  });

  it("falls back to the shared catalog when the channel is unknown", () => {
    expect(replyFailureMessageKey("provider", null)).toBe(
      "resources.conversations.reply.provider",
    );
    expect(
      replyFailureMessageKey("provider", { provider: "carrier_pigeon" }),
    ).toBe("resources.conversations.reply.provider");
  });
});

describe("isUserUnreachableError", () => {
  it("matches the proven per-recipient refusal signals", () => {
    expect(isUserUnreachableError("user_id is invalid")).toBe(true);
    expect(
      isUserUnreachableError("zalo send rejected: user_id is not valid"),
    ).toBe(true);
    // Production 2026-10-06: code=551 subcode=1545041, blocked/deactivated
    // Messenger recipient, permanent across bot turns and a recruiter retry.
    expect(
      isUserUnreachableError(
        "messenger send rejected (code=551, subcode=1545041): This person isn't available right now.",
      ),
    ).toBe(true);
    expect(
      isUserUnreachableError(
        "messenger send rejected (code=100, subcode=2018001): No matching user found",
      ),
    ).toBe(true);
    expect(
      isUserUnreachableError(
        "send skipped: recipient terminally unreachable (marked 2026-10-06)",
      ),
    ).toBe(true);
  });

  it("does not claim retryable failures", () => {
    expect(isUserUnreachableError(null)).toBe(false);
    expect(isUserUnreachableError("")).toBe(false);
    expect(
      isUserUnreachableError("messenger send rejected (code=10): transient"),
    ).toBe(false);
    expect(
      isUserUnreachableError("send rejected: timeout waiting for provider"),
    ).toBe(false);
  });
});

describe("replyFailureReasonLabel", () => {
  it("names Messenger on a Messenger conversation", () => {
    const messengerError =
      "messenger send rejected (code=551, subcode=1545041): This person isn't available right now.";
    expect(replyFailureReasonLabel(messengerError, "facebook_messenger")).toBe(
      "Người nhận không liên lạc được qua Messenger — thử lại sẽ không thành công",
    );
    expect(
      replyFailureReasonLabel(
        "messenger send rejected (code=10): bad",
        "facebook_messenger",
      ),
    ).toBe("Messenger từ chối tin nhắn");
  });

  it("keeps Zalo wording on Zalo conversations", () => {
    expect(replyFailureReasonLabel("user_id is invalid", "zalo_oa")).toBe(
      "Người nhận không liên lạc được qua Zalo — thử lại sẽ không thành công",
    );
    expect(
      replyFailureReasonLabel("zalo send rejected (code=-201)", "zalo_oa"),
    ).toBe("Zalo từ chối tin nhắn");
  });

  it("falls back to Zalo wording for unknown channels", () => {
    expect(replyFailureReasonLabel("zalo send rejected", null)).toBe(
      "Zalo từ chối tin nhắn",
    );
  });

  it("keeps the network reason channel-neutral", () => {
    expect(
      replyFailureReasonLabel(
        "timeout waiting for provider",
        "facebook_messenger",
      ),
    ).toBe("Lỗi kết nối mạng");
  });
});
