import polyglotI18nProvider from "ra-i18n-polyglot";
import type { TranslationMessages } from "ra-core";
import { vietnameseCrmMessages } from "./vietnameseCrmMessages";

const vietnameseCatalog =
  vietnameseCrmMessages as unknown as TranslationMessages;

export const SUPPORTED_RUNTIME_LOCALES = ["vi-VN"] as const;
export type SupportedRuntimeLocale = (typeof SUPPORTED_RUNTIME_LOCALES)[number];

export const assertSupportedRuntimeLocale = (
  locale: string,
): SupportedRuntimeLocale => {
  if (!SUPPORTED_RUNTIME_LOCALES.includes(locale as SupportedRuntimeLocale)) {
    throw new RangeError(`Unsupported runtime locale: ${locale}`);
  }
  return locale as SupportedRuntimeLocale;
};

export const getInitialLocale = (locale: string): "vi" => {
  assertSupportedRuntimeLocale(locale);
  return "vi";
};

export const createI18nProvider = (locale: string) => {
  getInitialLocale(locale);
  return polyglotI18nProvider(
    () => vietnameseCatalog,
    "vi",
    [{ locale: "vi", name: "Tiếng Việt" }],
    { allowMissing: true },
  );
};

// The pre-active setup shell is a Vietnamese administration surface. Active
// business UI is created from the validated runtime locale in App.tsx.
export const i18nProvider = createI18nProvider("vi-VN");

export const testI18nProvider = polyglotI18nProvider(
  () => vietnameseCatalog,
  "vi",
  [{ locale: "vi", name: "Tiếng Việt" }],
  { allowMissing: true },
);
