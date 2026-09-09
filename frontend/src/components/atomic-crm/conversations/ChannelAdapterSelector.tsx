import { useQuery } from "@tanstack/react-query";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { MessageCircle } from "lucide-react";

import zaloChatbotIcon from "@/assets/channel-adapters/zalo-chatbot.png";
import zaloOaIcon from "@/assets/channel-adapters/zalo-oa.png";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiJson } from "@/lib/apiClient";
import {
  type ConversationChannelProvider,
  getChannelProviderSearchParams,
} from "./conversation-list-filters";

type ChannelAdapterProvider = ConversationChannelProvider;

// Zalo adapters ship brand artwork; Messenger falls back to a glyph until a
// brand asset lands in assets/channel-adapters/.
type AdapterDefinition = {
  provider: ChannelAdapterProvider;
  label: string;
  icon?: string;
  Glyph?: typeof MessageCircle;
};

const ADAPTERS: readonly AdapterDefinition[] = [
  { provider: "zalo_bot", label: "Zalo Chatbot", icon: zaloChatbotIcon },
  { provider: "zalo_oa", label: "Zalo OA", icon: zaloOaIcon },
  {
    provider: "facebook_messenger",
    label: "Messenger",
    Glyph: MessageCircle,
  },
];

type NeedsAttentionResponse = { count: number };

const useScopedAttentionCount = (provider: ConversationChannelProvider) => {
  const { data } = useQuery<NeedsAttentionResponse>({
    queryKey: ["conversations-needs-attention", provider],
    queryFn: () =>
      apiJson<NeedsAttentionResponse>(
        `/api/v1/conversations/needs-attention?channel_provider=${encodeURIComponent(provider)}`,
      ),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  return data?.count ?? 0;
};

const formatAdapterAttentionCount = (count: number): string =>
  count > 99 ? "99+" : String(count);

const getAdapterAccessibleLabel = (
  label: string,
  count: number,
): string => (count > 0 ? `${label} — ${count} hội thoại cần phản hồi` : label);

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
                  {adapter.icon ? (
                    <img src={adapter.icon} alt="" aria-hidden="true" />
                  ) : adapter.Glyph ? (
                    <adapter.Glyph aria-hidden="true" />
                  ) : null}
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
  // Keep every displayed adapter query mounted regardless of selection so
  // badges stay warm and switching never briefly shows a stale count.
  const zaloBotCount = useScopedAttentionCount("zalo_bot");
  const zaloOaCount = useScopedAttentionCount("zalo_oa");
  const messengerCount = useScopedAttentionCount("facebook_messenger");

  return (
    <ChannelAdapterSelectorView
      provider={provider}
      counts={{
        zalo_bot: zaloBotCount,
        zalo_oa: zaloOaCount,
        facebook_messenger: messengerCount,
      }}
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
