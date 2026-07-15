import type {
  CoreAdminProps,
  AuthProvider,
  DashboardComponent,
  LayoutComponent,
} from "ra-core";
import {
  CustomRoutes,
  localStorageStore,
  Resource,
  usePermissions,
} from "ra-core";
import {
  Component,
  lazy,
  Suspense,
  useLayoutEffect,
  useState,
} from "react";
import type { ComponentType, ReactNode } from "react";
import { Navigate, Route } from "react-router";
import { QueryClient } from "@tanstack/react-query";
import { Admin } from "@/components/admin/admin";

import users from "../users";
import conversations from "../conversations";
import automation from "../automation";
import knowledge from "../knowledge";
import projects from "../projects";
import personas from "../personas";
import integrations from "../integrations";
import { Dashboard } from "../dashboard/Dashboard";
import { PerformancePage } from "../performance/PerformancePage";
import { Layout } from "../layout/Layout";
import {
  getAuthProvider as defaultAuthProviderBuilder,
  getDataProvider as defaultDataProviderBuilder,
} from "../providers/rest";
import type { CrmDataProvider } from "../providers/types";
import { StartPage } from "../login/StartPage.tsx";
import { getAccessToken } from "../providers/rest/api";

const defaultStore = localStorageStore(undefined, "CRM");
const defaultDataProvider = defaultDataProviderBuilder();
const defaultAuthProvider = defaultAuthProviderBuilder();

// --- Module-level singletons (P0 #2) ---------------------------------------
// Hoisting the QueryClient + persister out of the component body prevents
// every re-render from wiping the cache and re-persisting to localStorage.
// This is also a prerequisite for the unified admin (P0 #1): the same client
// must survive the mobile/desktop breakpoint swap.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Avoid refetch-on-every-mount and unbounded window-focus refetches.
      // Realtime updates are driven by Socket.IO invalidations, which call
      // invalidateQueries()/useRefresh() and bypass staleTime, so live data
      // stays fresh without a network round-trip on every navigation.
      staleTime: 30_000, // 30 seconds
      gcTime: 1000 * 60 * 60 * 24, // 24 hours
      networkMode: "offlineFirst",
    },
    mutations: {
      networkMode: "offlineFirst",
    },
  },
});

// --- Route-level code splitting (P1 #5) ------------------------------------
// Secondary pages are lazy-loaded so they land in their own chunks and stay
// out of the initial bundle. Named exports require the `{ named }` mapper.
const ProfilePage = lazy(async () => {
  const mod = await import("../settings/ProfilePage");
  return { default: mod.ProfilePage as ComponentType };
});
const ForgotPasswordPage = lazy(async () => {
  const mod = await import("../login/ForgotPasswordPage");
  return { default: mod.ForgotPasswordPage as ComponentType };
});
// Static path constants — React.lazy wrappers do not expose the original
// component's static `.path` property, so we mirror the values here.
// Source of truth remains the static assignment in each page module; if a
// path changes there, update this constant too.
const PROFILE_PATH = "/profile";
const FORGOT_PASSWORD_PATH = "/forgot-password";
const PUBLIC_HASH_PATHS = new Set(["/login", FORGOT_PASSWORD_PATH]);

const RouteFallback = () => null;

// Lazy route chunks (ProfilePage) can fail to load after a deploy (stale
// chunk hash) or on a flaky connection. A rejected React.lazy
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

const AdminPerformanceRoute = () => {
  const { permissions, isPending } = usePermissions();

  if (isPending) return null;

  return permissions === "admin" ? <PerformancePage /> : <Navigate to="/" replace />;
};

export type CRMProps = {
  dataProvider?: CrmDataProvider;
  authProvider?: AuthProvider;
  i18nProvider: CoreAdminProps["i18nProvider"];
  disableTelemetry?: boolean;
  store?: CoreAdminProps["store"];
  dashboard?: DashboardComponent;
  layout?: LayoutComponent;
};

/**
 * CRM Component
 *
 * This component sets up and renders the main CRM application using `ra-core`. It provides
 * default configurations and themes but allows for customization through props. The component
 * seeds the store with any custom prop values.
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
  dataProvider = defaultDataProvider,
  authProvider = defaultAuthProvider,
  i18nProvider,
  store = defaultStore,
  disableTelemetry,
  layout,
  dashboard,
  ...rest
}: CRMProps) => {
  const [authGateReady, setAuthGateReady] = useState(() => {
    if (typeof window === "undefined") return true;
    const hashPath = window.location.hash.replace(/^#/, "").split("?")[0];
    return Boolean(getAccessToken()) || PUBLIC_HASH_PATHS.has(hashPath);
  });

  useLayoutEffect(() => {
    if (authGateReady) return;
    window.location.hash = "/login";
    setAuthGateReady(true);
  }, [authGateReady]);

  // A single <Admin>, layout, and dashboard component are retained across
  // viewport changes. Responsive behavior belongs inside the shared frame,
  // avoiding a remount of route state while crossing the 768px boundary. The hoisted
  // QueryClient is passed into react-admin's CoreAdminContext, which owns the
  // single QueryClientProvider for the app.
  const resolvedLayout = layout ?? Layout;
  const resolvedDashboard = dashboard ?? Dashboard;

  if (!authGateReady) return null;

  return (
    <Admin
      dataProvider={dataProvider}
      authProvider={authProvider}
      i18nProvider={i18nProvider}
      store={store}
      queryClient={queryClient}
      loginPage={StartPage}
      layout={resolvedLayout}
      dashboard={resolvedDashboard}
      requireAuth
      disableTelemetry={disableTelemetry}
      {...rest}
    >
      <CustomRoutes>
        <Route
          path="/hieu-suat"
          element={
            <RouteBoundary>
              <AdminPerformanceRoute />
            </RouteBoundary>
          }
        />
        <Route
          path={PROFILE_PATH}
          element={
            <RouteBoundary>
              <ProfilePage />
            </RouteBoundary>
          }
        />
        <Route
          path="/settings/profile"
          element={<Navigate to={PROFILE_PATH} replace />}
        />
        <Route
          path="/zalo_integrations/*"
          element={<Navigate to="/settings" replace />}
        />
      </CustomRoutes>
      <CustomRoutes noLayout>
        <Route
          path={FORGOT_PASSWORD_PATH}
          element={
            <RouteBoundary>
              <ForgotPasswordPage />
            </RouteBoundary>
          }
        />
      </CustomRoutes>
      <Resource name="conversations" {...conversations} />
      <Resource name="bot_runs" {...automation} />
      <Resource name="knowledge_sources" {...knowledge} />
      <Resource name="projects" {...projects} />
      <Resource name="personas" {...personas} />
      <Resource name="settings" {...integrations} />
      {/* Users admin: always registered so /users resolves.
            Access is gated inside UserList (CanAccess) and via Header
            menu visibility — ra-core's static-children walker does not
            descend into <CanAccess>, so wrapping here would silently
            disable the route. RLS is the security boundary. */}
      <Resource name="users" {...users} />
    </Admin>
  );
};
