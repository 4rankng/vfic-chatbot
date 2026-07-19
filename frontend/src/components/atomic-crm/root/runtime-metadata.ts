import type { PublicRuntimeManifest } from "../installation/runtime-manifest";

const METADATA_SELECTORS = [
  'meta[name="theme-color"]',
  'meta[name="description"]',
  'meta[property="og:title"]',
  'meta[property="og:description"]',
  'meta[name="twitter:title"]',
  'meta[name="twitter:description"]',
] as const;

const setMetaContent = (selector: string, value: string): void => {
  document.head.querySelector<HTMLMetaElement>(selector)?.setAttribute("content", value);
};

export const resetRuntimeMetadata = (): void => {
  document.title = "Ting Ting";
  document.documentElement.lang = "vi";
  for (const selector of METADATA_SELECTORS) setMetaContent(selector, "");
  document.head
    .querySelectorAll('[data-runtime-metadata="favicon"]')
    .forEach((element) => element.remove());
};

export const applyRuntimeMetadata = (manifest: PublicRuntimeManifest): void => {
  resetRuntimeMetadata();
  if (
    manifest.lifecycle !== "ACTIVE" ||
    manifest.customer_identity === null ||
    manifest.branding === null ||
    manifest.locale === null
  ) {
    return;
  }

  const configuredAppName = manifest.branding.app_name?.trim();
  const configuredDisplayName = manifest.customer_identity.display_name.trim();
  document.title = configuredAppName || configuredDisplayName;
  document.documentElement.lang = manifest.locale;

  const primaryColor = manifest.branding.primary_color?.trim();
  if (primaryColor) setMetaContent('meta[name="theme-color"]', primaryColor);
};
