import type {
  CoreAdminProps,
  AuthProvider,
  DashboardComponent,
  LayoutComponent,
} from "ra-core";
import { CustomRoutes, localStorageStore, Resource } from "ra-core";
import { Component, lazy, Suspense, useEffect, useMemo } from "react";
import type { ComponentType, ReactNode } from "react";
import { Route } from "react-router";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { Admin } from "@/components/admin/admin";

import leads from "../leads";
import profiles from "../profiles";
import conversations from "../conversations";
import automation from "../automation";
import knowledge from "../knowledge";
import { Dashboard } from "../dashboard/Dashboard";
import { MobileDashboard } from "../dashboard/MobileDashboard";
import { Layout } from "../layout/Layout";
import { MobileLayout } from "../layout/MobileLayout";
import { ChangelogPage } from "../misc/ChangelogPage";
import {
  getAuthProvider as defaultAuthProviderBuilder,
  getDataProvider as defaultDataProviderBuilder,
} from "../providers/supabase";
import {
  CONFIGURATION_STORE_KEY,
  type ConfigurationContextValue,
} from "./ConfigurationContext";
import type { CrmDataProvider } from "../providers/types";
import {
  defaultCompanySectors,
  defaultCurrency,
  defaultDarkModeLogo,
  defaultDealCategories,
  defaultDealPipelineStatuses,
  defaultDealStages,
  defaultLightModeLogo,
  defaultNoteStatuses,
  defaultTaskTypes,
  defaultTitle,
} from "./defaultConfiguration";
import { i18nProvider as defaulti18nProvider } from "../providers/commons/i18nProvider";
import { StartPage } from "../login/StartPage.tsx";
import { useIsMobile } from "@/hooks/use-mobile.ts";

const defaultStore = localStorageStore(undefined, "CRM");

// --- Module-level singletons (P0 #2) ---------------------------------------
// Hoisting the QueryClient + persister out of the component body prevents
// every re-render from wiping the cache and re-persisting to localStorage.
// This is also a prerequisite for the unified admin (P0 #1): the same client
// must survive the mobile/desktop breakpoint swap.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 1000 * 60 * 60 * 24, // 24 hours
      networkMode: "offlineFirst",
    },
    mutations: {
      networkMode: "offlineFirst",
    },
  },
});

const asyncStoragePersister = createAsyncStoragePersister({
  storage: localStorage,
});

// --- Route-level code splitting (P1 #5) ------------------------------------
// Secondary pages are lazy-loaded so they land in their own chunks and stay
// out of the initial bundle. Named exports require the `{ named }` mapper.
const ProfilePage = lazy(async () => {
  const mod = await import("../settings/ProfilePage");
  return { default: mod.ProfilePage as ComponentType };
});
const SettingsPage = lazy(async () => {
  const mod = await import("../settings/SettingsPage");
  return { default: mod.SettingsPage as ComponentType };
});
const SettingsPageMobile = lazy(async () => {
  const mod = await import("../settings/SettingsPageMobile");
  return { default: mod.SettingsPageMobile as ComponentType };
});
// NOTE: ChangelogPage is imported statically (top of file) rather than lazy
// here — Header.tsx and SettingsPageMobile.tsx already import it eagerly, so
// a lazy() wrapper would be a no-op (Vite keeps it in the main chunk and
// warns). Keeping it static is consistent and avoids the misleading split.

// Static path constants — React.lazy wrappers do not expose the original
// component's static `.path` property, so we mirror the values here.
// Source of truth remains the static assignment in each page module; if a
// path changes there, update this constant too.
const PROFILE_PATH = "/profile";
const SETTINGS_PATH = "/settings";
const CHANGELOG_PATH = "/changelog";

const RouteFallback = () => null;

