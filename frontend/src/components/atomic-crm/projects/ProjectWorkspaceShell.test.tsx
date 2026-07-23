import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

describe("ProjectWorkspaceShell", () => {
  afterEach(async () => {
    cleanup();
    await page.viewport(1280, 720);
  });

  it("keeps overflowing project content vertically scrollable", async () => {
    const screen = await render(
      <main
        className="workspace-frame-content"
        style={{ height: "480px", overflow: "hidden" }}
      >
        <ProjectWorkspaceShell>
          <div className="project-workspace-content">
            <div style={{ height: "1800px" }}>Nội dung dự án dài</div>
          </div>
        </ProjectWorkspaceShell>
      </main>,
    );

    const panel = screen.container.querySelector(".project-center-panel");
    expect(panel).toBeInstanceOf(HTMLElement);

    const projectPanel = panel as HTMLElement;
    projectPanel.style.height = "320px";
    projectPanel.style.maxHeight = "320px";
    expect(projectPanel.scrollHeight).toBeGreaterThan(
      projectPanel.clientHeight,
    );
    expect(window.getComputedStyle(projectPanel).overflowY).toBe("auto");
  });

  it("lets long project content join the document scroll on phones", async () => {
    await page.viewport(390, 844);

    const screen = await render(
      <ProjectWorkspaceShell>
        <div className="project-workspace-content">
          <div style={{ height: "1800px" }}>Nội dung dự án dài</div>
        </div>
      </ProjectWorkspaceShell>,
    );

    const workspace = screen.container.querySelector(".project-workspace");
    const app = screen.container.querySelector(".project-app");
    expect(workspace).toBeInstanceOf(HTMLElement);
    expect(app).toBeInstanceOf(HTMLElement);

    expect(window.getComputedStyle(workspace as HTMLElement).overflowY).toBe(
      "visible",
    );
    expect(window.getComputedStyle(app as HTMLElement).overflowY).toBe(
      "visible",
    );
    expect(document.scrollingElement!.scrollHeight).toBeGreaterThan(
      document.scrollingElement!.clientHeight,
    );
  });
});
