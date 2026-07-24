import type { PublicRuntimeManifest } from "../installation/runtime-manifest";

const PRODUCT_NAME = "TingHire";
const PRODUCT_DESCRIPTION =
  "TingHire là nền tảng vận hành tuyển dụng giúp đội ngũ kết nối đúng người với đúng cơ hội.";
const PRODUCT_TAGLINE = "Tuyển đúng người. Nhanh hơn.";
const PRODUCT_THEME_COLOR = "#172033";

const PRODUCT_METADATA = [
  ['meta[name="theme-color"]', PRODUCT_THEME_COLOR],
  ['meta[name="description"]', PRODUCT_DESCRIPTION],
  ['meta[property="og:title"]', PRODUCT_NAME],
  ['meta[property="og:description"]', PRODUCT_TAGLINE],
  ['meta[name="twitter:title"]', PRODUCT_NAME],
  ['meta[name="twitter:description"]', PRODUCT_TAGLINE],
] as const;

const setMetaContent = (selector: string, value: string): void => {
  document.head
    .querySelector<HTMLMetaElement>(selector)
    ?.setAttribute("content", value);
};

export const resetRuntimeMetadata = (): void => {
  document.title = PRODUCT_NAME;
  document.documentElement.lang = "vi";
  for (const [selector, content] of PRODUCT_METADATA) {
    setMetaContent(selector, content);
  }
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
  const workspaceName = configuredAppName || configuredDisplayName;
  document.title = workspaceName
    ? `${workspaceName} · ${PRODUCT_NAME}`
    : PRODUCT_NAME;
  document.documentElement.lang = manifest.locale;
};
