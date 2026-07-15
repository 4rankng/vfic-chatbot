import { describe, expect, it } from "vitest";

import {
  CONFIGURATION_STORE_KEY,
  type ConfigurationContextValue,
} from "./ConfigurationContext";
import { defaultConfiguration } from "./defaultConfiguration";
import crmSource from "./CRM.tsx?raw";

/**
 * Phase-1 migration oracle. These assertions identify the browser-owned
 * fallback contract that the installation bootstrap must replace; they do not
 * define acceptable Release-B behavior.
 */
describe("legacy runtime configuration boundary", () => {
  it("stores active-looking business configuration under a browser-local key", () => {
    expect(CONFIGURATION_STORE_KEY).toBe("app.configuration");
  });

  it("injects a complete configuration even when no server configuration exists", () => {
    const current: ConfigurationContextValue = defaultConfiguration;

    expect(current.title).toBe("Ting Ting Soft");
    expect(current.currency).toBe("USD");
    expect(current.darkModeLogo).toBe("/dark-logo.png");
    expect(current.lightModeLogo).toBe("/light-logo.png");
    expect(current.dealStages.length).toBeGreaterThan(0);
    expect(current.taskTypes.length).toBeGreaterThan(0);
  });

  it("has no explicit unconfigured lifecycle state", () => {
    expect("lifecycle" in defaultConfiguration).toBe(false);
    expect("revision" in defaultConfiguration).toBe(false);
    expect("pack" in defaultConfiguration).toBe(false);
  });
});

describe("legacy React Admin resource registry", () => {
  it("pins every statically registered resource for later capability gating", () => {
    const resourceNames = [...crmSource.matchAll(/<Resource\s+name="([^"]+)"/g)].map(
      (match) => match[1],
    );

    expect(resourceNames).toEqual([
      "conversations",
      "bot_runs",
      "knowledge_sources",
      "projects",
      "personas",
      "settings",
      "users",
    ]);
  });
});
