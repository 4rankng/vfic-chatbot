import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  DataProviderContext,
  NotificationContext,
  StoreContextProvider,
  TestMemoryRouter,
  memoryStore,
} from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "../kit/tailkit-system.css";
import "./users.css";
import { TestMessages } from "../providers/commons/TestMessages";
import { UserCreate } from "./UserCreate";

// TEST-17 — this replaces the account-layout-regressions.test.ts that imported
// six `?raw` sources (users.css, features.css, personas-responsive.css and
// three TSX files) and regex-matched them. Those regexes could not see whether
// a rule applied to the element the console renders, whether a later
// declaration shadowed it, or whether the account form still validated.
//
// Everything below mounts the real `UserCreate` — ra-core's `CreateBase`,
// `Form` and the shipped Vietnamese catalog included — and measures what a
// recruiter's browser computes. An account form that loses its two-column
// grid, its 44px actions, or its required-field checks goes red here.
//
// Two lane facts shape the fixture:
//   * `--tt-*` resolves through `.workspace-frame` → `--workspace-border` →
//     `--color-base-300`, a daisyUI token this vitest project never emits, so
//     the whole chain is invalid on `.workspace-frame` and every descendant
//     reads "". The fixture therefore supplies the `--tt-*` values on the same
//     `.tailkit-workspace-content` shell the account pages render inside, which
//     is what the already-converted kit/settings/mobile-workspace suites do.
//   * The daisyUI / `@theme` typography scale is likewise unavailable, so
//     `--text-body-sm` (used by `.user-account-form [data-slot="form-label"]`)
//     is unasserted; the label colour and the field control geometry, which
//     carry the same "the form is styled by users.css, not by a browser
//     default" contract, are asserted instead.

const desktop = 1280;
const phone = 390;

const accountTokens = {
  "--tt-border": "#d4dce6",
  "--tt-ink": "#172033",
  "--tt-ink-muted": "#5a6a80",
  "--tt-surface-lift": "#fffcf8",
  "--tt-accent-soft": "#e6f2f1",
  "--tt-accent-strong": "#0b7285",
} as React.CSSProperties;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

const create = vi.fn(() => Promise.resolve({ data: { id: 7 } }));
const notify = vi.fn();

const mountAccountForm = (children: ReactNode) => (
  <TestMemoryRouter>
    <QueryClientProvider client={new QueryClient()}>
      <TestMessages>
        <StoreContextProvider value={memoryStore()}>
          <DataProviderContext.Provider
            value={
              {
                create,
                getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
                getOne: vi.fn(() => Promise.resolve({ data: {} })),
                getMany: vi.fn(() => Promise.resolve({ data: [] })),
                getManyReference: vi.fn(() =>
                  Promise.resolve({ data: [], total: 0 }),
                ),
                update: vi.fn(() => Promise.resolve({ data: {} })),
                delete: vi.fn(() => Promise.resolve({ data: {} })),
                updateMany: vi.fn(() => Promise.resolve({ data: [] })),
                deleteMany: vi.fn(() => Promise.resolve({ data: [] })),
              } as never
            }
          >
            {/* `addNotification` is the only half UserCreate touches; the tuple
                type is narrower than NotificationContextType, so it is widened
                here rather than stubbing the full notification store. */}
            <NotificationContext.Provider value={[notify, vi.fn()] as never}>
              <main
                className="tailkit-workspace-content"
                style={accountTokens}
              >
                {children}
              </main>
            </NotificationContext.Provider>
          </DataProviderContext.Provider>
        </StoreContextProvider>
      </TestMessages>
    </QueryClientProvider>
  </TestMemoryRouter>
);

const renderedForm = async () => {
  const screen = await render(mountAccountForm(<UserCreate />));
  return screen;
};

describe("account form content plane", () => {
  it("draws the account form as a flat ruled band, not a raised card", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const form = screen.container.querySelector<HTMLElement>(
      ".user-account-form",
    )!;
    const styles = getComputedStyle(form);

    // One flat plane: ruled top and bottom edges, no fill of its own. A card
    // frame here (radius + shadow + opaque background) is what the old
    // `not.toContain("@/components/ui/card")` source pin was guarding.
    expect(styles.borderBlockStartWidth).toBe("1px");
    expect(styles.borderBlockStartStyle).toBe("solid");
    expect(styles.borderBlockEndWidth).toBe("1px");
    expect(styles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(styles.borderRadius).toBe("0px");
    expect(styles.boxShadow).toBe("none");
    // The rendered proof of "does not import the card component": no Card
    // element and no card class survives anywhere inside the form.
    expect(form.querySelector('[data-slot="card"]')).toBeNull();
    expect(form.className).not.toContain("tt-card");
    expect(form.innerHTML).not.toContain("tt-card");
  });

  it("separates the form header from its body with a rule", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const header = screen.container.querySelector<HTMLElement>(
      ".user-account-form-header",
    )!;
    const headerStyles = getComputedStyle(header);
    expect(headerStyles.borderBottomWidth).toBe("1px");
    expect(headerStyles.borderBottomStyle).toBe("solid");
    // The header is a band, not a second card.
    expect(headerStyles.minHeight).toBe("72px");
    expect(headerStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  });
});

