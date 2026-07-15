import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { applyRuntimeMetadata, resetRuntimeMetadata } from "../root/runtime-metadata";
import { InstallationProvider } from "./InstallationContext";
import type { InstallationContextValue } from "./installation-context";
import {
  fetchRuntimeManifest,
  type PublicRuntimeManifest,
} from "./runtime-manifest";
import { getRuntimeKey } from "../capabilities/compile-capabilities";
import { resetActiveRuntimeState } from "../root/reset-runtime-state";

const LEGACY_CONFIGURATION_KEY = "app.configuration";
const AUTOMATIC_ATTEMPTS = 2;

type BootstrapState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; manifest: PublicRuntimeManifest };

const NeutralSurface = ({
  busy,
  onRetry,
}: {
  busy: boolean;
  onRetry?: () => void;
}) => (
  <main className="flex min-h-svh items-center justify-center bg-background px-5 py-10 text-foreground">
    <section
      className="w-full max-w-lg rounded-xl border bg-card p-6 shadow-sm sm:p-8"
      aria-busy={busy}
      aria-live="polite"
    >
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-muted">
          {busy ? (
            <Loader2 className="size-5 animate-spin" aria-hidden="true" />
          ) : (
            <AlertTriangle className="size-5" aria-hidden="true" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-content-title font-semibold tracking-tight">
            {busy ? "Đang kiểm tra cấu hình" : "Không thể xác minh cấu hình"}
          </h1>
          <p className="mt-2 text-body leading-6 text-muted-foreground">
            {busy
              ? "Hệ thống đang tải cấu hình an toàn từ máy chủ."
              : "Không gian làm việc chưa được mở để tránh dùng cấu hình cũ hoặc không đầy đủ."}
          </p>
          {!busy && onRetry ? (
            <Button
              type="button"
              className="mt-5 min-h-11 w-full sm:w-auto"
              onClick={onRetry}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Thử lại
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  </main>
);

export const InstallationBootstrap = ({ children }: { children: ReactNode }) => {
  const [state, setState] = useState<BootstrapState>({ status: "loading" });
  const currentManifestRef = useRef<PublicRuntimeManifest | null>(null);
  const inFlightRef = useRef<Promise<void> | null>(null);

  const load = useCallback(async (): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current;
    const operation = (async () => {
      if (!currentManifestRef.current) {
        setState({ status: "loading" });
        resetRuntimeMetadata();
      }

      let lastError: unknown;
      for (let attempt = 0; attempt < AUTOMATIC_ATTEMPTS; attempt += 1) {
        try {
          const manifest = await fetchRuntimeManifest();
          const previous = currentManifestRef.current;
          if (previous && getRuntimeKey(previous) !== getRuntimeKey(manifest)) {
            setState({ status: "loading" });
            await resetActiveRuntimeState();
          }
          currentManifestRef.current = manifest;
          applyRuntimeMetadata(manifest);
          setState({ status: "ready", manifest });
          return;
        } catch (error) {
          lastError = error;
        }
      }
      void lastError;
      currentManifestRef.current = null;
      setState({ status: "error" });
      await resetActiveRuntimeState();
      resetRuntimeMetadata();
    })();
    inFlightRef.current = operation;
    try {
      await operation;
    } finally {
      inFlightRef.current = null;
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.removeItem(LEGACY_CONFIGURATION_KEY);
    } catch {
      // Storage can be unavailable in hardened browsers. Runtime authority is
      // still network-only and never reads this legacy key.
    }
    void load();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      resetRuntimeMetadata();
    };
  }, [load]);

  const contextValue = useMemo<InstallationContextValue | null>(
    () =>
      state.status === "ready"
        ? { manifest: state.manifest, refreshRuntime: load }
        : null,
    [load, state],
  );

  if (state.status === "loading") return <NeutralSurface busy />;
  if (state.status === "error") {
    return <NeutralSurface busy={false} onRetry={() => void load()} />;
  }

  return (
    <InstallationProvider value={contextValue!}>{children}</InstallationProvider>
  );
};
