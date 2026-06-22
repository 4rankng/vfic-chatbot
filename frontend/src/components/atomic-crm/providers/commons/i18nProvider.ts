import { mergeTranslations } from "ra-core";
import polyglotI18nProvider from "ra-i18n-polyglot";
import englishMessages from "ra-language-english";
import { raSupabaseEnglishMessages } from "ra-supabase-language-english";
import { englishCrmMessages } from "./englishCrmMessages";
import { vietnameseCrmMessages } from "./vietnameseCrmMessages";

const raSupabaseEnglishMessagesOverride = {
  "ra-supabase": {
    auth: {
      password_reset: "Check your emails for a Reset Password message.",
    },
  },
};

const englishCatalog = mergeTranslations(
  englishMessages,
  raSupabaseEnglishMessages,
  raSupabaseEnglishMessagesOverride,
  englishCrmMessages,
);

const vietnameseCatalog = mergeTranslations(
  englishCatalog,
  vietnameseCrmMessages,
);

export const getInitialLocale = (): "vi" => {
  return "vi";
};

export const i18nProvider = polyglotI18nProvider(
  () => vietnameseCatalog,
  "vi",
  [{ locale: "vi", name: "Tiếng Việt" }],
  { allowMissing: true },
);

export const testI18nProvider = polyglotI18nProvider(
  () => vietnameseCatalog,
  "vi",
  [{ locale: "vi", name: "Tiếng Việt" }],
  { allowMissing: true },
);