describe("account form field grid", () => {
  it("lays the account fields out in two columns on desktop", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const grid = screen.container.querySelector<HTMLElement>(
      ".user-account-field-grid",
    )!;
    const tracks = Array.from(
      screen.container.querySelectorAll<HTMLElement>(".user-account-field"),
    );
    const rects = tracks.map((field) => field.getBoundingClientRect());

    // `.user-account-field-wide` (Email) owns the full row on its own; the
    // remaining fields share a second row. A single-column fallback put the
    // full-width email on the same visual line as the other fields.
    expect(rects[0].width).toBeGreaterThan(rects[1].width);
    expect(rects[1].top).toBeCloseTo(rects[2].top, 0);
    expect(rects[2].left).toBeGreaterThan(rects[1].left);
    expect(getComputedStyle(grid).gridTemplateColumns.split(" ")).toHaveLength(
      2,
    );
  });

  it("stacks every account field on one column at phone width", async () => {
    await page.viewport(phone, 844);
    const screen = await renderedForm();

    const tracks = Array.from(
      screen.container.querySelectorAll<HTMLElement>(".user-account-field"),
    );
    const rects = tracks.map((field) => field.getBoundingClientRect());

    // At 760px the grid drops to `minmax(0, 1fr)` and `.user-account-field-wide`
    // gives up its full-row span, so all five fields share one narrow track.
    for (const field of tracks) {
      expect(
        field.getBoundingClientRect().width,
        field.className,
      ).toBeCloseTo(rects[0].width, 0);
    }
    for (let index = 1; index < rects.length; index += 1) {
      expect(
        rects[index].top,
        tracks[index].className,
      ).toBeGreaterThanOrEqual(rects[index - 1].bottom - 1);
    }
  });

  it("keeps every account control a full-height touch target", async () => {
    // `.user-account-form [data-slot="form-control"]` pins 44px; the label
    // typography token is unavailable in this lane, so the geometry carries it.
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const controls = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        '.user-account-form [data-slot="form-control"], .user-account-form [data-slot="select-trigger"]',
      ),
    );
    expect(controls.length).toBeGreaterThanOrEqual(4);

    for (const control of controls) {
      const styles = getComputedStyle(control);
      expect(styles.height, control.outerHTML).toBe("44px");
      expect(styles.minHeight, control.outerHTML).toBe("44px");
      expect(control.getBoundingClientRect().height, control.outerHTML)
        .toBeGreaterThanOrEqual(44);
    }
  });
});

describe("account form actions", () => {
  it("holds every desktop action at the 44px comfortable height", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const actions = screen.container.querySelector<HTMLElement>(
      ".user-account-form-actions",
    )!;
    const buttons = Array.from(
      actions.querySelectorAll<HTMLElement>('[data-slot="button"], a'),
    );
    expect(buttons).toHaveLength(2);

    for (const button of buttons) {
      const styles = getComputedStyle(button);
      expect(styles.height, button.outerHTML).toBe("44px");
      expect(styles.minHeight, button.outerHTML).toBe("44px");
    }
    // The actions sit on their own ruled band, right-aligned on desktop.
    expect(getComputedStyle(actions).justifyContent).toBe("flex-end");
    expect(getComputedStyle(actions).borderTopWidth).toBe("1px");
  });

  it("stacks the account actions full-width at phone width", async () => {
    await page.viewport(phone, 844);
    const screen = await renderedForm();

    const actions = screen.container.querySelector<HTMLElement>(
      ".user-account-form-actions",
    )!;
    const buttons = Array.from(
      actions.querySelectorAll<HTMLElement>('[data-slot="button"], a'),
    );

    // The DOM order is cancel-then-submit, so `column-reverse` paints the
    // submit above the cancel — the primary action first on a phone.
    expect(getComputedStyle(actions).flexDirection).toBe("column-reverse");
    const [cancel, submit] = buttons;
    expect(submit.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      cancel.getBoundingClientRect().top + 1,
    );
    for (const button of buttons) {
      expect(button.getBoundingClientRect().width, button.outerHTML)
        .toBeCloseTo(actions.getBoundingClientRect().width, 0);
      expect(getComputedStyle(button).height, button.outerHTML).toBe("44px");
    }
  });
});

