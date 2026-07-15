import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  list: vi.fn(),
  publish: vi.fn(),
}));

vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("ra-core")>()),
  useNotify: () => mocks.notify,
}));
vi.mock("./workflow-authoring-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./workflow-authoring-client")>()),
  listWorkflowVersions: mocks.list,
  publishWorkflowVersion: mocks.publish,
}));

import { WorkflowAuthoringPage } from "./WorkflowAuthoringPage";

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("WorkflowAuthoringPage", () => {
  it("starts blank and requires an explicit tag tone before publishing Case fields", async () => {
    mocks.list.mockResolvedValue([]);
    mocks.publish.mockResolvedValue({
      id: "00000000-0000-4000-8000-000000000010",
      pack_key: "configured-pack",
      workflow_key: "support",
      version_no: 1,
      label: "Hỗ trợ khách hàng",
      checksum: "b".repeat(64),
      created_at: "2026-07-15T00:00:00Z",
    });
    const screen = await render(
      <WorkflowAuthoringPage
        packKey="configured-pack"
        workflowKey="support"
        embedded
      />,
    );

    await expect.element(screen.getByText("Chưa có thuộc tính bổ sung.")).toBeVisible();
    await screen.getByLabelText("Tên hiển thị").fill("Hỗ trợ khách hàng");
    await screen.getByRole("button", { name: "Thêm giai đoạn" }).click();
    await screen.getByLabelText("Mã giai đoạn 1").fill("new");
    await screen.getByLabelText("Tên giai đoạn 1").fill("Mới");
    await expect.element(screen.getByRole("button", { name: "Xoá giai đoạn" })).toBeVisible();
    await screen.getByRole("button", { name: "Thêm giai đoạn" }).click();
    await screen.getByLabelText("Mã giai đoạn 2").fill("resolved");
    await screen.getByLabelText("Tên giai đoạn 2").fill("Đã xử lý");
    await screen.getByRole("button", { name: "Thêm luồng chuyển" }).click();
    await screen.getByLabelText("Từ giai đoạn 1").selectOptions("new");
    await screen.getByLabelText("Đến giai đoạn 1").selectOptions("resolved");
    await expect.element(screen.getByRole("button", { name: "Xoá luồng chuyển" })).toBeVisible();
    const publishButton = screen.getByRole("button", { name: "Xuất bản phiên bản" });
    await expect.element(publishButton).toBeDisabled();
    await screen.getByRole("checkbox", { name: "Giai đoạn kết thúc" }).nth(1).click();
    await screen.getByRole("button", { name: "Thêm nhãn" }).click();
    await screen.getByLabelText("Mã nhãn 1").fill("urgent");
    await screen.getByLabelText("Tên nhãn 1").fill("Khẩn cấp");
    await expect.element(publishButton).toBeDisabled();
    await screen.getByLabelText("Màu nhãn 1").selectOptions("danger");
    await screen.getByRole("button", { name: "Thêm thuộc tính" }).click();
    await screen.getByLabelText("Mã thuộc tính 1").fill("customer_tier");
    await screen.getByLabelText("Tên thuộc tính 1").fill("Hạng khách hàng");
    await screen.getByLabelText("Kiểu thuộc tính 1").selectOptions("string");
    await screen.getByLabelText("Độ dài tối đa 1").fill("80");
    await screen.getByLabelText("Các lựa chọn thuộc tính 1").fill("Tiêu chuẩn\nƯu tiên");
    await expect.element(screen.getByRole("button", { name: "Xoá thuộc tính" })).toBeVisible();
    await expect.element(publishButton).toBeEnabled();
    await publishButton.click();

    expect(mocks.publish).toHaveBeenCalledWith(
      expect.objectContaining({
        pack_key: "configured-pack",
        workflow_key: "support",
        tags: [expect.objectContaining({ key: "urgent", tone: "danger" })],
        case_attribute_schema: {
          customer_tier: {
            type: "string",
            label: "Hạng khách hàng",
            required: false,
            max_length: 80,
            enum: ["Tiêu chuẩn", "Ưu tiên"],
          },
        },
      }),
    );
  });
});
