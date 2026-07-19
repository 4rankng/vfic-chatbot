import { render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import { ThemeProvider } from "./theme-provider";

describe("ThemeProvider", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.classList.remove("light", "dark");
    delete document.documentElement.dataset.theme;
  });

  it("always replaces stored or system dark state with the light theme", async () => {
    document.documentElement.classList.add("dark");
    document.documentElement.dataset.theme = "tingting-dark";

    await render(
      <ThemeProvider>
        <div>content</div>
      </ThemeProvider>,
    );

    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.dataset.theme).toBe("tingting");
  });
});
