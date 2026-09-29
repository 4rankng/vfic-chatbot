import type { ReactNode } from "react";

import { Label } from "@/components/base/input/label";
import { Toggle } from "@/components/base/toggle/toggle";
import { useIsMobile } from "@/hooks/use-mobile";

/**
 * Shared settings chrome: the collapsible card, the section panel that hosts a
 * settings view, and the labelled switch row every provider card uses.
 */

export const SettingsGroup = ({
  id,
  title,
  description,
  icon,
  meta,
  children,
  className = "",
  defaultOpen = false,
}: {
  id?: string;
  title: string;
  description?: string;
  icon: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) => {
  const isMobile = useIsMobile();
  const header = (
    <div className="settings-group-header">
      <div className="settings-group-title-group">
        <div className="settings-group-icon">{icon}</div>
        <div className="min-w-0">
          <div data-slot="settings-group-title">{title}</div>
          {description ? (
            <p className="settings-group-description">{description}</p>
          ) : null}
        </div>
      </div>
      {meta ? <div className="settings-group-meta">{meta}</div> : null}
    </div>
  );

  if (isMobile) {
    return (
      <details
        className={`settings-group settings-mobile-group tt-collapse tt-collapse-arrow ${className}`}
        id={id}
        open={defaultOpen}
      >
        <summary className="settings-mobile-group-summary tt-collapse-title">
          {header}
        </summary>
        <div className="settings-group-content tt-collapse-content">
          {children}
        </div>
      </details>
    );
  }

  return (
    <section className={`settings-group ${className}`} id={id}>
      {header}
      <div className="settings-group-content">{children}</div>
    </section>
  );
};

export const SettingsSectionPanel = ({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) => (
  <section className="settings-section-panel" id={id}>
    {children}
  </section>
);

export const ProviderSwitchField = ({
  id,
  label,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  id: string;
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) => (
  <div className="settings-switch-row">
    <div className="min-w-0">
      <Label htmlFor={id}>{label}</Label>
    </div>
    {/*
      `uu-scope` re-binds the four utility names this console and Untitled UI
      both define, so the track paints its own surface instead of the brand
      coral. The toggle owns no `validationBehavior`: React Aria's switch props
      omit it, and a toggle always has a value, so there is no empty control for
      a native validation bubble to fire on.
    */}
    <Toggle
      id={id}
      className="uu-scope"
      isSelected={checked}
      isDisabled={disabled}
      onChange={onCheckedChange}
    />
  </div>
);
