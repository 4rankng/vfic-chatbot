import { ArrowLeft } from "@untitledui/icons";
import type { ReactNode } from "react";
import { Button } from "@/components/base/buttons/button";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { cx } from "@/utils/cx";

/**
 * Sticky phone header for top-level and drilled-in console pages — the one
 * chrome language for mobile page tops (back / title / actions), adapted from
 * the vendored PRO mobile header
 * (`components/application/app-navigation/base-components/mobile-header.tsx`),
 * not installed verbatim from the template.
 *
 * Render only under `useIsMobile()`; the desktop topbar/rail stays untouched.
 * The title renders as the page's `h1`: the settings navigation contract pins a
 * `heading` role named after the active section
 * (`SettingsConsolePage.navigation.test.tsx`).
 *
 * Touch contract: every interactive child is a 44px target (`size-11`).
 */
export const MobilePageHeader = ({
  title,
  onBack,
  primaryAction,
  utilityAction,
  className,
}: {
  title: string;
  onBack?: () => void;
  primaryAction?: ReactNode;
  utilityAction?: ReactNode;
  className?: string;
}) => {
  return (
    <header
      className={cx(
        // `workspace-chrome` rebinds the Untitled UI vocabulary to the ink
        // shell (navy bg, ivory ink) — the same chrome the topbar and drawer
        // speak, so every page top reads as one system.
        "uu-scope workspace-chrome sticky top-0 z-30 flex min-h-14 items-center gap-2 border-b border-secondary bg-primary px-2 pt-[env(safe-area-inset-top)]",
        className,
      )}
    >
      {onBack ? (
        <Button
          size="md"
          color="secondary"
          iconLeading={ArrowLeft}
          aria-label="Quay lại"
          onPress={onBack}
          className="size-11! shrink-0 justify-center"
        />
      ) : null}

      <h1 className="min-w-0 flex-1 truncate text-md font-semibold text-primary">
        {title}
      </h1>

      {primaryAction}

      {utilityAction ? (
        <ButtonUtility
          size="sm"
          icon={utilityAction}
          className="size-11! shrink-0 justify-center"
        />
      ) : null}
    </header>
  );
};
