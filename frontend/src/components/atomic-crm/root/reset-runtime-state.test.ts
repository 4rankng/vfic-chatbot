import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const realtime = vi.hoisted(() => ({
  closeRealtimeSocket: vi.fn(),
  getRealtimeSocket: vi.fn(),
}));
vi.mock("@/lib/vfic/realtimeSocket", () => realtime);

import { useMessageStore } from "../conversations/messageStore";
import {
  abandonRuntimeGenerationForTests,
  ensureRuntimeGeneration,
  getActiveRuntimeBundle,
  getRuntimeEpoch,
  resetActiveRuntimeState,
} from "./reset-runtime-state";

describe("runtime generation reset", () => {
  beforeEach(() => {
    abandonRuntimeGenerationForTests();
    useMessageStore.getState().resetAll();
    window.localStorage.clear();
    realtime.closeRealtimeSocket.mockClear();
  });

  afterEach(async () => {
    await resetActiveRuntimeState();
    abandonRuntimeGenerationForTests();
  });

  it("reuses the exact QueryClient and store for the same complete key", async () => {
    const first = await ensureRuntimeGeneration(1);
    first.store.setItem("view", "same-generation");

    const second = await ensureRuntimeGeneration(1);

    expect(second).toBe(first);
    expect(second.queryClient).toBe(first.queryClient);
    expect(second.store).toBe(first.store);
    expect(second.store.getItem("view")).toBe("same-generation");
    expect(realtime.closeRealtimeSocket).not.toHaveBeenCalled();
  });

  it("abandons Query, message, socket and adapter state before mounting G8", async () => {
    const first = await ensureRuntimeGeneration(7);
    first.queryClient.setQueryData(["generation"], "G7");
    useMessageStore.getState().reset("conversation-g7");
    window.localStorage.setItem("vfic:chatops:active-filter:v1", "priority");
    const previousEpoch = getRuntimeEpoch();

    const second = await ensureRuntimeGeneration(8);

    expect(second).not.toBe(first);
    expect(second.queryClient).not.toBe(first.queryClient);
    expect(second.store).not.toBe(first.store);
    expect(first.queryClient.getQueryData(["generation"])).toBeUndefined();
    expect(second.queryClient.getQueryData(["generation"])).toBeUndefined();
    expect(useMessageStore.getState().conversations.size).toBe(0);
    expect(useMessageStore.getState().pendingOptimistic.size).toBe(0);
    expect(window.localStorage.getItem("vfic:chatops:active-filter:v1")).toBeNull();
    expect(getRuntimeEpoch()).toBe(previousEpoch + 1);
    expect(realtime.closeRealtimeSocket).toHaveBeenCalledOnce();
  });

  it("replaces an existing generation when authority changes without reusing its cache", async () => {
    const first = await ensureRuntimeGeneration(1);
    first.queryClient.setQueryData(["old"], "value");

    const replacement = await ensureRuntimeGeneration(2);

    expect(getActiveRuntimeBundle()).toBe(replacement);
    expect(replacement).not.toBe(first);
    expect(first.queryClient.getQueryData(["old"])).toBeUndefined();
    expect(realtime.closeRealtimeSocket).toHaveBeenCalledOnce();
  });

  it("fully abandons business state on an active to suspended transition", async () => {
    const bundle = await ensureRuntimeGeneration(1);
    bundle.queryClient.setQueryData(["active"], true);
    useMessageStore.getState().reset("active-conversation");

    await resetActiveRuntimeState();

    expect(getActiveRuntimeBundle()).toBeNull();
    expect(bundle.queryClient.getQueryData(["active"])).toBeUndefined();
    expect(useMessageStore.getState().conversations.size).toBe(0);
    expect(realtime.closeRealtimeSocket).toHaveBeenCalledOnce();
  });
});
