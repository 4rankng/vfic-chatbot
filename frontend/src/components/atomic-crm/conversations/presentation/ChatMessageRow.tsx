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

import type { ConversationChannelProvider, Message } from "../../types";
import { splitMessageTextBlocks } from "../domain/conversation-message-text";
import type { ConversationMessageKind } from "../domain/conversation-thread-rows";
import {
  isUserUnreachableError,
  replyFailureReasonLabel,
} from "../domain/reply-failure-messages";
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
  if (status === "suppressed") return "Không gửi được";
  if (status === "sent") return "Đã gửi";
  return "";
};

const deliveryRetryLabel = (attempts?: number) => {
  if (attempts == null || attempts <= 1) return "";
  const retries = attempts - 1;
  return `Đã thử lại ${retries} lần`;
};

export type ChatMessageRowProps = {
  message: Message;
  kind: ConversationMessageKind;
  isGrouped: boolean;
  candidateAvatarUrl?: string | null;
  isRetrying?: boolean;
  onRetry?: (messageId: string) => void;
  /** The conversation's resolved display channel; picks the failure wording. */
  channelProvider?: ConversationChannelProvider | null;
};

export const ChatMessageRow = memo(
  ({
    message: m,
    kind,
    isGrouped,
    candidateAvatarUrl,
    isRetrying = false,
    onRetry,
    channelProvider = null,
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
    // A permanently unreachable recipient (Zalo -201, Messenger 551) can
    // never be delivered to: retrying only re-pays for a doomed send, so the
    // retry affordance is withheld and the reason is always shown.
    const isUnreachable =
      m.delivery_status === "failed" &&
      isUserUnreachableError(m.external_error);
    const canRetry =
      kind === "agent" &&
      m.delivery_status === "failed" &&
      !isUnreachable &&
      !m.id.startsWith("optimistic-");
    // A failed send whose reply body is empty (e.g. an empty candidate that
    // slipped through) would render a blank bubble. Surface the failure reason
    // instead so the "Gửi lỗi" row always tells the recruiter what happened —
    // and on an unreachable send, even when the body exists.
    const failureReason = replyFailureReasonLabel(
      m.external_error,
      channelProvider,
    );
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
            {failureReason && (!hasText || isUnreachable) ? (
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
