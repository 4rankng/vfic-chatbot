import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExternalApiView } from "./domain/external-api-contracts";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  getProjectExternalApi: vi.fn(),
  saveProjectExternalApi: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("./external-api-service", () => ({
  getProjectExternalApi: mocks.getProjectExternalApi,
  saveProjectExternalApi: mocks.saveProjectExternalApi,
}));

import { ProjectExternalApiPanel } from "./ProjectExternalApiPanel";

const GUIDE = [
  "# Hướng dẫn tích hợp API cho Chatbot",
  "POST /api/v1/integration/password-reset/otp — gửi OTP qua Zalo.",
].join("\n");

const savedView: ExternalApiView = {
  enabled: true,
  base_url: "https://api.example.com",
  auth_header: "X-API-Key",
  auth_scheme: "",
  guide: GUIDE,
  api_key: { configured: true, preview: "10 ký tự" },
};

const renderPanel = () =>
  render(<ProjectExternalApiPanel projectId="project-1" />);

describe("ProjectExternalApiPanel", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.getProjectExternalApi.mockResolvedValue(savedView);
    mocks.saveProjectExternalApi.mockResolvedValue(savedView);
  });

  it("renders the saved connection with the key masked and no value", async () => {
    const screen = await renderPanel();

    await expect
      .element(screen.getByTestId("project-external-api-key-status"))
      .toHaveTextContent("Đã lưu · 10 ký tự");
    await expect
      .element(screen.getByLabelText("Base URL"))
      .toHaveValue("https://api.example.com");
    await expect
      .element(screen.getByLabelText("Hướng dẫn API cho chatbot"))
      .toHaveValue(GUIDE);
    await expect
      .element(screen.getByTestId("project-external-api-header-preview"))
      .toHaveTextContent("X-API-Key: •••");
    expect(screen.getByLabelText("Khóa API").element()).toHaveProperty(
      "value",
      "",
    );
  });

  it("omits api_key when the key field stays blank", async () => {
    const screen = await renderPanel();
    await screen.getByTestId("project-external-api-save").click();

    await vi.waitFor(() => {
      expect(mocks.saveProjectExternalApi).toHaveBeenCalledTimes(1);
    });
    const [projectId, payload] = mocks.saveProjectExternalApi.mock.calls[0];
    expect(projectId).toBe("project-1");
    expect("api_key" in payload).toBe(false);
    expect(payload.guide).toBe(GUIDE);
    expect(payload.base_url).toBe("https://api.example.com");
    expect(mocks.notify).toHaveBeenCalledWith("Đã lưu tích hợp API ngoài.", {
      type: "success",
    });
  });

  it("sends a typed key and clears it only through the explicit action", async () => {
    const screen = await renderPanel();
    await screen.getByLabelText("Khóa API").fill("ttk_fresh");
    await screen.getByTestId("project-external-api-save").click();
    await vi.waitFor(() => {
      expect(mocks.saveProjectExternalApi).toHaveBeenCalledTimes(1);
    });
    expect(mocks.saveProjectExternalApi.mock.calls[0][1].api_key).toBe(
      "ttk_fresh",
    );

    mocks.saveProjectExternalApi.mockClear();
    await screen.getByRole("button", { name: "Xóa khóa" }).click();
    await expect
      .element(screen.getByTestId("project-external-api-key-status"))
      .toHaveTextContent("Sẽ xóa khóa khi lưu");
    await screen.getByTestId("project-external-api-save").click();
    await vi.waitFor(() => {
      expect(mocks.saveProjectExternalApi).toHaveBeenCalledTimes(1);
    });
    expect(mocks.saveProjectExternalApi.mock.calls[0][1].api_key).toBe("");
  });

  it("fills the guide from an uploaded file", async () => {
    const screen = await renderPanel();
    const uploaded = "# Hướng dẫn mới\nPOST /api/v1/integration/employee/lookup\n";
    await screen
      .getByLabelText("Tệp hướng dẫn")
      .upload(new File([uploaded], "guide.md", { type: "text/markdown" }));

    await expect
      .element(screen.getByLabelText("Hướng dẫn API cho chatbot"))
      .toHaveValue(uploaded);
    await screen.getByTestId("project-external-api-save").click();
    await vi.waitFor(() => {
      expect(mocks.saveProjectExternalApi).toHaveBeenCalledTimes(1);
    });
    expect(mocks.saveProjectExternalApi.mock.calls[0][1].guide).toBe(uploaded);
  });

  it("reports an invalid base URL inline and disables saving", async () => {
    const screen = await renderPanel();
    await screen.getByLabelText("Base URL").fill("http://api.example.com");

    await expect
      .element(screen.getByTestId("project-external-api-errors"))
      .toHaveTextContent(
        "Chỉ dùng http cho 127.0.0.1/localhost; còn lại phải là https.",
      );
    await vi.waitFor(() => {
      expect(
        screen.getByTestId("project-external-api-save").element(),
      ).toHaveProperty("disabled", true);
    });
    expect(mocks.saveProjectExternalApi).not.toHaveBeenCalled();
  });

  it("blocks enabling without a guide", async () => {
    mocks.getProjectExternalApi.mockResolvedValue({
      ...savedView,
      enabled: false,
      base_url: "",
      guide: "",
    });
    const screen = await renderPanel();
    await screen.getByLabelText("Hướng dẫn API cho chatbot").fill("");
    await screen.getByLabelText("Base URL").fill("https://api.example.com");
    await screen.getByLabelText("Bật tích hợp API").click();

    await expect
      .element(screen.getByTestId("project-external-api-errors"))
      .toHaveTextContent("Bật tích hợp cần dán hoặc tải lên hướng dẫn API.");
    await vi.waitFor(() => {
      expect(
        screen.getByTestId("project-external-api-save").element(),
      ).toHaveProperty("disabled", true);
    });
  });
});
