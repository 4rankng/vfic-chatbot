import { useId, type ReactNode, type Ref } from "react";
import { ArrowLeft, ChevronRight, Phone } from "lucide-react";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import type { ConversationContextValue } from "../../capabilities/types";
import { LeadAvatar } from "../LeadAvatar";
import "../inbox/conversation-header.css";

type Props = {
  identity: ConversationContextValue;
  onBack?: () => void;
  onOpenCandidate?: (trigger: HTMLButtonElement) => void;
  candidateOpen: boolean;
  candidateTriggerRef?: Ref<HTMLButtonElement>;
  actions?: ReactNode;
};

/** Identity and navigation only; reply controls belong beside the composer. */
export const ConversationHeader = ({
  identity,
  onBack,
  onOpenCandidate,
  candidateOpen,
  candidateTriggerRef,
  actions,
}: Props) => {
  const contactId = useId();
  const phone = identity.contactSubtitle?.phone?.trim();
  const contents = (
    <>
      <LeadAvatar
        src={identity.avatarUrl}
        bg={identity.avatarBackground}
        ink={identity.avatarForeground}
        iconSize={18}
        className="conversation-header-avatar"
        alt={identity.avatarAlt}
      />
      <span className="conversation-header-copy">
        <span className="conversation-header-name">{identity.displayName}</span>
        <span id={contactId} className="conversation-header-metadata">
          <span className="conversation-header-phone">
            <Phone aria-hidden="true" />
            <span>{phone || "Chưa có số điện thoại"}</span>
          </span>
        </span>
        {identity.contactSubtitle?.secondaryName ? (
          <span className="conversation-header-confirmed-name">
            {identity.contactSubtitle.secondaryName}
          </span>
        ) : null}
      </span>
      {onOpenCandidate ? (
        <ChevronRight
          className="conversation-header-disclosure"
          aria-hidden="true"
        />
      ) : null}
    </>
  );

  return (
    <header className="chat-header conversation-header">
      {onBack ? (
        <ButtonUtility
          color="tertiary"
          tooltip="Mở danh sách hội thoại"
          className="uu-scope conversation-header-back"
          icon={<ArrowLeft aria-hidden="true" />}
          onPress={onBack}
        />
      ) : null}
      {onOpenCandidate ? (
        <button
          ref={candidateTriggerRef}
          type="button"
          data-allow-tall
          className="conversation-header-identity conversation-header-identity-button"
          aria-label={`Xem thông tin ứng viên của ${identity.displayName}`}
          aria-describedby={contactId}
          aria-expanded={candidateOpen}
          aria-controls="conversation-context-panel"
          onClick={(event) => onOpenCandidate(event.currentTarget)}
        >
          {contents}
        </button>
      ) : (
        <div className="conversation-header-identity">{contents}</div>
      )}
      {actions ? (
        <div className="conversation-header-actions">{actions}</div>
      ) : null}
    </header>
  );
};
