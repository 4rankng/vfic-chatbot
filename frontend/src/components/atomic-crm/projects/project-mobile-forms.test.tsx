import type { ReactNode } from "react";
import { CoreAdminContext } from "ra-core";
import type * as RaCoreModule from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page, userEvent } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "@/flat-surfaces.css";
import "../conversations/inbox.css";
import "./projects.css";
import { testI18nProvider } from "../providers/commons/i18nProvider";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import { ProjectShow } from "./ProjectShow";
import { BusTimetableSection } from "./ProjectBusTimetable";
import { SinglePageEditor } from "./presentation/SinglePageEditor";
import { CategoryEditor } from "./presentation/CategoryEditor";
import type { SinglePageDraft } from "./presentation/use-single-page-draft";
import type { CategoryDraft } from "./presentation/use-category-draft";

const mocks = vi.hoisted(() => ({ loadBus: vi.fn(), notify: vi.fn() }));
const shownProject = vi.hoisted(() => ({
  id: "project-a",
  name: "LG Hải Phòng",
  slug: "TênDựÁnRấtDài".repeat(10),
  summary: "Tuyển dụng công nhân tại khu công nghiệp Tràng Duệ. ".repeat(10),
  is_active: true,
  knowledge_mode: "RAG",
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
}));

vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof RaCoreModule>()),
  useNotify: () => mocks.notify,
  useRecordContext: () => shownProject,
  useRedirect: () => vi.fn(),
  ShowBase: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("../hooks/useRoleActions", () => ({
  useRoleActions: () => ({ isAdmin: false, canEdit: false }),
}));
vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: () => <p>Kiến thức tư vấn của dự án</p>,
}));
vi.mock("./project-knowledge-service", async (importOriginal) => ({
  ...(await importOriginal()),
  getProjectBusTimetable: mocks.loadBus,
  listSinglePageExternalSources: () => Promise.resolve([]),
}));

const longRoute =
  "Tuyến đưa đón công nhân Hải Phòng — " + "TênTuyếnRấtDài".repeat(8);
const longStop =
  "Điểm đón tại khu công nghiệp Tràng Duệ — " + "TênĐiểmĐónRấtDài".repeat(8);

const draft: SinglePageDraft = {
  loading: false,
  saving: false,
  refreshing: true,
  filename: "Thông tin tuyển dụng dự án Hải Phòng.md",
  text: "Kiến thức tư vấn của dự án. ".repeat(40),
  hasCurrentPage: true,
  loadFailed: false,
  remoteChanged: true,
  autoSyncOn: true,
  syncRefreshKey: 0,
  setFilename: () => undefined,
  setText: () => undefined,
  save: async () => undefined,
  readFile: async () => undefined,
  handleSourceChange: () => undefined,
  handleSynchronized: () => undefined,
  reload: async () => undefined,
  discardChanges: () => undefined,
};

const categoryDraft: CategoryDraft = {
  content: "Nội dung danh mục. ".repeat(30),
  filename: "TênTệpKiếnThứcRấtDài".repeat(10) + ".md",
  hasCurrentSource: true,
  hasUnsavedChanges: false,
  isEditing: false,
  loading: false,
  loadFailed: false,
  saving: false,
  reload: async () => undefined,
  setContent: () => undefined,
  startEditing: () => undefined,
  cancelEditing: () => undefined,
  save: async () => undefined,
};

const workspace = (children: ReactNode) => (
  <CoreAdminContext i18nProvider={testI18nProvider}>
    <div id="root" className="workspace-frame-content">
      <ProjectWorkspaceShell>
        <div className="project-workspace-content">{children}</div>
      </ProjectWorkspaceShell>
    </div>
  </CoreAdminContext>
);

const expectContained = (container: HTMLElement, width: number) => {
  const surface = container.querySelector<HTMLElement>(
    ".project-workspace-content",
  )!;
  expect(surface.scrollWidth).toBeLessThanOrEqual(surface.clientWidth + 1);
  expect(document.scrollingElement!.scrollWidth).toBeLessThanOrEqual(width + 1);
  for (const element of surface.querySelectorAll<HTMLElement>(
    "button, p, h2, h3, h4, summary",
  )) {
    if (element.getClientRects().length === 0) continue;
    expect(
      element.scrollWidth,
      element.textContent ?? element.tagName,
    ).toBeLessThanOrEqual(element.clientWidth + 1);
    expect(element.getBoundingClientRect().right).toBeLessThanOrEqual(
      surface.getBoundingClientRect().right + 1,
    );
  }
};