describe("account form validation", () => {
  it("blocks the create call and names every empty required field", async () => {
    create.mockClear();
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    // The old pins asserted the literal `required("Vui lòng nhập thông tin.")`
    // and `email("Email chưa đúng định dạng.")` in the source. What matters is
    // that an empty submit surfaces the Vietnamese message and never reaches
    // the data provider.
    await expect
      .poll(() =>
        Array.from(screen.container.querySelectorAll("p")).filter((node) =>
          (node.textContent ?? "").includes("Vui lòng nhập thông tin."),
        ).length,
      )
      .toBeGreaterThanOrEqual(4);
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects a malformed email before sending data", async () => {
    // Two layers guard the email, and this walks both. The input is
    // `type="email"`, so a value with no `@` never reaches the form at all —
    // the browser's own constraint stops the submit. `a@b` clears that
    // constraint but is still not an address ra will accept, so the
    // Vietnamese `email("Email chưa đúng định dạng.")` message is what the
    // recruiter sees. Either way `create` must not fire.
    create.mockClear();
    await page.viewport(desktop, 720);
    const screen = await renderedForm();
    const email = screen.container.querySelector<HTMLInputElement>(
      'input[name="email"]',
    )!;

    await screen
      .getByRole("textbox", { name: /Họ và tên/ })
      .fill("Nguyễn Minh Anh");
    await screen.getByLabelText("Vai trò").click();
    await screen.getByRole("option", { name: "Tuyển dụng" }).click();
    await screen
      .getByRole("textbox", { name: "Mật khẩu", exact: true })
      .fill("matkhau");
    await screen
      .getByRole("textbox", { name: "Xác nhận mật khẩu" })
      .fill("matkhau");

    // Layer 1 — the native email constraint blocks the submit outright.
    await screen
      .getByRole("textbox", { name: /Email/ })
      .fill("khong-phai-email");
    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();
    expect(create).not.toHaveBeenCalled();
    expect(email.checkValidity()).toBe(false);

    // Layer 2 — a value the browser accepts but ra rejects surfaces the
    // Vietnamese message and still never reaches the data provider.
    await screen.getByRole("textbox", { name: /Email/ }).fill("a@b");
    expect(email.checkValidity()).toBe(true);
    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();
    await expect
      .poll(() =>
        screen.container.textContent?.includes(
          "Email chưa đúng định dạng.",
        ) ?? false,
      )
      .toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("submits and reports progress once the required details are valid", async () => {
    // Replaces the `toContain("Đang tạo")` source pin with the real pending
    // state: while `create` is in flight the submit control is disabled and
    // relabels itself, so a recruiter sees the request is running.
    // `Promise.withResolvers` is ES2024 and this project targets ES2022, so the
    // pending promise is built with an explicit resolver.
    let resolveCreate!: (value: { data: { id: number } }) => void;
    const promise = new Promise<{ data: { id: number } }>((resolve) => {
      resolveCreate = resolve;
    });
    create.mockClear();
    create.mockReturnValueOnce(promise as never);
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await screen.getByRole("textbox", { name: /Email/ }).fill("recruiter@vfic.dev");
    await screen.getByRole("textbox", { name: /Họ và tên/ }).fill("Nguyễn Minh Anh");
    await screen
      .getByRole("textbox", { name: "Mật khẩu", exact: true })
      .fill("matkhau");
    await screen.getByRole("textbox", { name: "Xác nhận mật khẩu" }).fill("matkhau");

    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    const pending = screen.getByRole("button", { name: "Đang tạo" });
    await expect.element(pending).toBeVisible();
    expect(pending.element().hasAttribute("disabled")).toBe(true);

    resolveCreate({ data: { id: 7 } });
    await expect
      .poll(() => create.mock.calls.length)
      .toBe(1);
    // The provider is called as `create("users", { data })`, so the payload
    // lands in the second argument.
    const [resource, params] = create.mock.calls[0] as unknown as [
      string,
      { data: Record<string, unknown> },
    ];
    expect(resource).toBe("users");
    expect(params.data).toMatchObject({
      email: "recruiter@vfic.dev",
      full_name: "Nguyễn Minh Anh",
    });
    // The confirm-password field is a client-side check only; it must not be
    // shipped to the users endpoint.
    expect(params.data).not.toHaveProperty("confirm_password");
  });
});
