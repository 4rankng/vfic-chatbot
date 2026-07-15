import type { AuthProvider, CoreAdminProps, LayoutComponent } from "ra-core";
import { CustomRoutes, Resource } from "ra-core";
import { useLayoutEffect, useMemo, useState } from "react";
import { Route } from "react-router";

import { Admin } from "@/components/admin/admin";
import { RuntimeCapabilityProvider } from "../capabilities/runtime-context";
import type { RuntimeGenerationBundle } from "../capabilities/types";
import { Layout } from "../layout/Layout";
import { StartPage } from "../login/StartPage";
import {
  getAuthProvider as defaultAuthProviderBuilder,
  getDataProvider as defaultDataProviderBuilder,
} from "../providers/rest";
import { getAccessToken } from "../providers/rest/api";
import type { CrmDataProvider } from "../providers/types";

const defaultDataProvider = defaultDataProviderBuilder();
const PUBLIC_HASH_PATHS = new Set(["/login", "/forgot-password"]);

export type CRMProps = {
  bundle: RuntimeGenerationBundle;
  dataProvider?: CrmDataProvider;
  authProvider?: AuthProvider;
  i18nProvider: CoreAdminProps["i18nProvider"];
  disableTelemetry?: boolean;
  layout?: LayoutComponent;
};

/** One business Admin whose resources, routes, store and query cache all belong
 * to exactly one compiled runtime generation. */
export const CRM = ({
  bundle,
  dataProvider = defaultDataProvider,
  authProvider,
  i18nProvider,
  disableTelemetry,
  layout = Layout,
}: CRMProps) => {
  const { runtime } = bundle;
  const resolvedAuthProvider = useMemo(
    () => authProvider ?? defaultAuthProviderBuilder(runtime.availableResources),
    [authProvider, runtime.availableResources],
  );
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

  if (!authGateReady) return null;

  const layoutRoutes = runtime.routes.filter((route) => route.layout === "layout");
  const noLayoutRoutes = runtime.routes.filter(
    (route) => route.layout === "no-layout",
  );

  return (
    <RuntimeCapabilityProvider runtime={runtime}>
      <Admin
        key={runtime.key}
        dataProvider={dataProvider}
        authProvider={resolvedAuthProvider}
        i18nProvider={i18nProvider}
        store={bundle.store}
        queryClient={bundle.queryClient}
        loginPage={StartPage}
        layout={layout}
        dashboard={runtime.dashboard}
        requireAuth
        disableTelemetry={disableTelemetry}
      >
        <CustomRoutes>
          {layoutRoutes.map(({ id, path, Component }) => (
            <Route key={id} path={path} element={<Component />} />
          ))}
        </CustomRoutes>
        <CustomRoutes noLayout>
          {noLayoutRoutes.map(({ id, path, Component }) => (
            <Route key={id} path={path} element={<Component />} />
          ))}
        </CustomRoutes>
        {runtime.resources.map(({ id, name, props }) => (
          <Resource key={id} name={name} {...props} />
        ))}
      </Admin>
    </RuntimeCapabilityProvider>
  );
};
