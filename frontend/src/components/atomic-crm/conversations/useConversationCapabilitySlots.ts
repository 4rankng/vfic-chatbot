import { useCompiledRuntime } from "../capabilities/runtime-context";
import type { ConversationSlots } from "../capabilities/types";

/**
 * Lives apart from `conversation-capability.tsx` so that file exports only
 * components — mixing a hook into it disables Fast Refresh
 * (react-refresh/only-export-components).
 */
export const useConversationCapabilitySlots = (): ConversationSlots =>
  useCompiledRuntime().conversationSlots;
