import type { ReactNode } from "react";
import { I18nContextProvider } from "ra-core";

import { testI18nProvider } from "./i18nProvider";

/**
 * Mounts a component with the shipped Vietnamese catalog, so a test asserts the
 * same wording the app renders. The app is Vietnamese-only (see AGENTS.md), and
 * `i18nProvider` pins the locale to `vi`; ra-core's default i18n context has no
 * messages, so a component using `useTranslate` outside this wrapper would
 * render raw catalog keys.
 */
export const TestMessages = ({ children }: { children: ReactNode }) => (
  <I18nContextProvider value={testI18nProvider}>{children}</I18nContextProvider>
);