// Lazy route chunks (ProfilePage, SettingsPage*) can fail to load after a
// deploy (stale chunk hash) or on a flaky connection. A rejected React.lazy
// import throws during render and — with no boundary — would unmount the
// entire <Admin>. This isolates the failure to the route pane and offers a
// reload, which re-fetches the current valid chunk.
class RouteErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state: { hasError: boolean } = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          style={{ padding: "2rem", textAlign: "center", color: "#666" }}
        >
          <p style={{ marginBottom: "0.75rem" }}>
            Không thể tải trang. Vui lòng tải lại.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              padding: "0.4rem 0.9rem",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            Tải lại trang
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// React Router's <CustomRoutes> is a <Routes>, which accepts only <Route>
// (or <Fragment>) as direct children — wrapping the routes in an error
// boundary or <Suspense> trips the "is not a <Route> component" invariant
// at route-config build time. Wrap each route's *element* instead, so a
// rejected lazy import still isolates the failure to that route pane and
// offers a reload (the original intent of RouteErrorBoundary).
const RouteBoundary = ({ children }: { children: ReactNode }) => (
  <RouteErrorBoundary>
    <Suspense fallback={<RouteFallback />}>{children}</Suspense>
  </RouteErrorBoundary>
);

export type CRMProps = {
  dataProvider?: CrmDataProvider;
  authProvider?: AuthProvider;
  i18nProvider?: CoreAdminProps["i18nProvider"];
  disableTelemetry?: boolean;
  store?: CoreAdminProps["store"];
  dashboard?: DashboardComponent;
  layout?: LayoutComponent;
} & Partial<ConfigurationContextValue>;

/**
 * CRM Component
 *
 * This component sets up and renders the main CRM application using `ra-core`. It provides
 * default configurations and themes but allows for customization through props. The component
 * seeds the store with any custom prop values for backwards compatibility.
 *
 * @param {LabeledValue[]} companySectors - The list of company sectors used in the application.
 * @param {string} currency - The ISO 4217 currency code used to format monetary values (e.g. "USD", "EUR", "GBP").
 * @param {RaThemeOptions} darkTheme - The theme to use when the application is in dark mode.
 * @param {LabeledValue[]} dealCategories - The categories of deals used in the application.
 * @param {string[]} dealPipelineStatuses - The statuses of deals in the pipeline used in the application.
 * @param {DealStage[]} dealStages - The stages of deals used in the application.
 * @param {RaThemeOptions} lightTheme - The theme to use when the application is in light mode.
 * @param {string} logo - The logo used in the CRM application.
 * @param {NoteStatus[]} noteStatuses - The statuses of notes used in the application.
 * @param {LabeledValue[]} taskTypes - The types of tasks used in the application.
 * @param {string} title - The title of the CRM application.
 *
 * @returns {JSX.Element} The rendered CRM application.
 *
 * @example
 * // Basic usage of the CRM component
 * import { CRM } from '@/components/atomic-crm/dashboard/CRM';
 *
 * const App = () => (
 *     <CRM
 *         logo="/path/to/logo.png"
 *         title="My Custom CRM"
 *         lightTheme={{
 *             ...defaultTheme,
 *             palette: {
 *                 primary: { main: '#0000ff' },
 *             },
 *         }}
 *     />
 * );
 *
 * export default App;
 */
