// One row of the conversation thread: the message bubble for a single stored
// message, in whichever variant that message's kind calls for (candidate,
// bot, recruiter, system rail, event rail).
//
// Extracted from the thread so the variants are one memoized component with a
// flat prop surface instead of a switch inside the thread's render body. Every
// prop is a value that actually changes — the message record itself, two
// booleans, a string and a stable callback — so a neighbouring row's re-render
// (a delivery status flipping, a new arrival) never invalidates this one.

import { memo, useMemo, type CSSProperties } from "react";
import { useTranslate } from "ra-core";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/base/buttons/button";

import type { Message } from "../../types";
import { splitMessageTextBlocks } from "../domain/conversation-message-text";
import type { ConversationMessageKind } from "../domain/conversation-thread-rows";
import { LeadAvatar } from "../LeadAvatar";

const AVATAR_PLACEHOLDER_STYLE: CSSProperties = { width: 32 };

const formatTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
};

const deliveryStatusLabel = (status?: Message["delivery_status"]) => {
  if (status === "failed") return "Gửi lỗi";
  if (status === "send_unknown") return "Chưa xác nhận gửi";
  if (status === "suppressed") return "Đã chặn";
  if (status === "sent") return "Đã gửi";
  return "";
};

const deliveryRetryLabel = (attempts?: number) => {
  if (attempts == null || attempts <= 1) return "";
  const retries = attempts - 1;
  return `Đã thử lại ${retries} lần`;
};

/**
 * Map a failed/unknown send's backend `external_error` to a short Vietnamese
 * reason, so a "Gửi lỗi" bubble is diagnosable instead of blank when the
 * attempted reply content is empty/unavailable. Mirrors the provider/network
 * taxonomy used elsewhere in the CRM (vietnameseCrmMessages.reply.*), in Vietnamese.
 */
const failureReasonLabel = (m: Message): string => {
  if (m.delivery_status !== "failed" && m.delivery_status !== "send_unknown") {
    return "";
  }
  const reason = (m.external_error ?? "").toLowerCase();
  if (!reason) return "";
  if (
    reason.includes("user_id is invalid") ||
    reason.includes("user_id is not valid")
  ) {
    return "Người nhận không liên lạc được qua Zalo — thử lại sẽ không thành công";
  }
  if (
    reason.includes("timeout") ||
    reason.includes("connect") ||
    reason.includes("network")
  ) {
    return "Lỗi kết nối mạng";
  }
  return "Zalo từ chối tin nhắn";
};

export type ChatMessageRowProps = {
  message: Message;
  kind: ConversationMessageKind;
  isGrouped: boolean;
  candidateAvatarUrl?: string | null;
  isRetrying?: boolean;
  onRetry?: (messageId: string) => void;
};

export const ChatMessageRow = memo(
  ({
    message: m,
    kind,
    isGrouped,
    candidateAvatarUrl,
    isRetrying = false,
    onRetry,
  }: ChatMessageRowProps) => {
    const translate = useTranslate();
    const textBlocks = useMemo(
      () => splitMessageTextBlocks(m.content),
      [m.content],
    );

    if (kind === "system") {
      return (
        <div className="system-message" data-message-id={m.id}>
          <span>{m.content}</span>
        </div>
      );
    }

    if (kind === "event") {
      return (
        <div className="system-event" data-message-id={m.id}>
          <Sparkles className="icon" />
          <span>{m.content}</span>
        </div>
      );
    }

    const deliveryLabel = deliveryStatusLabel(m.delivery_status);
    const retryLabel = deliveryRetryLabel(m.delivery_attempts);
    const canRetry =
      kind === "agent" &&
      m.delivery_status === "failed" &&
      !m.id.startsWith("optimistic-");
    // A failed send whose reply body is empty (e.g. an empty candidate that
    // slipped through) would render a blank bubble. Surface the failure reason
    // instead so the "Gửi lỗi" row always tells the recruiter what happened.
    const failureReason = failureReasonLabel(m);
    const hasText = textBlocks.some((block) => block && block.trim());
    const avatar =
      kind === "user" ? (
        !isGrouped ? (
          <LeadAvatar
            src={candidateAvatarUrl}
            className="message-avatar"
            iconSize={16}
            alt="Ảnh đại diện người trò chuyện"
          />
        ) : (
          <span
            className="message-avatar-placeholder"
            style={AVATAR_PLACEHOLDER_STYLE}
          />
        )
      ) : null;
    const bubble = (
      <div className="bubble tt-chat-bubble">
        <div className="bubble-content">
          <div className="message-text">
            {textBlocks.map((block, index) =>
              block ? (
                <p className="message-text-block" key={`${index}-${block}`}>
                  {block}
                </p>
              ) : (
                <span
                  aria-hidden="true"
                  className="message-text-break"
                  key={`break-${index}`}
                />
              ),
            )}
            {failureReason && !hasText ? (
              <p className="message-text-block delivery-error-detail">
                {failureReason}
              </p>
            ) : null}
          </div>
          <span className="bubble-meta-inline">
            {kind !== "user" && deliveryLabel ? (
              <span
                className={`delivery-status ${m.delivery_status ?? "sent"}`}
              >
                {deliveryLabel}
              </span>
            ) : null}
            {kind !== "user" && retryLabel ? (
              <span className="delivery-retry-count">{retryLabel}</span>
            ) : null}
            {canRetry ? (
              <Button
                type="button"
                size="sm"
                color="tertiary"
                className="uu-scope delivery-retry-button"
                isDisabled={isRetrying}
                onPress={() => onRetry?.(m.id)}
              >
                {isRetrying
                  ? translate("crm.common.retrying")
                  : translate("crm.common.retry")}
              </Button>
            ) : null}
            <span className="bubble-time-inline">
              {formatTime(m.created_at)}
            </span>
          </span>
        </div>
      </div>
    );

    return (
      <div
        className={`message-row tt-chat ${kind === "user" ? "tt-chat-start" : "tt-chat-end"} ${kind} ${isGrouped ? "grouped" : ""}`}
        data-message-id={m.id}
      >
        {kind === "user" ? (
          <>
            {avatar}
            {bubble}
          </>
        ) : (
          bubble
        )}
      </div>
    );
  },
);
ChatMessageRow.displayName = "ChatMessageRow";
