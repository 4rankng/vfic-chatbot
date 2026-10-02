import { Form, TestMemoryRouter } from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@/index.css";
import "@/styles/untitledui-theme.css";
import "@/flat-surfaces.css";
import "./projects.css";
import { FormToggle } from "../kit";
import { TestMessages } from "../providers/commons/TestMessages";

const contrast = (first: string, second: string) => {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d")!;
  const luminance = (color: string) => {
    context.fillStyle = color;
    context.fillRect(0, 0, 1, 1);
    const channels = Array.from(context.getImageData(0, 0, 1, 1).data).slice(
      0,
      3,
    );
    const linear = channels.map((value) => {
      const scaled = value / 255;
      return scaled <= 0.04045
        ? scaled / 12.92
        : ((scaled + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const a = luminance(first);
  const b = luminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
};

const renderToggle = () =>
  render(
    <TestMemoryRouter>
      <TestMessages>
        <Form
          resource="projects"
          record={{ is_active: false }}
          onSubmit={vi.fn()}
        >
          <div id="root" className="inbox-bg-container project-workspace">
            <section className="project-form-surface">
              <FormToggle
                source="is_active"
                label="Dự án hoạt động"
                className="project-edit-active"
              />
            </section>
          </div>
        </Form>
      </TestMessages>
    </TestMemoryRouter>,
  );

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("project activation switch", () => {
  it.each([390, 1280])(
    "keeps the off control outlined and the selected state distinct at %ipx",
    async (width) => {
      await page.viewport(width, 900);
      const screen = await renderToggle();
      const toggle = screen.getByRole("switch", { name: "Dự án hoạt động" });
      const wrapper = screen.container.querySelector<HTMLElement>(
        ".project-edit-active .uu-scope",
      )!;
      const track = wrapper.querySelector<HTMLElement>(
        ":scope > div.rounded-full",
      )!;
      const thumb = track.firstElementChild as HTMLElement;
      const surface = screen.container.querySelector<HTMLElement>(
        ".project-form-surface",
      )!;
      const off = getComputedStyle(track);
      const offColor = off.backgroundColor;
      expect(off.boxShadow).toBe("none");
      expect(off.borderTopWidth).toBe("1px");
      expect(
        contrast(off.borderTopColor, getComputedStyle(surface).backgroundColor),
      ).toBeGreaterThanOrEqual(3);
      expect(
        contrast(getComputedStyle(thumb).borderTopColor, offColor),
      ).toBeGreaterThanOrEqual(3);
      if (width < 768) {
        expect(wrapper.getBoundingClientRect().height).toBeGreaterThanOrEqual(
          44,
        );
        expect(wrapper.getBoundingClientRect().width).toBeGreaterThanOrEqual(
          44,
        );
      }
      await screen.getByText("Dự án hoạt động", { exact: true }).click();
      await expect.element(toggle).toBeChecked();
      expect(wrapper).toHaveAttribute("data-selected");
      const selected = getComputedStyle(track);
      expect(selected.backgroundColor).not.toBe(offColor);
      expect(
        contrast(
          getComputedStyle(thumb).backgroundColor,
          selected.backgroundColor,
        ),
      ).toBeGreaterThanOrEqual(3);
    },
  );
});
