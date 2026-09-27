import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
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
    <Switch
      id={id}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
    />
  </div>
);
