/**
 * Rendered WCAG 2.1 AA contrast audit (mobile viewports).
 *
 * Reads the REAL computed colors out of the mounted DOM at 320/390px:
 * effective background = first opaque ancestor fill, contrast = WCAG ratio,
 * threshold 4.5:1 for normal text, 3:1 for large text (≥24px, or ≥18.66px
 * bold). Elements that deliberately clip (ellipsis) or are hidden/off-canvas
 * are skipped; their rect containment is covered by mobile-containment.
 */
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as RaCoreModule from "ra-core";

import "@/index.css";
import "@/flat-surfaces.css";
import "./conversations/inbox.css";
import "./projects/projects.css";
import "./users/users.css";
import "./integrations/settings.css";
import "./dashboard/dashboard.css";
import "./performance/performance.css";
import { testI18nProvider } from "./providers/commons/i18nProvider";
import { TestMessages } from "./providers/commons/TestMessages";
import type { Project, UserAccount } from "./types";

const viewport = vi.hoisted(() => ({ isMobile: true }));
const listState = vi.hoisted(() => ({
  value: {
    data: [] as unknown[],
    isPending: false,
    error: null as Error | null,
    total: 0,
    page: 1,
    perPage: 25,
    setPage: (_page: number) => {},
    filterValues: {} as Record<string, unknown>,
    displayedFilters: {} as Record<string, unknown>,
    setFilters: () => {},
    setPerPage: () => {},
    hasNextPage: false,
    hasPreviousPage: false,
  },
}));
const perfState = vi.hoisted(() => ({
  value: {
    data: {
      window: "7d",
      response_time: {
        p50_ms: 1500,
        p95_ms: 3200,
        trend: [{ bucket: "b", p50_ms: 1500, p95_ms: 3200, turns: 3 }],
      },
      conversion: { rate_pct: 25.0, with_phone: 3, candidate_chats: 12 },
    },
    isPending: false,
    isFetching: false,
    isError: false,
    refetch: () => Promise.resolve(),
    dataUpdatedAt: 1_784_732_616_000,
  },
}));

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => viewport.isMobile,
  useIsWideDesktop: () => false,
  useIsNarrow: () => viewport.isMobile,
}));

vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof RaCoreModule>()),
  useTranslate: () => testI18nProvider.translate,
  useNotify: () => vi.fn(),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useGetList: () => ({ data: [], total: 0 }),
  useDataProvider: () => ({
    update: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
    markAsRead: vi.fn(() => Promise.resolve()),
  }),
  useListContext: () => listState.value,
  useListPaginationContext: () => listState.value,
  useGetOne: () => ({ data: undefined, isPending: false, isError: false }),
  useCreatePath: () => (options: { resource: string; type: string }) =>
    `/${options.resource}/${options.type}`,
  ListBase: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("./performance/usePerformanceStats", () => ({
  usePerformanceStats: () => perfState.value,
}));

vi.mock("./projects/ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: ({ project }: { project: { name: string } }) => (
    <p>Kiến thức dự án {project.name}</p>
  ),
}));

vi.mock("./integrations/api", () => ({
  zaloIntegrationGateway: new Proxy(
    {},
    { get: () => vi.fn(() => Promise.resolve({})) },
  ),
  facebookIntegrationGateway: new Proxy(
    {},
    { get: () => vi.fn(() => Promise.resolve({})) },
  ),
}));

import { UserList } from "./users/UserList";
import { ProjectWorkspaceShell } from "./projects/ProjectWorkspaceShell";
import { ProjectMobileCardList } from "./projects/ProjectList";
import { PerformancePage } from "./performance/PerformancePage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

const user: UserAccount = {
  id: "user-1",
  email: "recruiter@vfic.dev",
  full_name: "Nguyễn Minh Anh",
  role: "recruiter",
  disabled: false,
  created_at: "2026-07-22T10:00:00Z",
  updated_at: "2026-07-22T10:00:00Z",
};
const project: Project = {
  id: "project-1",
  name: "Dự án personnel tuyển dụng",
  slug: "du-an",
  is_active: true,
  ingest_state: "ready",
  knowledge_mode: "RAG",
  knowledge_document_count: 2,
  category_readiness: { ready: 1, total: 12 },
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const Frame = ({ children }: { children: ReactNode }) => (
  <div className="workspace-frame">
    <div className="workspace-frame-content">{children}</div>
  </div>
);

const renderContained = async (ui: ReactNode, width: number) => {
  await page.viewport(width, 844);
  return render(
    <TestMessages>
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient()}>
          <Frame>{ui}</Frame>
        </QueryClientProvider>
      </MemoryRouter>
    </TestMessages>,
  );
};

const PHONES = [320, 390] as const;

