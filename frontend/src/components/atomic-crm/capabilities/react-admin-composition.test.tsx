import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthProvider, DataProvider } from "ra-core";

const api = vi.hoisted(() => ({ apiJson: vi.fn() }));
const realtime = vi.hoisted(() => ({
  closeRealtimeSocket: vi.fn(),
  getRealtimeSocket: vi.fn(),
}));
vi.mock("../providers/rest/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../providers/rest/api")>();
  return { ...actual, apiJson: api.apiJson };
});
vi.mock("@/lib/vfic/realtimeSocket", () => realtime);

import { CRM } from "../root/CRM";
import { InstallationProvider } from "../installation/InstallationContext";
import { testI18nProvider } from "../providers/commons/i18nProvider";
import type { CrmDataProvider } from "../providers/types";
import { genericFixtureManifest, genericFixtureRegistry } from "./test-fixtures";
import {
  abandonRuntimeGenerationForTests,
  ensureRuntimeGeneration,
  resetActiveRuntimeState,
} from "../root/reset-runtime-state";
import { canAccess } from "../providers/commons/canAccess";

const dataProvider = {
  getList: vi.fn(async () => ({ data: [], total: 0 })),
  getOne: vi.fn(async () => ({ data: { id: "1" } })),
  getMany: vi.fn(async () => ({ data: [] })),
  getManyReference: vi.fn(async () => ({ data: [], total: 0 })),
  create: vi.fn(async (_resource, params) => ({ data: { id: "1", ...params.data } })),
  update: vi.fn(async (_resource, params) => ({ data: { id: params.id, ...params.data } })),
  updateMany: vi.fn(async (_resource, params) => ({ data: params.ids })),
  delete: vi.fn(async (_resource, params) => ({ data: params.previousData })),
  deleteMany: vi.fn(async (_resource, params) => ({ data: params.ids })),
} as unknown as DataProvider;

const authProvider: AuthProvider = {
  login: async () => undefined,
  logout: async () => undefined,
  checkAuth: async () => undefined,
  checkError: async () => undefined,
  getIdentity: async () => ({ id: "admin", fullName: "Quản trị" }),
  getPermissions: async () => "admin",
  canAccess: async () => true,
};

const recruiterAuthProvider = (availableResources: ReadonlySet<string>): AuthProvider => ({
  ...authProvider,
  getPermissions: async () => "recruiter",
  canAccess: async (params) => canAccess("recruiter", params, availableResources),
});

