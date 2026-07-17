import { useQuery } from "@tanstack/react-query";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";

import zaloChatbotIcon from "@/assets/channel-adapters/zalo-chatbot.png";
import zaloOaIcon from "@/assets/channel-adapters/zalo-oa.png";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiJson } from "../providers/rest/api";
import {
  type ConversationChannelProvider,
  getChannelProviderSearchParams,
} from "./conversation-list-filters";

type AdapterDefinition = {
  provider: ConversationChannelProvider;
  label: string;
  icon: string;
};

const ADAPTERS: readonly AdapterDefinition[] = [
  { provider: "zalo_bot", label: "Zalo Chatbot", icon: zaloChatbotIcon },
  { provider: "zalo_oa", label: "Zalo OA", icon: zaloOaIcon },
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
  provider: ConversationChannelProvider;
  counts: Readonly<Record<ConversationChannelProvider, number>>;
  onProviderChange: (provider: ConversationChannelProvider) => void;
}) => {
  const selected =
    ADAPTERS.find((adapter) => adapter.provider === provider) ?? ADAPTERS[0];
  const selectedCount = counts[selected.provider];

  return (
    <div className="channel-adapter-selector">
      <RadioGroupPrimitive.Root
        className="channel-adapter-options"
        aria-label="Chọn kênh hội thoại"
        value={provider}
        onValueChange={(value) => {
          if (value === "zalo_bot" || value === "zalo_oa") {
            onProviderChange(value);
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
      <p className="channel-adapter-caption" aria-live="polite">
        Kênh đang chọn: <strong>{selected.label}</strong>
        {selectedCount > 0 ? (
          <span> · {selectedCount} hội thoại cần phản hồi</span>
        ) : null}
      </p>
    </div>
  );
};

export const ChannelAdapterSelector = ({
  provider,
  searchParams,
  onSearchParamsChange,
}: {
  provider: ConversationChannelProvider;
  searchParams: URLSearchParams;
  onSearchParamsChange: (next: URLSearchParams) => void;
}) => {
  // Keep both queries mounted regardless of selection so badges stay warm and
  // adapter switching never briefly shows an aggregate or stale count.
  const zaloBotCount = useScopedAttentionCount("zalo_bot");
  const zaloOaCount = useScopedAttentionCount("zalo_oa");

  return (
    <ChannelAdapterSelectorView
      provider={provider}
      counts={{ zalo_bot: zaloBotCount, zalo_oa: zaloOaCount }}
      onProviderChange={(nextProvider) =>
        onSearchParamsChange(
          getChannelProviderSearchParams(searchParams, nextProvider),
        )
      }
    />
  );
};
