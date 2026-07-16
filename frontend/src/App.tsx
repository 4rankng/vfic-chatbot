import { CRM } from "@/components/atomic-crm/root/CRM";
import {
  hasReadyActiveRuntime,
  useInstallationContext,
} from "@/components/atomic-crm/installation/installation-context";
import { legacyRecruitmentWorkspaceManifest } from "@/components/atomic-crm/installation/runtime-manifest";
import { createI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";
import { useMemo } from "react";
import { useEffect, useState } from "react";
import type { RuntimeGenerationBundle } from "@/components/atomic-crm/capabilities/types";
import { ensureRuntimeGeneration } from "@/components/atomic-crm/root/reset-runtime-state";
import { getRuntimeKey } from "@/components/atomic-crm/capabilities/compile-capabilities";
import type { PublicRuntimeManifest } from "@/components/atomic-crm/installation/runtime-manifest";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

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
const ReadyRuntimeApplication = ({
  manifest,
  refreshRuntime,
}: {
  manifest: PublicRuntimeManifest;
  refreshRuntime: () => Promise<void>;
}) => {
  const [bundle, setBundle] = useState<RuntimeGenerationBundle | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [compileAttempt, setCompileAttempt] = useState(0);
  const activeI18nProvider = useMemo(
    () =>
      hasReadyActiveRuntime(manifest) && manifest.locale
        ? createI18nProvider(manifest.locale)
        : null,
    [manifest],
  );

  useEffect(() => {
    let cancelled = false;
    setBlocked(false);
    setBundle(null);
    void ensureRuntimeGeneration(manifest)
      .then((nextBundle) => {
        if (!cancelled) setBundle(nextBundle);
      })
      .catch(() => {
        if (!cancelled) {
          setBundle(null);
          setBlocked(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [compileAttempt, manifest]);

  const retryCompilation = async () => {
    await refreshRuntime();
    setCompileAttempt((attempt) => attempt + 1);
  };

  if (blocked) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-background p-5">
        <section className="w-full max-w-lg rounded-xl border bg-card p-6 text-center shadow-sm">
          <h1 className="text-content-title font-semibold">Không thể tải không gian tuyển dụng</h1>
          <p className="mt-2 text-body leading-6 text-muted-foreground">
            Giao diện tuyển dụng chưa tải được. Hệ thống không dùng dữ liệu cũ để bảo đảm an toàn.
          </p>
          <Button className="mt-5" onClick={() => void retryCompilation()}>
            Tải lại không gian làm việc
          </Button>
        </section>
      </main>
    );
  }
  if (!bundle || !activeI18nProvider) {
    return <RuntimeCompilationLoading />;
  }
  return <CRM bundle={bundle} i18nProvider={activeI18nProvider} />;
};

export const RuntimeCompilationLoading = () => (
  <main className="flex min-h-svh items-center justify-center bg-background p-5" aria-live="polite">
    <section className="flex items-center gap-3 rounded-xl border bg-card px-5 py-4 shadow-sm" role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden="true" />
      <span>Đang chuẩn bị không gian tuyển dụng</span>
    </section>
  </main>
);

const App = () => {
  const { manifest, refreshRuntime } = useInstallationContext();
  const recruitmentManifest = useMemo(() => legacyRecruitmentWorkspaceManifest(), []);
  const key = `${getRuntimeKey(recruitmentManifest)}:${manifest.authority_generation}`;

  return (
    <ReadyRuntimeApplication
      key={key}
      manifest={recruitmentManifest}
      refreshRuntime={refreshRuntime}
    />
  );
};

export default App;
