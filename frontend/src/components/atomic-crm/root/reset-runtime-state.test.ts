import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const realtime = vi.hoisted(() => ({ closeRealtimeSocket: vi.fn() }));
vi.mock("@/lib/vfic/realtimeSocket", () => realtime);

import { useMessageStore } from "../conversations/messageStore";
import { genericFixtureManifest, genericFixtureRegistry } from "../capabilities/test-fixtures";
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
    const manifest = genericFixtureManifest();
    const registry = genericFixtureRegistry();
    const first = await ensureRuntimeGeneration(manifest, registry);
    first.store.setItem("view", "same-generation");

    const second = await ensureRuntimeGeneration({ ...manifest }, registry);

    expect(second).toBe(first);
    expect(second.queryClient).toBe(first.queryClient);
    expect(second.store).toBe(first.store);
    expect(second.store.getItem("view")).toBe("same-generation");
    expect(realtime.closeRealtimeSocket).not.toHaveBeenCalled();
  });

  it("abandons Query, message, socket and adapter state before mounting G8", async () => {
    const registry = genericFixtureRegistry();
    const first = await ensureRuntimeGeneration(
      genericFixtureManifest({ authority_generation: 7 }),
      registry,
    );
    first.queryClient.setQueryData(["generation"], "G7");
    useMessageStore.getState().reset("conversation-g7");
    window.localStorage.setItem("vfic:chatops:active-filter:v1", "priority");
    const previousEpoch = getRuntimeEpoch();

    const second = await ensureRuntimeGeneration(
      genericFixtureManifest({
        authority_generation: 8,
        revision_id: "00000000-0000-4000-8000-000000000008",
        manifest_checksum: "8".repeat(64),
      }),
      registry,
    );

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

  it("leaves no old generation active when the replacement fails compilation", async () => {
    const registry = genericFixtureRegistry();
    const first = await ensureRuntimeGeneration(genericFixtureManifest(), registry);
    first.queryClient.setQueryData(["old"], "value");

    await expect(
      ensureRuntimeGeneration(
        genericFixtureManifest({
          authority_generation: 2,
          pack_contract_hash: "f".repeat(64),
        }),
        registry,
      ),
    ).rejects.toMatchObject({ code: "PACK_HASH_MISMATCH" });

    expect(getActiveRuntimeBundle()).toBeNull();
    expect(first.queryClient.getQueryData(["old"])).toBeUndefined();
    expect(realtime.closeRealtimeSocket).toHaveBeenCalledOnce();
  });

  it("fully abandons business state on an active to suspended transition", async () => {
    const bundle = await ensureRuntimeGeneration(
      genericFixtureManifest(),
      genericFixtureRegistry(),
    );
    bundle.queryClient.setQueryData(["active"], true);
    useMessageStore.getState().reset("active-conversation");

    await resetActiveRuntimeState();

    expect(getActiveRuntimeBundle()).toBeNull();
    expect(bundle.queryClient.getQueryData(["active"])).toBeUndefined();
    expect(useMessageStore.getState().conversations.size).toBe(0);
    expect(realtime.closeRealtimeSocket).toHaveBeenCalledOnce();
  });
});
