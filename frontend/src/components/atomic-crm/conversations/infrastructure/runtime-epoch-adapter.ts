import type { RuntimeEpochPort } from "../application/ports";

let runtimeEpochPort: RuntimeEpochPort | null = null;

export const bindConversationRuntimeEpoch = (port: RuntimeEpochPort): void => {
  runtimeEpochPort = port;
};

const requireRuntimeEpochPort = (): RuntimeEpochPort => {
  if (!runtimeEpochPort) {
    throw new Error("Conversation runtime epoch port is not bound");
  }
  return runtimeEpochPort;
};

export const conversationRuntimeEpoch: RuntimeEpochPort = {
  capture: () => requireRuntimeEpochPort().capture(),
  isCurrent: (epoch) => requireRuntimeEpochPort().isCurrent(epoch),
};