beforeEach(() => {
  mocks.loadBus.mockReset();
  mocks.loadBus.mockResolvedValue({
    total: 60,
    page: 1,
    per_page: 6,
    data: [
      {
        id: "route-a",
        route_name: longRoute,
        route_no: "MãTuyếnRấtDài".repeat(6),
        route_variant: "",
        shift: "day",
        direction: "outbound",
        stops: [
          {
            id: "stop-a",
            stop_order: 1,
            stop_name: longStop,
            scheduled_time: "06:30",
          },
        ],
      },
    ],
  });
});

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("project forms on narrow phones", () => {
  it.each([320, 360, 390, 1440])(
    "keeps filename and Sheet controls compact without shrinking the KB editor at %ipx",
    async (width) => {
      await page.viewport(width, 900);
      const screen = await render(
        workspace(
          <SinglePageEditor projectId="project-a" draft={draft} editable />,
        ),
      );
      await screen
        .getByRole("button", { name: "Liên kết Google Sheet" })
        .click();
      const expectedHeight = width < 768 ? 40 : 36;
      const editableFont = window.matchMedia("(pointer: coarse)").matches
        ? "16px"
        : "12px";
      for (const name of ["Tên file trang kiến thức", "Link Google Sheet"]) {
        const input = screen.getByRole("textbox", { name }).element();
        expect(input.getBoundingClientRect().height).toBe(expectedHeight);
        expect(getComputedStyle(input).fontSize).toBe(editableFont);
      }
      for (const name of ["Chọn file", "Hủy", "Nhập một lần"]) {
        const button = screen
          .getByRole("button", { name, exact: true })
          .element();
        expect(button.getBoundingClientRect().height).toBe(expectedHeight);
      }
      const sourceBody = screen.container.querySelector<HTMLElement>(
        ".project-source-link-body",
      )!;
      expect(getComputedStyle(sourceBody).gap).toBe("12px");
      expect(getComputedStyle(sourceBody).padding).toBe("16px");
      expect(
        getComputedStyle(sourceBody.querySelector("label")!).fontSize,
      ).toBe("13px");
      const editor = screen
        .getByRole("textbox", { name: "Nội dung trang kiến thức" })
        .element();
      expect(editor.getBoundingClientRect().height).toBeGreaterThanOrEqual(280);
      expectContained(screen.container, width);
    },
  );

  it.each([320, 360, 390])(
    "places the project title below Back and preserves full recruitment details at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        <CoreAdminContext i18nProvider={testI18nProvider}>
          <div id="root" className="workspace-frame-content">
            <ProjectShow />
          </div>
        </CoreAdminContext>,
      );
      const back = screen
        .getByRole("button", { name: "Dự án", exact: true })
        .element();
      const heading = screen
        .getByRole("heading", { name: shownProject.name })
        .element();
      expect(heading.getBoundingClientRect().top).toBeGreaterThanOrEqual(
        back.getBoundingClientRect().bottom,
      );
      expectContained(screen.container, width);
    },
  );
  it.each([320, 360, 390])(
    "shows full bus route and stop names with unboxed paging controls at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        workspace(
          <section className="project-knowledge-panel">
            <div className="project-knowledge-content">
              <BusTimetableSection projectId="project-a" />
            </div>
          </section>,
        ),
      );
      await expect.element(screen.getByText(longRoute)).toBeVisible();
      expectContained(screen.container, width);
      const stop = screen.getByText(longStop).element();
      expect(stop.scrollWidth).toBeLessThanOrEqual(stop.clientWidth + 1);
      expect(getComputedStyle(stop).textOverflow).not.toBe("ellipsis");
      for (const name of ["Trang trước", "Trang sau"]) {
        const button = screen.getByRole("button", { name }).element();
        expect(button.getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
        expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(
          44,
        );
        expect(getComputedStyle(button).backgroundColor).toBe(
          "rgba(0, 0, 0, 0)",
        );
        expect(getComputedStyle(button).boxShadow).toBe("none");
        expect(getComputedStyle(button).borderWidth).toBe("0px");
      }
      const next = screen.getByRole("button", { name: "Trang sau" }).element();
      await userEvent.keyboard("{Tab}");
      next.focus();
      expect(document.activeElement).toBe(next);
      expect(getComputedStyle(next).outlineStyle).toBe("solid");
      expect(
        Number.parseFloat(getComputedStyle(next).outlineWidth),
      ).toBeGreaterThanOrEqual(2);
    },
  );

  it.each([320, 360, 390])(
    "keeps single-page sync, refresh notices and linking controls contained at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        workspace(
          <SinglePageEditor projectId="project-a" draft={draft} editable />,
        ),
      );
      await screen
        .getByRole("button", { name: "Liên kết Google Sheet" })
        .click();
      await screen
        .getByRole("switch", { name: "Bật đồng bộ tự động hàng ngày" })
        .click();
      expectContained(screen.container, width);
      const summary = screen
        .getByText("Sheet sẽ ghi đè nội dung sửa tay")
        .element()
        .closest("summary")!;
      expect(summary.getBoundingClientRect().height).toBeGreaterThanOrEqual(40);
      await screen.getByRole("button", { name: "Hủy", exact: true }).click();
      await expect
        .element(screen.getByRole("button", { name: "Liên kết Google Sheet" }))
        .toBeVisible();
    },
  );

  it.each([320, 360, 390])(
    "keeps long category descriptions and Sheet forms contained at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        workspace(
          <section className="project-knowledge-panel">
            <div className="project-knowledge-content">
              <CategoryEditor
                projectId="project-a"
                selectedKey="compensation"
                draft={categoryDraft}
                processing={false}
                editable
                canManageSources
                onSourceCreated={() => undefined}
              />
            </div>
          </section>,
        ),
      );
      await screen
        .getByRole("button", { name: "Liên kết Google Sheet" })
        .click();
      expectContained(screen.container, width);
      const category = screen.getByRole("combobox");
      await category.click();
      const list = screen.getByRole("listbox").element();
      expect(list.getBoundingClientRect().right).toBeLessThanOrEqual(width);
      expect(list.getBoundingClientRect().left).toBeGreaterThanOrEqual(0);
    },
  );
});
