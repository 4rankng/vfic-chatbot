import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { Navigate } from "react-router";

import { contributions } from "./index";

const navigation = (id: string) => {
  const item = contributions[`kernel.navigation.${id}`];
  expect(item.kind).toBe("navigation");
  if (item.kind !== "navigation") {
    throw new Error(`Expected navigation contribution for ${id}`);
  }
  return item.destination;
};

const route = (id: string) => {
  const item = contributions[id];
  expect(item.kind).toBe("route");
  if (item.kind !== "route") {
    throw new Error(`Expected route contribution for ${id}`);
  }
  return item.route;
};

const renderRouteElement = <TProps extends object>(
  Component: unknown,
): ReactElement<TProps> => (Component as () => ReactElement<TProps>)();

describe("kernel navigation contract", () => {
  it("keeps each dock destination active only on its intended paths", () => {
    expect(navigation("overview").isActive("/")).toBe(true);
    expect(navigation("overview").isActive("/projects")).toBe(false);

    expect(navigation("messages").isActive("/conversations")).toBe(true);
    expect(navigation("messages").isActive("/conversations/42")).toBe(true);
    expect(navigation("messages").isActive("/profile")).toBe(false);

    expect(navigation("projects").isActive("/projects")).toBe(true);
    expect(navigation("projects").isActive("/projects/alpha")).toBe(true);
    expect(navigation("projects").isActive("/settings")).toBe(false);

    expect(navigation("performance").isActive("/hieu-suat")).toBe(true);
    expect(navigation("performance").isActive("/hieu-suat/recent")).toBe(true);
    expect(navigation("performance").isActive("/")).toBe(false);

    expect(navigation("users").isActive("/users")).toBe(true);
    expect(navigation("users").isActive("/users/7")).toBe(true);
    expect(navigation("users").isActive("/profile")).toBe(false);
    expect(navigation("users").isActive("/settings")).toBe(false);

    expect(navigation("bot_runs").isActive("/bot_runs")).toBe(true);
    expect(navigation("bot_runs").isActive("/bot_runs/42")).toBe(true);
    expect(navigation("bot_runs").isActive("/settings")).toBe(false);

    // The profile screen lives in the account menu, not in the sidebar.
    expect(contributions["kernel.navigation.account"]).toBeUndefined();
  });

  it("groups every destination under the sidebar section that owns it", () => {
    expect(navigation("overview").section).toBe("operations");
    expect(navigation("messages").section).toBe("operations");
    expect(navigation("projects").section).toBe("operations");
    expect(navigation("users").section).toBe("team");
    expect(navigation("settings").section).toBe("system");
    expect(navigation("bot_runs").section).toBe("system");
    expect(navigation("performance").section).toBe("system");
  });

  it("keeps admin settings active across every routed settings surface", () => {
    const settings = navigation("settings");

    expect(settings.roles).toEqual(["admin"]);
    expect(settings.isActive("/settings")).toBe(true);
    expect(settings.isActive("/settings/profile")).toBe(true);
    expect(settings.isActive("/zalo_integrations")).toBe(true);
    expect(settings.isActive("/zalo_integrations/legacy")).toBe(true);
    // Users and projects are their own sidebar destinations now,
    // so the settings item must not claim their routes.
    expect(settings.isActive("/users/7")).toBe(false);
    expect(settings.isActive("/projects")).toBe(false);
  });

  it("preserves legacy redirects and route layouts", () => {
    const profileRedirect = route("kernel.route.settings-profile-redirect");
    const settingsRedirect = route(
      "channel.zalo.route.legacy-settings-redirect",
    );
    const performance = route("kernel.route.performance");
    const profile = route("kernel.route.profile");
    const forgotPassword = route("kernel.route.forgot-password");

    expect(profileRedirect.path).toBe("/settings/profile");
    expect(profileRedirect.layout).toBe("layout");
    expect(settingsRedirect.path).toBe("/zalo_integrations/*");
    expect(settingsRedirect.layout).toBe("layout");
    expect(performance.path).toBe("/hieu-suat");
    expect(performance.layout).toBe("layout");
    expect(profile.path).toBe("/profile");
    expect(profile.layout).toBe("layout");
    expect(forgotPassword.layout).toBe("no-layout");

    const profileElement = renderRouteElement<{ to: string; replace: boolean }>(
      profileRedirect.Component,
    );
    const settingsElement = renderRouteElement<{
      to: string;
      replace: boolean;
    }>(settingsRedirect.Component);
    const profileRouteElement = renderRouteElement<{
      children: ReactElement;
    }>(profile.Component);
    const forgotPasswordElement = renderRouteElement<{
      children: ReactElement;
    }>(forgotPassword.Component);

    expect(profileElement.type).toBe(Navigate);
    expect(profileElement.props.to).toBe("/profile");
    expect(profileElement.props.replace).toBe(true);
    expect(settingsElement.type).toBe(Navigate);
    expect(settingsElement.props.to).toBe("/settings");
    expect(settingsElement.props.replace).toBe(true);
    expect(profileRouteElement.props.children.type).toBeDefined();
    expect(forgotPasswordElement.props.children.type).toBeDefined();
  });

  it("keeps the kernel resource registry wired to the expected resources", () => {
    expect(contributions["kernel.resource.conversations"]).toMatchObject({
      kind: "resource",
      resource: { name: "conversations" },
    });
    expect(contributions["kernel.resource.bot-runs"]).toMatchObject({
      kind: "resource",
      resource: { name: "bot_runs" },
    });
    expect(contributions["kernel.resource.settings"]).toMatchObject({
      kind: "resource",
      resource: { name: "settings" },
    });
    expect(contributions["kernel.resource.users"]).toMatchObject({
      kind: "resource",
      resource: { name: "users" },
    });
  });
});
