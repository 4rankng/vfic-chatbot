declare module "vitest/internal/browser" {
  interface BrowserCommands {
    setTimezone(timezoneId: string): Promise<void>;
  }
}

declare module "*?raw" {
  const content: string;
  export default content;
}
