import { useId, useState } from "react";
import { Bot, Check, ChevronDown, Handshake, UserRound } from "lucide-react";
import { MenuItem } from "react-aria-components";
import { Button } from "@/components/base/buttons/button";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import type {
  ConversationMode,
  EditableConversationMode,
} from "../domain/conversation-mode";
import "../inbox/conversation-header.css";

const OPTIONS = [
  {
    mode: "bot",
    label: "Chatbot",
    description: "Tự động trả lời ứng viên",
    Icon: Bot,
  },
  {
    mode: "human",
    label: "Tư vấn viên",
    description: "Chỉ nhân viên trả lời",
    Icon: UserRound,
  },
  {
    mode: "semi_auto",
    label: "Bán tự động",
    description: "Chatbot trả lời khi nhân viên không phản hồi",
    Icon: Handshake,
  },
] as const;

export const ConversationReplyMode = ({
  mode,
  needsClaim,
  isChangingMode = false,
  onChange,
}: {
  mode: ConversationMode;
  needsClaim: boolean;
  isChangingMode?: boolean;
  onChange: (mode: EditableConversationMode) => void | Promise<void>;
}) => {
  const labelId = useId();
  const [pending, setPending] = useState(false);
  if (mode === "closed") {
    return null;
  }
  const active = OPTIONS.find((option) => option.mode === mode)!;
  const changeMode = async (next: EditableConversationMode) => {
    if (needsClaim || pending || isChangingMode || next === mode) return;
    setPending(true);
    try {
      await onChange(next);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dropdown.Root>
      <Button
        type="button"
        color="secondary"
        size="sm"
        className="uu-scope reply-mode-trigger"
        aria-label="Đổi chế độ trả lời"
        aria-describedby={labelId}
        isDisabled={needsClaim || pending || isChangingMode}
        isLoading={pending || isChangingMode}
        showTextWhileLoading
        iconLeading={active.Icon}
        iconTrailing={ChevronDown}
      >
        <span id={labelId}>Chế độ: {active.label}</span>
      </Button>
      <Dropdown.Popover
        placement="top end"
        offset={8}
        className="uu-scope reply-mode-menu"
      >
        <Dropdown.Menu aria-label="Chế độ trả lời">
          {OPTIONS.map((option) => (
            <MenuItem
              key={option.mode}
              id={option.mode}
              textValue={option.label}
              data-allow-tall
              className={`reply-mode-option ${mode === option.mode ? "is-current" : ""}`}
              onAction={() => void changeMode(option.mode)}
            >
              <option.Icon
                className="reply-mode-option-icon"
                aria-hidden="true"
              />
              <span className="reply-mode-option-copy">
                <span className="reply-mode-option-title">
                  {option.label}
                  {mode === option.mode ? (
                    <span className="sr-only"> · Đang chọn</span>
                  ) : null}
                </span>
                <span className="reply-mode-option-description">
                  {option.description}
                </span>
              </span>
              {mode === option.mode ? (
                <Check className="reply-mode-option-icon" aria-hidden="true" />
              ) : null}
            </MenuItem>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown.Root>
  );
};