beforeEach(() => {
  viewport.isMobile = true;
  listState.value = {
    data: [],
    isPending: false,
    error: null,
    total: 0,
    page: 1,
    perPage: 25,
    setPage: () => {},
    filterValues: {},
    displayedFilters: {},
    setFilters: () => {},
    setPerPage: () => {},
    hasNextPage: false,
    hasPreviousPage: false,
  };
});

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

/** WCAG relative luminance from a resolved rgb()/rgba()/hex color string. */
function luminance(color: string): number | null {
  const rgb = color.match(
    /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)/,
  );
  if (color.startsWith("#")) {
    const h = color.slice(1);
    if (h.length !== 6 && h.length !== 3) return null;
    const full =
      h.length === 3
        ? h
            .split("")
            .map((c) => c + c)
            .join("")
        : h;
    return luminance(
      `rgb(${parseInt(full.slice(0, 2), 16)}, ${parseInt(full.slice(2, 4), 16)}, ${parseInt(full.slice(4, 6), 16)})`,
    );
  }
  if (!rgb) return null;
  const alpha = rgb[4] === undefined ? 1 : parseFloat(rgb[4]);
  if (alpha >= 1) {
    const part = (v: string) => {
      const n = parseInt(v, 10) / 255;
      return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
    };
    return (
      0.2126 * part(rgb[1]) + 0.7152 * part(rgb[2]) + 0.0722 * part(rgb[3])
    );
  }
  return null; // translucent fill: knocked over an ancestor's fill instead
}

/** Effective background = first ancestor (self inclusive) with an opaque fill. */
function effectiveBackground(element: Element): string {
  let node: Element | null = element;
  while (node) {
    const bg = getComputedStyle(node).backgroundColor;
    if (bg && !bg.startsWith("rgba(0, 0, 0, 0)") && bg !== "transparent") {
      const l = luminance(bg);
      if (l !== null) return bg;
    }
    node = node.parentElement;
  }
  return "#ffffff";
}

function contrastRatio(fg: string, bg: string): number | null {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  if (l1 === null || l2 === null) return null;
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

function assertContrast(surface: HTMLElement, width: number) {
  const issues: string[] = [];
  const selectors = "h1, h2, h3, h4, p, span, button, a, label, td, th";
  for (const element of Array.from(
    surface.querySelectorAll<HTMLElement>(selectors),
  )) {
    if (element.getClientRects().length === 0) continue;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden") continue;
    const text = (element.textContent ?? "").trim();
    if (!text) continue;
    const fg = style.color;
    const bg = effectiveBackground(element);
    const ratio = contrastRatio(fg, bg);
    if (ratio === null) continue;
    const size = parseFloat(style.fontSize);
    const bold = parseInt(style.fontWeight, 10) >= 600;
    const largeText = size >= 24 || (size >= 18.66 && bold);
    const required = largeText ? 3 : 4.5;
    if (ratio < required) {
      issues.push(
        `${element.tagName}.${String(element.className).slice(0, 40)} "${text.slice(0, 30)}" ${ratio.toFixed(2)}:1 < ${required}:1 (fg ${fg} on ${bg})`,
      );
    }
  }
  expect(
    issues,
    `WCAG AA contrast failures at ${width}px:\n${issues.join("\n")}`,
  ).toEqual([]);
}

describe("rendered WCAG AA contrast (mobile)", () => {
  it.each(PHONES)(
    "keeps the users directory text at AA contrast at %ipx",
    async (width) => {
      listState.value = { ...listState.value, data: [user], total: 1 };
      const screen = await renderContained(<UserList />, width);
      await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
      assertContrast(
        screen.container.querySelector<HTMLElement>(
          ".user-directory-workspace",
        )!,
        width,
      );
    },
  );

  it.each(PHONES)(
    "keeps the project directory text at AA contrast at %ipx",
    async (width) => {
      listState.value = { ...listState.value, data: [project], total: 1 };
      const screen = await renderContained(
        <ProjectWorkspaceShell>
          <div className="project-workspace-content">
            <div className="ops-page-shell project-page-shell">
              <ProjectMobileCardList
                projects={[project]}
                isAdmin={false}
                canEdit={false}
                onEdit={() => {}}
                onDeleted={() => {}}
                onOpenKnowledge={() => {}}
              />
            </div>
          </div>
        </ProjectWorkspaceShell>,
        width,
      );
      await expect.element(screen.getByText(project.name)).toBeVisible();
      assertContrast(
        screen.container.querySelector<HTMLElement>(
          ".project-workspace-content",
        )!,
        width,
      );
    },
  );

  it.each(PHONES)(
    "keeps the performance page text at AA contrast at %ipx",
    async (width) => {
      const screen = await renderContained(<PerformancePage />, width);
      await expect
        .element(screen.getByRole("heading", { name: "Hiệu suất chatbot" }))
        .toBeVisible();
      assertContrast(
        screen.container.querySelector<HTMLElement>(".performance-page")!,
        width,
      );
    },
  );
});
