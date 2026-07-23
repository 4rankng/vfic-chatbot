import {
  loadRuntimeManifest,
  type FetchRuntimeManifestOptions,
} from "./runtime-manifest-application";
import { createBrowserRuntimeManifestGateway } from "./runtime-manifest-browser";

export {
  isLegacyWorkspaceRuntime,
  parseRuntimeManifest,
  RuntimeManifestError,
  type PublicRuntimeManifest,
} from "./runtime-manifest-policy";
export type { FetchRuntimeManifestOptions } from "./runtime-manifest-application";

export const fetchRuntimeManifest = async (
  options: FetchRuntimeManifestOptions = {},
) => loadRuntimeManifest(createBrowserRuntimeManifestGateway(), options);