describe("React Admin compiled composition", () => {
  beforeEach(() => {
    abandonRuntimeGenerationForTests();
    window.localStorage.setItem("RaStore.auth.access_token", "test-token");
    window.location.hash = "#/contacts";
    api.apiJson.mockResolvedValue({ count: 0 });
    dataProvider.getList = vi.fn(async () => ({ data: [], total: 0 }));
  });

  afterEach(async () => {
    await cleanup();
    await resetActiveRuntimeState();
    abandonRuntimeGenerationForTests();
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("discovers compiled Resources because CRM renders them as direct Admin children", async () => {
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider
        value={{ manifest, refreshRuntime: async () => undefined }}
      >
        <CRM
          bundle={bundle}
          authProvider={authProvider}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(screen.getByRole("heading", { name: "Liên hệ" })).toBeVisible();
    await vi.waitFor(() => {
      expect(dataProvider.getList).toHaveBeenCalledWith(
        "contacts",
        expect.objectContaining({ pagination: expect.any(Object) }),
      );
    });
    const forbidden = api.apiJson.mock.calls
      .map(([path]) => String(path))
      .filter((path) =>
        /\/leads|\/jobs|dashboard\/attention|features|bus-timetable/.test(path),
      );
    expect(forbidden).toEqual([]);
  });

  it("lets recruiters list Contacts without exposing the administrator-only create action", async () => {
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider value={{ manifest, refreshRuntime: async () => undefined }}>
        <CRM
          bundle={bundle}
          authProvider={recruiterAuthProvider(bundle.runtime.availableResources)}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(screen.getByRole("heading", { name: "Liên hệ" })).toBeVisible();
    await vi.waitFor(() => expect(dataProvider.getList).toHaveBeenCalledWith("contacts", expect.any(Object)));
    await expect.element(screen.getByRole("link", { name: /Tạo/ })).not.toBeInTheDocument();
  });

  it("keeps recruiter Contact edit access", async () => {
    window.location.hash = "#/contacts/1";
    dataProvider.getOne = vi.fn(async () => ({
      data: { id: "1", display_name: "Liên hệ hiện có", version: 1 },
    })) as DataProvider["getOne"];
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider value={{ manifest, refreshRuntime: async () => undefined }}>
        <CRM
          bundle={bundle}
          authProvider={recruiterAuthProvider(bundle.runtime.availableResources)}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(screen.getByText("Cập nhật liên hệ")).toBeVisible();
    expect(document.body.textContent).not.toContain("Phiên bản");
  });

  it("discovers compiled custom Routes as direct React Router children", async () => {
    window.location.hash = "#/settings/workflows/new";
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider
        value={{ manifest, refreshRuntime: async () => undefined }}
      >
        <CRM
          bundle={bundle}
          authProvider={authProvider}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(
      screen.getByText("Hãy chọn gói và quy trình trước"),
    ).toBeVisible();
  });

  it("renders administrator-facing Case selectors without exposed IDs or checksums", async () => {
    window.location.hash = "#/cases/create";
    const workflowVersionId = "00000000-0000-4000-8000-000000000031";
    const staleVersionId = "00000000-0000-4000-8000-000000000030";
    let resolveStaleVersion: (value: object) => void = () => undefined;
    const staleVersion = new Promise<object>((resolve) => {
      resolveStaleVersion = resolve;
    });
    api.apiJson.mockImplementation(async (path: string) =>
      path === `/api/v1/admin/case-workflows/${staleVersionId}`
        ? staleVersion
        : path === `/api/v1/admin/case-workflows/${workflowVersionId}`
        ? {
            id: workflowVersionId,
            pack_key: "generic-fixture",
            workflow_key: "support",
            version_no: 3,
            label: "Hỗ trợ khách hàng",
            checksum: "e".repeat(64),
            created_at: "2026-07-15T00:00:00Z",
            schema_version: 1,
            case_attribute_schema: {
              customer_tier: {
                type: "string",
                label: "Hạng khách hàng",
                required: true,
                enum: ["Tiêu chuẩn", "Ưu tiên"],
              },
            },
            stages: [],
            transitions: [],
            tags: [],
          }
        : path.startsWith("/api/v1/admin/case-workflows")
        ? {
            data: [
              {
                id: staleVersionId,
                pack_key: "generic-fixture",
                workflow_key: "support",
                version_no: 2,
                label: "Phiên bản cũ",
                checksum: "d".repeat(64),
                created_at: "2026-07-14T00:00:00Z",
              },
              {
                id: workflowVersionId,
                pack_key: "generic-fixture",
                workflow_key: "support",
                version_no: 3,
                label: "Hỗ trợ khách hàng",
                checksum: "e".repeat(64),
                created_at: "2026-07-15T00:00:00Z",
              },
            ],
            total: 1,
          }
        : { count: 0 },
    );
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider
        value={{ manifest, refreshRuntime: async () => undefined }}
      >
        <CRM
          bundle={bundle}
          authProvider={authProvider}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(screen.getByText("Tạo hồ sơ công việc")).toBeVisible();
    await expect.element(screen.getByText("Liên hệ *")).toBeVisible();
    const workflowSelect = screen.getByLabelText("Quy trình *");
    await expect.element(workflowSelect).toBeVisible();
    await expect.element(screen.getByText("Người phụ trách")).toBeVisible();
    await workflowSelect.selectOptions(staleVersionId);
    await workflowSelect.selectOptions(workflowVersionId);
    await expect.element(workflowSelect).toHaveValue(workflowVersionId);
    await expect.element(screen.getByText("Thông tin theo quy trình")).toBeVisible();
    await expect.element(screen.getByText("Hạng khách hàng")).toBeVisible();
    resolveStaleVersion({
      id: staleVersionId,
      pack_key: "generic-fixture",
      workflow_key: "support",
      version_no: 2,
      label: "Phiên bản cũ",
      checksum: "d".repeat(64),
      created_at: "2026-07-14T00:00:00Z",
      schema_version: 1,
      case_attribute_schema: {
        stale_field: { type: "string", label: "Trường dữ liệu cũ", required: true },
      },
      stages: [],
      transitions: [],
      tags: [],
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.body.textContent).not.toContain("Trường dữ liệu cũ");
    await expect.element(workflowSelect).toHaveValue(workflowVersionId);
    expect(document.body.textContent).not.toContain(workflowVersionId);
    expect(document.body.textContent).not.toContain("Mã kiểm tra quy trình");
  });

  it("renders generic conversations with zero recruitment calls or lead-room access", async () => {
    window.location.hash = "#/conversations";
    const manifest = genericFixtureManifest();
    const bundle = await ensureRuntimeGeneration(manifest, genericFixtureRegistry());
    const screen = await render(
      <InstallationProvider
        value={{ manifest, refreshRuntime: async () => undefined }}
      >
        <CRM
          bundle={bundle}
          authProvider={authProvider}
          dataProvider={dataProvider as CrmDataProvider}
          i18nProvider={testI18nProvider}
        />
      </InstallationProvider>,
    );

    await expect.element(
      screen.getByRole("heading", { name: "Tin nhắn" }),
    ).toBeVisible();
    await vi.waitFor(() => {
      expect(dataProvider.getList).toHaveBeenCalledWith(
        "conversations",
        expect.any(Object),
      );
    });
    expect(realtime.getRealtimeSocket).not.toHaveBeenCalled();
    expect(document.body.textContent?.toLocaleLowerCase("vi-VN")).not.toContain("ứng viên");
    const forbidden = api.apiJson.mock.calls
      .map(([path]) => String(path))
      .filter((path) =>
        /\/leads|\/jobs|dashboard\/attention|features|bus-timetable/.test(path),
      );
    expect(forbidden).toEqual([]);
  });
});
