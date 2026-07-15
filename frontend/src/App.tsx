import { CRM } from "@/components/atomic-crm/root/CRM";
import {
  hasReadyActiveRuntime,
  useInstallationContext,
} from "@/components/atomic-crm/installation/installation-context";
import { SetupApplication } from "@/components/atomic-crm/installation/SetupLayout";
import { createI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";
import { useMemo } from "react";

/**
 * Application entry point
 *
 * Customize Atomic CRM by passing props to the CRM component:
 *  - companySectors
 *  - darkTheme
 *  - dealCategories
 *  - dealPipelineStatuses
 *  - dealStages
 *  - lightTheme
 *  - logo
 *  - noteStatuses
 *  - taskTypes
 *  - title
 * ... as well as all the props accepted by shadcn-admin-kit's <Admin> component.
 *
 * @example
 * const App = () => (
 *    <CRM
 *       logo="./img/logo.png"
 *       title="Acme CRM"
 *    />
 * );
 */
const App = () => {
  const { manifest } = useInstallationContext();
  const activeI18nProvider = useMemo(
    () =>
      hasReadyActiveRuntime(manifest) && manifest.locale
        ? createI18nProvider(manifest.locale)
        : null,
    [manifest],
  );
  return hasReadyActiveRuntime(manifest) && activeI18nProvider ? (
    <CRM i18nProvider={activeI18nProvider} />
  ) : (
    <SetupApplication />
  );
};

export default App;
