import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";

import messengerIcon from "@/assets/channel-adapters/facebook-messenger.svg";
import tingtingOaIcon from "@/assets/channel-adapters/tingting-oa.png";
import zaloChatbotIcon from "@/assets/channel-adapters/zalo-chatbot.png";
import zaloOaIcon from "@/assets/channel-adapters/zalo-oa.png";
import { useAttentionCounts } from "@/components/atomic-crm/layout/topbar/useAttentionCounts";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  type ConversationChannelProvider,
  CONVERSATION_CHANNEL_LABELS,
} from "../types";
import { getChannelProviderSearchParams } from "./domain/conversation-list-filters";

type ChannelAdapterProvider = ConversationChannelProvider;

type AdapterDefinition = {
  provider: ChannelAdapterProvider;
  label: string;
  icon: string;
};

const ADAPTERS: readonly AdapterDefinition[] = [
  {
    provider: "zalo_bot",
    label: CONVERSATION_CHANNEL_LABELS.zalo_bot,
    icon: zaloChatbotIcon,
  },
  {
    provider: "zalo_oa",
    label: CONVERSATION_CHANNEL_LABELS.zalo_oa,
    icon: zaloOaIcon,
  },
  {
    provider: "facebook_messenger",
    label: CONVERSATION_CHANNEL_LABELS.facebook_messenger,
    icon: messengerIcon,
  },
  {
    provider: "tingting_oa",
    label: CONVERSATION_CHANNEL_LABELS.tingting_oa,
    icon: tingtingOaIcon,
  },
];

const formatAdapterAttentionCount = (count: number): string =>
  count > 99 ? "99+" : String(count);

const getAdapterAccessibleLabel = (label: string, count: number): string =>
  count > 0 ? `${label} — ${count} hội thoại cần phản hồi` : label;

export const ChannelAdapterSelectorView = ({
  provider,
  counts,
  onProviderChange,
}: {
  provider: ConversationChannelProvider | undefined;
  counts: Readonly<Record<ChannelAdapterProvider, number>>;
  onProviderChange: (provider: ConversationChannelProvider | undefined) => void;
}) => {
  return (
    <div className="channel-adapter-selector">
      <RadioGroupPrimitive.Root
        className="channel-adapter-options"
        aria-label="Chọn kênh hội thoại"
        value={provider ?? ""}
        onValueChange={(value) => {
          if (ADAPTERS.some((adapter) => adapter.provider === value)) {
            onProviderChange(value as ChannelAdapterProvider);
          }
        }}
      >
        {ADAPTERS.map((adapter) => {
          const count = counts[adapter.provider];
          const accessibleLabel = getAdapterAccessibleLabel(
            adapter.label,
            count,
          );
          return (
            <Tooltip key={adapter.provider}>
              <TooltipTrigger asChild>
                <RadioGroupPrimitive.Item
                  value={adapter.provider}
                  className="channel-adapter-option"
                  aria-label={accessibleLabel}
                  onClick={() => {
                    if (provider === adapter.provider) {
                      onProviderChange(undefined);
                    }
                  }}
                >
                  <img src={adapter.icon} alt="" aria-hidden="true" />
                  {count > 0 ? (
                    <span
                      className="channel-adapter-badge"
                      aria-label={`${count} hội thoại cần phản hồi`}
                    >
                      {formatAdapterAttentionCount(count)}
                    </span>
                  ) : null}
                </RadioGroupPrimitive.Item>
              </TooltipTrigger>
              <TooltipContent side="bottom">{accessibleLabel}</TooltipContent>
            </Tooltip>
          );
        })}
      </RadioGroupPrimitive.Root>
    </div>
  );
};

export const ChannelAdapterSelector = ({
  provider,
  searchParams,
  onSearchParamsChange,
}: {
  provider: ConversationChannelProvider | undefined;
  searchParams: URLSearchParams;
  onSearchParamsChange: (next: URLSearchParams) => void;
}) => {
  // One shared counts query feeds every displayed adapter (and the topbar
  // bell), so switching scope never briefly shows a stale badge and the panel
  // never runs its own pollers.
  const { byProvider } = useAttentionCounts();

  return (
    <ChannelAdapterSelectorView
      provider={provider}
      counts={byProvider}
      onProviderChange={(nextProvider) => {
        if (nextProvider) {
          onSearchParamsChange(
            getChannelProviderSearchParams(searchParams, nextProvider),
          );
          return;
        }
        const next = new URLSearchParams(searchParams);
        next.delete("channel_provider");
        next.delete("id");
        onSearchParamsChange(next);
      }}
    />
  );
};
