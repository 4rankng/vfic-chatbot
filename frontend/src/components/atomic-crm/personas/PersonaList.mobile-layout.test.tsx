import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "../conversations/inbox.css";
import "../integrations/settings.css";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";

describe("PersonaList mobile layout", () => {
  afterEach(async () => {
    window.scrollTo(0, 0);
    cleanup();
    await page.viewport(1280, 720);
  });

  it("lets the embedded Agent overview grow with the settings document", async () => {
    await page.viewport(390, 844);

    const screen = await render(
      <TestMessages>
        <div className="workspace-frame">
          <main className="workspace-frame-content tailkit-workspace-content">
            <div className="settings-workspace-content">
              <section className="settings-embedded-resource">
                <div className="persona-workspace-content">
                  <div
                    style={{
                      display: "flex",
                      height: "1800px",
                      flexDirection: "column",
                      justifyContent: "space-between",
                    }}
                  >
                    Nội dung Agent dài
                    <span data-testid="persona-content-end">
                      Kết thúc nội dung Agent
                    </span>
                  </div>
                </div>
              </section>
            </div>
          </main>
        </div>
      </TestMessages>,
    );

    const content = screen.container.querySelector(
      ".persona-workspace-content",
    );
    expect(content).toBeInstanceOf(HTMLElement);

    const embeddedContent = content as HTMLElement;
    expect(window.getComputedStyle(embeddedContent).maxHeight).toBe("none");
    expect(window.getComputedStyle(embeddedContent).overflowY).toBe("visible");
    expect(embeddedContent.scrollHeight).toBe(embeddedContent.clientHeight);

    // Below the rail breakpoint the workspace scrolls with the document, so the
    // end of a long embedded list stays reachable.
    const scrollingElement = document.scrollingElement!;
    expect(scrollingElement.scrollHeight).toBeGreaterThan(
      scrollingElement.clientHeight,
    );

    window.scrollTo(0, scrollingElement.scrollHeight);

    const contentEnd = screen.getByTestId("persona-content-end").element();
    await expect
      .poll(() => contentEnd.getBoundingClientRect().bottom)
      .toBeLessThanOrEqual(scrollingElement.clientHeight);
  });
});
