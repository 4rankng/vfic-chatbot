import {
  parseRuntimeManifest,
  RuntimeManifestError,
  type PublicRuntimeManifest,
} from "./runtime-manifest-policy";

export type FetchRuntimeManifestOptions = {
  timeoutMs?: number;
};

export type RuntimeManifestHttpResponse = Readonly<{
  ok: boolean;
  status: number;
  cacheControl: string | null;
  json: () => Promise<unknown>;
}>;

export type RuntimeManifestGateway = Readonly<{
  readRuntimeManifest: (
    options: Readonly<{ timeoutMs: number }>,
  ) => Promise<RuntimeManifestHttpResponse>;
}>;

const DEFAULT_TIMEOUT_MS = 5_000;

export const loadRuntimeManifest = async (
  gateway: RuntimeManifestGateway,
  options: FetchRuntimeManifestOptions = {},
): Promise<PublicRuntimeManifest> => {
  const response = await gateway.readRuntimeManifest({
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  });
  if (!response.ok) {
    throw new RuntimeManifestError(
      `Installation runtime request failed with status ${response.status}`,
    );
  }
  const cacheControl = response.cacheControl?.toLowerCase() ?? "";
  if (!cacheControl.includes("no-store")) {
    throw new RuntimeManifestError(
      "Installation runtime response is cacheable",
    );
  }
  return parseRuntimeManifest(await response.json());
};