export const CRM = ({
  companySectors = defaultCompanySectors,
  currency = defaultCurrency,
  dealCategories = defaultDealCategories,
  dealPipelineStatuses = defaultDealPipelineStatuses,
  dealStages = defaultDealStages,
  darkModeLogo = defaultDarkModeLogo,
  lightModeLogo = defaultLightModeLogo,
  noteStatuses = defaultNoteStatuses,
  taskTypes = defaultTaskTypes,
  title = defaultTitle,
  dataProvider = defaultDataProviderBuilder(),
  authProvider = defaultAuthProviderBuilder(),
  i18nProvider = defaulti18nProvider,
  store = defaultStore,
  googleWorkplaceDomain = import.meta.env.VITE_GOOGLE_WORKPLACE_DOMAIN,
  disableEmailPasswordAuthentication = import.meta.env
    .VITE_DISABLE_EMAIL_PASSWORD_AUTHENTICATION === "true",
  disableTelemetry,
  layout,
  dashboard,
  ...rest
}: CRMProps) => {
  useEffect(() => {
    if (
      disableTelemetry ||
      process.env.NODE_ENV !== "production" ||
      typeof window === "undefined" ||
      typeof window.location === "undefined" ||
      typeof Image === "undefined"
    ) {
      return;
    }
    const img = new Image();
    img.src = `https://atomic-crm-telemetry.marmelab.com/atomic-crm-telemetry?domain=${window.location.hostname}`;
  }, [disableTelemetry]);

  // Seed the store with CRM prop values if not already stored
  // (backwards compatibility for prop-based config)
  useEffect(() => {
    if (!store.getItem(CONFIGURATION_STORE_KEY)) {
      store.setItem(CONFIGURATION_STORE_KEY, {
        companySectors,
        currency,
        dealCategories,
        dealPipelineStatuses,
        dealStages,
        noteStatuses,
        taskTypes,
        title,
        darkModeLogo,
        lightModeLogo,
        googleWorkplaceDomain,
        disableEmailPasswordAuthentication,
      } satisfies ConfigurationContextValue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store]);

  const isMobile = useIsMobile();

  // on login, pre-fetch the configuration to avoid a flickering
  // when accessing the app for the first time
  const wrappedAuthProvider = useMemo<AuthProvider>(
    () => ({
      ...authProvider,
      login: async (params: any) => {
        const result = await authProvider.login(params);
        try {
          const config = await dataProvider.getConfiguration();
          if (Object.keys(config).length > 0) {
            store.setItem(CONFIGURATION_STORE_KEY, config);
          }
        } catch {
          // Non-critical: config will load via useConfigurationLoader
        }
        return result;
      },
      handleCallback: async (params: any) => {
        if (!authProvider.handleCallback) {
          throw new Error(
            "handleCallback is not implemented in the authProvider",
          );
        }
        const result = await authProvider.handleCallback(params);
        try {
          const config = await dataProvider.getConfiguration();
          if (Object.keys(config).length > 0) {
            store.setItem(CONFIGURATION_STORE_KEY, config);
          }
        } catch {
          // Non-critical: config will load via useConfigurationLoader
        }
        return result;
      },
      logout: async (params: any) => {
        try {
          store.removeItem(CONFIGURATION_STORE_KEY);
        } catch {
          // Ignore
        }
        return authProvider.logout(params);
      },
    }),
    [authProvider, dataProvider, store],
  );

  // P0 #1: a single <Admin> is rendered regardless of the viewport so that
  // crossing the 768px breakpoint no longer swaps the component type and
  // unmounts the entire app. The layout + dashboard are chosen by isMobile,
  // and the CustomRoutes union is gated per breakpoint. The hoisted
  // QueryClient + persister wrap the admin so both layouts share the same
  // cache (and persistence applies on desktop too — acceptable per the audit).
  const resolvedLayout = layout ?? (isMobile ? MobileLayout : Layout);
  const resolvedDashboard =
    dashboard ?? (isMobile ? MobileDashboard : Dashboard);

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ persister: asyncStoragePersister }}
    >
      <Admin
        dataProvider={dataProvider}
        authProvider={wrappedAuthProvider}
        i18nProvider={i18nProvider}
        store={store}
        queryClient={queryClient}
        loginPage={StartPage}
        layout={resolvedLayout}
        dashboard={resolvedDashboard}
        requireAuth
        disableTelemetry
        {...rest}
      >
        <CustomRoutes>
          {!isMobile && (
            <Route
              path={PROFILE_PATH}
              element={
                <RouteBoundary>
                  <ProfilePage />
                </RouteBoundary>
              }
            />
          )}
          {!isMobile && (
            <Route
              path={SETTINGS_PATH}
              element={
                <RouteBoundary>
                  <SettingsPage />
                </RouteBoundary>
              }
            />
          )}
          {isMobile && (
            <Route
              path={SETTINGS_PATH}
              element={
                <RouteBoundary>
                  <SettingsPageMobile />
                </RouteBoundary>
              }
            />
          )}
          <Route path={CHANGELOG_PATH} element={<ChangelogPage />} />
        </CustomRoutes>
        <Resource name="leads" {...leads} />
        <Resource name="conversations" {...conversations} />
        <Resource name="bot_runs" {...automation} />
        <Resource name="knowledge_sources" {...knowledge} />
        {/* Users admin: always registered so /users resolves.
            Access is gated inside ProfileList (CanAccess) and via Header
            menu visibility — ra-core's static-children walker does not
            descend into <CanAccess>, so wrapping here would silently
            disable the route. RLS is the security boundary. */}
        <Resource name="users" {...profiles} />
      </Admin>
    </PersistQueryClientProvider>
  );
};
