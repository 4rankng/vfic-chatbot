/**
 * Isolated mirror of the backend's canonical, non-executable recruitment@1
 * parity export. Executable imports remain frontend-owned in registry.ts.
 */
export const RECRUITMENT_V1_PARITY = Object.freeze({
  schemaVersion: 1,
  packKey: "recruitment",
  packVersion: "1",
  kernelAbi: "1" as const,
  packContractHash:
    "2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9",
  parityChecksum:
    "2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9",
  capabilityIds: [
    "conversation",
    "knowledge",
    "candidate_intake",
    "job_advisory",
    "channel.zalo",
  ] as const,
});
