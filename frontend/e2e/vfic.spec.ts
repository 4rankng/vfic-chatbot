import { expect, test } from "./fixtures";
import type { Locator, Page } from "@playwright/test";

/** Check painted controls, not document width alone: overflow:hidden can crop
 * a field without widening the document. Scroll-edge clipping and off-canvas
 * sheets are intentional; transcript rows are measured by their own tests. */
async function expectMobileControlGeometry(page: Page, context: string) {
  await expect
    .poll(
      async () =>
        page.evaluate(() => {
          const issues: string[] = [];
          const tolerance = 2;
          const describe = (element: Element) =>
            `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}[${element.getAttribute("aria-label") ?? element.getAttribute("name") ?? [...element.classList].slice(0, 2).join(".")}]`;
          const parents = (element: Element) => {
            const result: Element[] = [];
            for (
              let parent = element.parentElement;
              parent;
              parent = parent.parentElement
            )
              result.push(parent);
            return result;
          };
          const hasEmptyCssClip = (element: Element) => {
            const style = getComputedStyle(element);
            const bounds = element.getBoundingClientRect();
            const length = (value: string, size: number) =>
              /^-?(?:\d+\.?\d*|\.\d+)(?:px|%)?$/.test(value)
                ? (Number.parseFloat(value) *
                    (value.endsWith("%") ? size : 100)) /
                  100
                : Number.NaN;
            // React Aria focus guards stay in the accessibility tree, but their
            // absolute wrapper clips away every pixel even if a shared control
            // floor makes the nested button's layout box 40px tall. Check the
            // actual clip geometry, never a guard's label or generated id.
            const rectangle = style.clip.match(/^rect\((.*)\)$/);
            if (rectangle && /^(absolute|fixed)$/.test(style.position)) {
              const values = rectangle[1].trim().split(/[\s,]+/);
              if (values.length === 4) {
                const dimensions = [bounds.height, bounds.width];
                const defaults = [0, bounds.width, bounds.height, 0];
                const [top, right, bottom, left] = values.map((value, index) =>
                  value === "auto"
                    ? defaults[index]
                    : length(value, dimensions[index % 2]),
                );
                if (
                  Math.min(bounds.width, right) <= Math.max(0, left) ||
                  Math.min(bounds.height, bottom) <= Math.max(0, top)
                )
                  return true;
              }
            }
            const inset = style.clipPath.match(
              /^inset\((.*)\)(?:\s+(?:border|padding|content|margin)-box)?$/,
            );
            if (!inset) return false;
            const values = inset[1]
              .split(/\s+round\s+/)[0]
              .trim()
              .split(/\s+/);
            if (values.length < 1 || values.length > 4) return false;
            const [top, right = top, bottom = top, left = right] = values;
            // Unknown expressions stay measurable: only a provably empty clip
            // is excluded, so partially clipped real controls still fail below.
            return (
              length(left, bounds.width) + length(right, bounds.width) >=
                bounds.width ||
              length(top, bounds.height) + length(bottom, bounds.height) >=
                bounds.height
            );
          };
          const painted = (element: Element, decorative = false) => {
            const ancestors = parents(element);
            if (
              element.closest("[hidden], [inert]") ||
              (!decorative && element.closest('[aria-hidden="true"]')) ||
              ancestors.some(
                (parent) =>
                  parent.matches("details:not([open])") &&
                  !parent.querySelector(":scope > summary")?.contains(element),
              )
            )
              return false;
            const rect = element.getBoundingClientRect();
            const exposed = exposedBounds(element, ancestors);
            return (
              rect.width > 0 &&
              rect.height > 0 &&
              exposed.right > exposed.left &&
              exposed.bottom > exposed.top &&
              [element, ...ancestors].every((node) => {
                const style = getComputedStyle(node);
                return (
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity) !== 0 &&
                  !hasEmptyCssClip(node)
                );
              })
            );
          };
          const scrolls = (element: Element, axis: "x" | "y") => {
            const style = getComputedStyle(element);
            return (
              /^(auto|scroll|overlay)$/.test(
                axis === "x" ? style.overflowX : style.overflowY,
              ) &&
              (axis === "x"
                ? element.scrollWidth > element.clientWidth + tolerance
                : element.scrollHeight > element.clientHeight + tolerance)
            );
          };
          const clip = (element: Element) => {
            const rect = element.getBoundingClientRect();
            return {
              left: rect.left + element.clientLeft,
              top: rect.top + element.clientTop,
              right: rect.left + element.clientLeft + element.clientWidth,
              bottom: rect.top + element.clientTop + element.clientHeight,
            };
          };
          const exposedBounds = (
            element: Element,
            ancestors = parents(element),
          ) => {
            const rect = element.getBoundingClientRect();
            const exposed = {
              left: Math.max(0, rect.left),
              top: Math.max(0, rect.top),
              right: Math.min(innerWidth, rect.right),
              bottom: Math.min(innerHeight, rect.bottom),
            };
            // Scrolled fields keep their layout boxes behind fixed siblings.
            // Only their exposed pixels can overlap another control. Intersect
            // genuine scrollports; hidden/clip wrappers still get the full-box
            // crop checks below, so a broken wrapper cannot disappear here.
            for (const ancestor of ancestors) {
              const bounds = clip(ancestor);
              if (scrolls(ancestor, "x")) {
                exposed.left = Math.max(exposed.left, bounds.left);
                exposed.right = Math.min(exposed.right, bounds.right);
              }
              if (scrolls(ancestor, "y")) {
                exposed.top = Math.max(exposed.top, bounds.top);
                exposed.bottom = Math.min(exposed.bottom, bounds.bottom);
              }
            }
            return exposed;
          };
          const contains = (outer: DOMRect, inner: DOMRect) =>
            inner.left >= outer.left - tolerance &&
            inner.right <= outer.right + tolerance &&
            inner.top >= outer.top - tolerance &&
            inner.bottom <= outer.bottom + tolerance;
          const controls = [
            ...document.querySelectorAll(
              'main button, main a[href], main input:not([type="hidden"]), main textarea, main select, main summary, main [role="button"], main [role="combobox"], main [role="switch"], main [role="checkbox"], .workspace-topbar button, .workspace-topbar a[href], [role="dialog"] button, [role="dialog"] input:not([type="hidden"]), [role="dialog"] textarea, [role="dialog"] [role="combobox"], [role="menu"] [role^="menuitem"]',
            ),
          ].filter(
            (element) => painted(element) && !element.closest('[role="log"]'),
          );
          const surfaces = [
            ...document.querySelectorAll(
              'main form, [role="dialog"] form, [role="dialog"], [role="alertdialog"]',
            ),
          ].filter((element) => painted(element));
          for (const element of [...controls, ...surfaces]) {
            const rect = element.getBoundingClientRect();
            if (
              element.matches(
                '.conversation-header-identity-button, .conversation-header-back, .conversation-header-actions-button, .reply-mode-trigger, .composer-action.send, .context-close, .candidate-profile-edit-trigger, button[aria-label="Hiện mật khẩu"], button[aria-label="Ẩn mật khẩu"], .settings-input-action, .settings-copy-app-id',
              ) &&
              (rect.width < 44 - tolerance || rect.height < 44 - tolerance)
            )
              issues.push(
                `${describe(element)} has a touch target smaller than 44px`,
              );
            if (
              element.matches(
                '.candidate-profile-edit-actions > button, .candidate-profile-edit-form input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])',
              )
            ) {
              const frame = element.matches("input")
                ? (element.closest('[class~="group/input"]') ?? element)
                : element;
              if (Math.abs(frame.getBoundingClientRect().height - 40) > 0.5)
                issues.push(
                  `${describe(element)} should use the 40px form tier`,
                );
            }
            const ancestors = parents(element);
            const horizontalScroller = ancestors.some((parent) =>
              scrolls(parent, "x"),
            );
            const verticalScrollEdge = ancestors.some((parent) => {
              if (!scrolls(parent, "y")) return false;
              const bounds = clip(parent);
              return (
                rect.top < bounds.top - tolerance ||
                rect.bottom > bounds.bottom + tolerance
              );
            });
            if (
              !horizontalScroller &&
              (rect.left < -tolerance || rect.right > innerWidth + tolerance)
            )
              issues.push(`${describe(element)} extends past the phone width`);
            for (const ancestor of ancestors) {
              const style = getComputedStyle(ancestor);
              const bounds = clip(ancestor);
              if (
                !horizontalScroller &&
                /^(hidden|clip)$/.test(style.overflowX) &&
                (rect.left < bounds.left - tolerance ||
                  rect.right > bounds.right + tolerance)
              )
                issues.push(
                  `${describe(element)} is cropped horizontally by ${describe(ancestor)}`,
                );
              // Controls can legitimately straddle a vertical scroll edge or the
              // document fold. A hidden fixed-height wrapper inside it cannot crop
              // a fully on-screen control, though.
              if (
                rect.top >= 0 &&
                rect.bottom <= innerHeight &&
                !verticalScrollEdge &&
                /^(hidden|clip)$/.test(style.overflowY) &&
                (rect.top < bounds.top - tolerance ||
                  rect.bottom > bounds.bottom + tolerance)
              )
                issues.push(
                  `${describe(element)} is cropped vertically by ${describe(ancestor)}`,
                );
            }
            if (
              element.matches('[role="dialog"], [role="alertdialog"]') &&
              (rect.top < -tolerance || rect.bottom > innerHeight + tolerance)
            )
              issues.push(`${describe(element)} extends past the phone height`);
          }
          // Popovers, dialogs and sticky navigation cover scrolling page content.
          // Compare controls within each surface. Settings fields are separately
          // hit-tested after scrolling so the navigation cannot hide an active field.
          const surface = (element: Element) =>
            element.closest(
              '[role="dialog"], [role="alertdialog"], [role="menu"], .workspace-topbar, .settings-mobile-topbar',
            ) ?? document.querySelector("main");
          const reservedPasswordAction = (first: Element, second: Element) => {
            const input = first.matches("input") ? first : second;
            const action = input === first ? second : first;
            if (
              !input.matches("input") ||
              !action.matches("button") ||
              !action.parentElement?.contains(input) ||
              !/^(Hiện|Ẩn) mật khẩu$/.test(
                action.getAttribute("aria-label") ?? "",
              )
            )
              return false;
            const field = input.getBoundingClientRect();
            const button = action.getBoundingClientRect();
            const glyphs = [...action.querySelectorAll("svg, img")].filter(
              (icon) => painted(icon, true),
            );
            const row = action.parentElement.getBoundingClientRect();
            // A centered 44px hit target can extend 2px around a 40px field.
            // Its glyph still fits the field and its trailing padding, while
            // the action stays in its own row. Other controls are compared below.
            return (
              glyphs.length > 0 &&
              glyphs.every((icon) =>
                contains(field, icon.getBoundingClientRect()),
              ) &&
              contains(row, button) &&
              button.left >=
                field.right -
                  Number.parseFloat(getComputedStyle(input).paddingRight) -
                  tolerance &&
              button.right <= field.right + tolerance
            );
          };
          for (let index = 0; index < controls.length; index++) {
            const first = controls[index];
            const firstRect = first.getBoundingClientRect();
            const firstExposed = exposedBounds(first);
            for (const second of controls.slice(index + 1)) {
              if (
                first.contains(second) ||
                second.contains(first) ||
                surface(first) !== surface(second) ||
                reservedPasswordAction(first, second)
              )
                continue;
              const secondExposed = exposedBounds(second);
              if (
                Math.min(firstExposed.right, secondExposed.right) -
                  Math.max(firstExposed.left, secondExposed.left) >
                  tolerance &&
                Math.min(firstExposed.bottom, secondExposed.bottom) -
                  Math.max(firstExposed.top, secondExposed.top) >
                  tolerance
              )
                issues.push(`${describe(first)} overlaps ${describe(second)}`);
            }
            for (const icon of first.querySelectorAll("svg, img")) {
              if (!painted(icon, true)) continue;
              const bounds = icon.getBoundingClientRect();
              if (bounds.width < 10 || bounds.height < 10)
                issues.push(`${describe(first)} has a collapsed glyph`);
              if (!contains(firstRect, bounds))
                issues.push(
                  `${describe(first)} has a glyph outside its control`,
                );
            }
          }
          return [...new Set(issues)];
        }),
      {
        message: `${context}: visible controls must fit without cropping or overlap`,
      },
    )
    .toEqual([]);
}

async function expectMobileFormDensity(
  page: Page,
  selector: string,
  context: string,
) {
  await expect
    .poll(
      () =>
        page.evaluate((scopeSelector) => {
          const issues: string[] = [];
          const coarse = matchMedia("(pointer: coarse)").matches;
          const scopes = [...document.querySelectorAll(scopeSelector)];
          const painted = (element: Element) => {
            const rect = element.getBoundingClientRect();
            if (
              rect.width === 0 ||
              rect.height === 0 ||
              rect.right <= 0 ||
              rect.left >= innerWidth ||
              rect.bottom <= 0 ||
              rect.top >= innerHeight ||
              element.closest('[hidden], [inert], [aria-hidden="true"]')
            )
              return false;
            for (
              let node: Element | null = element;
              node;
              node = node.parentElement
            ) {
              const style = getComputedStyle(node);
              if (
                style.display === "none" ||
                style.visibility === "hidden" ||
                Number(style.opacity) === 0 ||
                (node !== element &&
                  node.matches("details:not([open])") &&
                  !node.querySelector(":scope > summary")?.contains(element))
              )
                return false;
            }
            return true;
          };
          const collect = (query: string) =>
            [
              ...new Set(
                scopes.flatMap((scope) => [...scope.querySelectorAll(query)]),
              ),
            ].filter(painted);
          const fields = collect(
            'input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]), textarea, select',
          );
          const labels = collect("label, .account-profile-field-label");
          if (fields.length === 0)
            issues.push("no visible native form fields were checked");
          if (labels.length === 0)
            issues.push("no visible form labels were checked");
          const near = (actual: number, expected: number) =>
            Math.abs(actual - expected) <= 0.5;
          const name = (element: Element) =>
            element.id ||
            element.getAttribute("name") ||
            element.tagName.toLowerCase();
          for (const field of fields) {
            const editable = !field.matches(
              'select, :disabled, [readonly], [aria-readonly="true"], [aria-disabled="true"]',
            );
            const expectedFont = coarse && editable ? 16 : 12;
            if (
              !near(
                Number.parseFloat(getComputedStyle(field).fontSize),
                expectedFont,
              )
            )
              issues.push(`${name(field)} should use ${expectedFont}px values`);
            if (field.matches("textarea")) continue;
            const frame = field.closest('[class~="group/input"]') ?? field;
            if (!near(frame.getBoundingClientRect().height, 40))
              issues.push(`${name(field)} should have a 40px field frame`);
          }
          for (const label of labels)
            if (!near(Number.parseFloat(getComputedStyle(label).fontSize), 13))
              issues.push(`${name(label)} should use 13px labels`);
          for (const trigger of collect('button[aria-haspopup="listbox"]')) {
            if (!near(trigger.getBoundingClientRect().height, 40))
              issues.push("select should have a 40px field frame");
            const values = [...trigger.querySelectorAll("p")].filter(painted);
            if (values.length === 0)
              issues.push("selected value text is missing");
            for (const value of values)
              if (
                !near(Number.parseFloat(getComputedStyle(value).fontSize), 12)
              )
                issues.push("select should use 12px selected values");
          }
          return [...new Set(issues)];
        }, selector),
      {
        message: `${context}: compact field frames and text must share the control scale`,
      },
    )
    .toEqual([]);
}

async function expectSettingsFieldExposure(field: Locator, context: string) {
  await expect
    .poll(
      () =>
        field.evaluate((element) => {
          const issues: string[] = [];
          const navigation = document.querySelector(".settings-mobile-topbar");
          if (!navigation) return ["sticky settings navigation is missing"];
          const frame = element.closest('[class~="group/input"]') ?? element;
          const rect = frame.getBoundingClientRect();
          const navigationRect = navigation.getBoundingClientRect();
          let scrollTop = 0;
          let scrollBottom = innerHeight;
          for (
            let parent = frame.parentElement;
            parent;
            parent = parent.parentElement
          ) {
            if (
              /^(auto|scroll|overlay)$/.test(
                getComputedStyle(parent).overflowY,
              ) &&
              parent.scrollHeight > parent.clientHeight + 2
            ) {
              const bounds = parent.getBoundingClientRect();
              scrollTop = Math.max(0, bounds.top + parent.clientTop);
              scrollBottom = Math.min(
                innerHeight,
                scrollTop + parent.clientHeight,
              );
              break;
            }
          }
          if (rect.top < Math.max(scrollTop, navigationRect.bottom) - 2)
            issues.push("scrolled field is covered by sticky navigation");
          if (rect.bottom > scrollBottom + 2)
            issues.push("scrolled field extends past its scroll viewport");
          if (rect.left < -2 || rect.right > innerWidth + 2)
            issues.push("scrolled field extends past the phone width");
          for (const y of [
            rect.top + 2,
            (rect.top + rect.bottom) / 2,
            rect.bottom - 2,
          ]) {
            const exposed = document.elementFromPoint(
              (rect.left + rect.right) / 2,
              y,
            );
            if (!exposed || !frame.contains(exposed))
              issues.push("scrolled field is not exposed for interaction");
          }
          return [...new Set(issues)];
        }),
      {
        message: `${context}: scrolled fields remain exposed below sticky navigation`,
      },
    )
    .toEqual([]);
}

async function expectExpandedMobileSettings(page: Page, context: string) {
  const groups = page.locator("main details.settings-mobile-group");
  expect(
    await groups.count(),
    "mobile settings retain expandable groups",
  ).toBeGreaterThan(0);
  for (let index = 0; index < (await groups.count()); index++) {
    const group = groups.nth(index);
    const summary = group.locator(":scope > summary");
    const wasOpen = (await group.getAttribute("open")) !== null;
    if (!wasOpen) await summary.click();
    await expect(group).toHaveAttribute("open", "");
    await summary.scrollIntoViewIfNeeded();
    await expectMobileControlGeometry(
      page,
      `${context}, expanded group ${index + 1}`,
    );
    await expectMobileFormDensity(
      page,
      ".settings-field",
      `${context}, expanded group ${index + 1}`,
    );

    const fields = group.locator(
      'input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]):visible, textarea:visible',
    );
    expect(
      await fields.count(),
      "expanded settings expose their fields",
    ).toBeGreaterThan(0);
    for (const [position, field] of [
      ["first", fields.first()],
      ["last", fields.last()],
    ] as const) {
      await field.scrollIntoViewIfNeeded();
      await expectSettingsFieldExposure(
        field,
        `${context}, ${position} field in group ${index + 1}`,
      );
      await expectMobileControlGeometry(
        page,
        `${context}, ${position} field in group ${index + 1}`,
      );
      await expectMobileFormDensity(
        page,
        ".settings-field",
        `${context}, ${position} field in group ${index + 1}`,
      );
    }

    // Auxiliary disclosures, such as OA webhook health, are also checked open.
    // Their collapsed contents must not masquerade as painted controls.
    const disclosures = group.locator("details");
    for (
      let detailIndex = 0;
      detailIndex < (await disclosures.count());
      detailIndex++
    ) {
      const disclosure = disclosures.nth(detailIndex);
      const detailSummary = disclosure.locator(":scope > summary");
      const detailWasOpen = (await disclosure.getAttribute("open")) !== null;
      if (!detailWasOpen) await detailSummary.click();
      await expect(disclosure).toHaveAttribute("open", "");
      await expectMobileControlGeometry(
        page,
        `${context}, auxiliary disclosure ${detailIndex + 1}`,
      );
      if (!detailWasOpen) {
        await detailSummary.click();
        await expect(disclosure).not.toHaveAttribute("open", "");
      }
    }
    if (!wasOpen) {
      await summary.click();
      await expect(group).not.toHaveAttribute("open", "");
    }
  }
}

async function expectUnboxedConversationGlyphs(
  page: Page,
  selectors: string[],
) {
  // Pointer/focus decoration is deliberate. Measure the resting visual
  // contract, without treating conventional form fields/buttons as glyphs.
  await page.mouse.move(1, 1);
  for (const selector of selectors) {
    await expect(page.locator(selector).first()).toBeVisible();
    const boxed = await page.locator(selector).evaluateAll((elements) =>
      elements
        .filter((element) => {
          if (element.matches(":hover, :focus-visible")) return false;
          const style = getComputedStyle(element);
          const transparent =
            style.backgroundColor === "transparent" ||
            /rgba\([^)]*,\s*0\)$/.test(style.backgroundColor);
          return (
            !transparent ||
            style.backgroundImage !== "none" ||
            style.boxShadow !== "none" ||
            [
              style.borderTopWidth,
              style.borderRightWidth,
              style.borderBottomWidth,
              style.borderLeftWidth,
            ].some((width) => Number.parseFloat(width) > 0)
          );
        })
        .map((element) => [...element.classList].join(".")),
    );
    expect(boxed, `${selector} should render as a bare glyph at rest`).toEqual(
      [],
    );
  }
}

async function expectMobileAccountRows(page: Page, context: string) {
  const rows = page.locator(".user-directory-row");
  await expect(rows.first()).toBeVisible();
  await expect
    .poll(
      () =>
        rows.evaluateAll((elements) => {
          const issues: string[] = [];
          for (const row of elements) {
            const bounds = row.getBoundingClientRect();
            if (bounds.height === 0) continue;
            const parts = [
              row.querySelector(".user-directory-identity"),
              row.querySelector(".user-directory-role > *"),
              row.querySelector(".user-directory-status > *"),
              row.querySelector(".user-directory-created"),
              row.querySelector(".user-directory-created > span"),
            ].filter((element): element is Element => element !== null);
            if (parts.length !== 5)
              issues.push("account identity, role, status, or date is missing");
            for (const part of parts) {
              const rect = part.getBoundingClientRect();
              if (
                rect.left < Math.max(0, bounds.left) - 2 ||
                rect.right > Math.min(innerWidth, bounds.right) + 2
              )
                issues.push(
                  `${part.className || part.tagName} extends outside its account row`,
                );
            }
            // These are independent pieces of account metadata. Unlike a table's
            // row/cell boxes, their visible badges and date must never intersect.
            const metadata = [
              row.querySelector(".user-directory-role > *"),
              row.querySelector(".user-directory-status > *"),
              row.querySelector(".user-directory-created"),
            ].filter((element): element is Element => element !== null);
            for (let index = 0; index < metadata.length; index++) {
              const first = metadata[index].getBoundingClientRect();
              for (const second of metadata.slice(index + 1)) {
                const rect = second.getBoundingClientRect();
                if (
                  Math.min(first.right, rect.right) -
                    Math.max(first.left, rect.left) >
                    2 &&
                  Math.min(first.bottom, rect.bottom) -
                    Math.max(first.top, rect.top) >
                    2
                )
                  issues.push("account role, status, and date overlap");
              }
            }
          }
          return [...new Set(issues)];
        }),
      {
        message: `${context}: account metadata must fit inside separate mobile rows`,
      },
    )
    .toEqual([]);
}

test.describe("current recruitment workspace baseline", () => {
  test("keeps workspace pages inside phone, tablet, and desktop viewports", async ({
    loginAsAdmin,
    page,
  }, testInfo) => {
    test.setTimeout(180_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await loginAsAdmin();
    const routes = [
      ["/", "Tổng quan"],
      ["/projects", "Dự án tuyển dụng"],
      ["/projects/create", "Tạo dự án"],
      ["/users", "Tài khoản"],
      ["/users/create", "Tạo tài khoản"],
      ["/bot_runs", "Lần chạy bot"],
      ["/settings", "Zalo"],
      ["/profile", "Hồ sơ cá nhân"],
      ["/hieu-suat", "Hiệu suất chatbot"],
      ["/conversations", "Hộp thư"],
    ];
    for (const width of [320, 360, 390, 768, 900, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      for (const [route, heading] of routes) {
        await page.goto(`/#${route}`);
        // An arbitrary heading also matches a 404 page. Assert the actual
        // screen so a typo or removed route cannot count as layout coverage.
        await expect(
          page.getByRole("heading", { name: heading, exact: true }).first(),
        ).toBeVisible({ timeout: 15_000 });
        await page.evaluate(() => document.fonts.ready);
        await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0);
        await expect(page.locator('main [data-slot="skeleton"]')).toHaveCount(
          0,
        );
        await expect(
          page.getByRole("status", { name: /^Đang tải/ }),
        ).toHaveCount(0);
        if (route === "/bot_runs") {
          await expect(
            page.getByRole("button", { name: /^Xem lần chạy #/ }).first(),
          ).toBeVisible();
        }
        await expect
          .poll(
            () =>
              page.evaluate(
                () =>
                  document.documentElement.scrollWidth -
                  document.documentElement.clientWidth,
              ),
            { message: `${route} must fit a ${width}px viewport` },
          )
          .toBeLessThanOrEqual(1);
        if (width < 768) {
          await expectMobileControlGeometry(page, `${route} at ${width}px`);
          if (route === "/users") {
            await expectMobileAccountRows(
              page,
              `account directory at ${width}px`,
            );
          }
          if (route === "/settings") {
            await expectExpandedMobileSettings(page, `settings at ${width}px`);
            await page
              .getByRole("button", { name: "Mở danh mục cài đặt", exact: true })
              .click();
            await page
              .getByRole("navigation", { name: "Mục cài đặt", exact: true })
              .getByRole("button", { name: /^Người dùng / })
              .click();
            await expect(
              page
                .getByRole("heading", { name: "Người dùng", exact: true })
                .first(),
            ).toBeVisible();
            await expectMobileAccountRows(
              page,
              `embedded settings accounts at ${width}px`,
            );
            await expectMobileControlGeometry(
              page,
              `embedded settings accounts at ${width}px`,
            );
          }
          if (route === "/profile") {
            await page
              .getByRole("button", { name: "Sửa", exact: true })
              .click();
            await expect(
              page.locator(".account-profile-field-editing input").first(),
            ).toBeVisible();
            await expectMobileControlGeometry(
              page,
              `profile edit at ${width}px`,
            );
          }
          const densityScope =
            route === "/users/create"
              ? ".user-account-form"
              : route === "/projects/create"
                ? ".project-create-fields"
                : route === "/profile"
                  ? ".account-profile-field-grid"
                  : null;
          if (densityScope) {
            const fields = page.locator(`${densityScope} input:visible`);
            await expect(fields.first()).toBeVisible();
            for (const field of [fields.first(), fields.last()]) {
              await field.scrollIntoViewIfNeeded();
              await expectMobileFormDensity(
                page,
                densityScope,
                `${route} at ${width}px`,
              );
              await expectMobileControlGeometry(
                page,
                `${route} compact fields at ${width}px`,
              );
            }
          }
          const lastFormField = page
            .locator(
              'main form input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]):visible, main form textarea:visible',
            )
            .last();
          if (await lastFormField.count()) {
            await lastFormField.scrollIntoViewIfNeeded();
            await expectMobileControlGeometry(
              page,
              `last form field on ${route} at ${width}px`,
            );
          }
          if (route === "/conversations") {
            await page
              .getByRole("button", { name: /Mở hội thoại với/ })
              .first()
              .click();
            await expect(
              page.getByRole("log", { name: "Luồng tin nhắn" }),
            ).toBeVisible();
            await expectMobileControlGeometry(
              page,
              `conversation at ${width}px`,
            );
            await expectUnboxedConversationGlyphs(page, [
              ".message-avatar",
              ".composer-channel-icon",
            ]);
            await page
              .getByRole("button", { name: "Đổi chế độ trả lời" })
              .click();
            await expect(
              page.getByRole("menu", { name: "Chế độ trả lời" }),
            ).toBeVisible();
            await expectMobileControlGeometry(
              page,
              `reply mode menu at ${width}px`,
            );
            await page.keyboard.press("Escape");
            await page
              .getByRole("button", { name: /Xem thông tin ứng viên của/ })
              .click();
            const candidate = page.locator(
              '[role="dialog"]#conversation-context-panel',
            );
            await expect(candidate).toBeVisible();
            const candidateSize = await candidate.boundingBox();
            expect(
              candidateSize?.width,
              "the phone candidate sheet uses the available width",
            ).toBeGreaterThanOrEqual(width - 2);
            await expectMobileControlGeometry(
              page,
              `candidate sheet at ${width}px`,
            );
            await expectUnboxedConversationGlyphs(page, [
              ".candidate-info-icon",
              ".context-close",
            ]);
            await candidate
              .getByRole("button", {
                name: "Chỉnh sửa hồ sơ ứng viên",
                exact: true,
              })
              .click();
            await expect(
              candidate.getByRole("form", { name: "Chỉnh sửa hồ sơ ứng viên" }),
            ).toBeVisible();
            await expectMobileControlGeometry(
              page,
              `candidate edit at ${width}px`,
            );
            await candidate
              .locator("input:visible, textarea:visible")
              .last()
              .scrollIntoViewIfNeeded();
            await expectMobileControlGeometry(
              page,
              `candidate edit last field at ${width}px`,
            );
            await candidate.locator(".context-close").click();
            await expect(candidate).toBeHidden();
          }
        }
        if (width === 360 || width === 1440) {
          await page.screenshot({
            path: testInfo.outputPath(
              `workspace-${route.replaceAll("/", "-") || "overview"}-${width}.png`,
            ),
            fullPage: true,
            animations: "disabled",
          });
        }
      }
    }
    expect(pageErrors).toEqual([]);
  });

  test("authenticates through FastAPI and renders the recruitment dashboard", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();

    await expect(
      page.getByRole("heading", { name: "Tổng quan" }),
    ).toBeVisible();
  });

  test("loads a real conversation and preserves takeover/release behavior", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/conversations");

    await expect(page.getByRole("heading", { name: "Hộp thư" })).toBeVisible({
      timeout: 15_000,
    });

    // Rendered guards carried over from the former stylesheet/component
    // source-text pins: the inbox must not resurrect the removed count badge
    // or queue-filter controls, and multi-line conversation rows must not be
    // shrunk into the fixed-height button system.
    const listMarkers = await page.evaluate(() => ({
      countBadge:
        document.querySelector(".workspace-conversation-count") !== null,
      queueFilters:
        document.querySelector(
          ".conversation-filters, .conversation-filter",
        ) !== null,
      shrunkRows: document.querySelector(".conversation.tt-btn") !== null,
      rows: document.querySelectorAll(".conversation").length,
    }));
    expect(listMarkers.queueFilters).toBe(false);
    expect(listMarkers.countBadge).toBe(false);
    expect(listMarkers.shrunkRows).toBe(false);
    expect(listMarkers.rows).toBeGreaterThan(0);

    await page
      .getByRole("button", { name: /Mở hội thoại với/ })
      .first()
      .click();
    await expect(
      page
        .getByRole("log", { name: "Luồng tin nhắn" })
        .getByText("E2E bot reply", { exact: true }),
    ).toBeVisible();

    // Desktop keeps its compact directory header; phones provide a 44px touch
    // target. The adapter icon must fit inside either tile.
    const detailMarkers = await page.evaluate(() => {
      const computed = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return null;
        const styles = getComputedStyle(element);
        return {
          width: styles.width,
          height: styles.height,
        };
      };
      const searchInput = document.querySelector<HTMLElement>(
        ".workspace-rail .search input",
      );
      return {
        adapterTile: computed(".channel-adapter-option"),
        adapter: computed(".channel-adapter-option img"),
        modeIcon: computed(
          '.composer-wrap [aria-label="Đổi chế độ trả lời"] svg',
        ),
        adapterCount: document.querySelectorAll(".channel-adapter-option")
          .length,
        searchHeight: searchInput ? getComputedStyle(searchInput).height : null,
      };
    });
    expect(detailMarkers.adapterCount).toBeGreaterThan(0);
    expect(detailMarkers.adapterTile).not.toBeNull();
    expect(detailMarkers.adapter).not.toBeNull();
    expect(detailMarkers.modeIcon).not.toBeNull();
    expect(detailMarkers.searchHeight).not.toBeNull();

    const tile = detailMarkers.adapterTile as { width: string; height: string };
    const icon = detailMarkers.adapter as { width: string; height: string };
    const modeIcon = detailMarkers.modeIcon as {
      width: string;
      height: string;
    };
    const phone = (page.viewportSize()?.width ?? 1280) < 768;
    const globalBar = page.locator(".workspace-topbar");
    if (phone) {
      await expect(globalBar).toBeHidden();
      await expect(
        page.getByRole("button", { name: "Mở danh sách hội thoại" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: /Xem thông tin ứng viên của/ }),
      ).toBeFocused();
    } else {
      await expect(globalBar).toBeVisible();
    }
    const replyMode = page.getByRole("button", {
      name: "Đổi chế độ trả lời",
    });
    await expect(replyMode).toBeVisible();
    await expect(
      page.locator(".composer-wrap").getByRole("button", {
        name: "Đổi chế độ trả lời",
      }),
    ).toBeVisible();
    await expect(
      page.locator(".chat-header").getByRole("button", {
        name: "Đổi chế độ trả lời",
      }),
    ).toHaveCount(0);
    const replyModeSize = await replyMode.boundingBox();
    expect(replyModeSize?.height).toBeGreaterThanOrEqual(44);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (phone) {
      expect(Number.parseFloat(tile.width)).toBeGreaterThanOrEqual(44);
      expect(Number.parseFloat(tile.height)).toBeGreaterThanOrEqual(44);
    } else {
      expect(Number.parseFloat(tile.width)).toBeLessThanOrEqual(40);
      expect(Number.parseFloat(tile.height)).toBeLessThanOrEqual(40);
    }
    expect(Number.parseFloat(icon.width)).toBeLessThanOrEqual(
      Number.parseFloat(tile.width),
    );
    const searchHeight = Number.parseFloat(
      detailMarkers.searchHeight as string,
    );
    if (phone) {
      expect(searchHeight).toBe(40);
    } else {
      expect(searchHeight).toBeLessThanOrEqual(40);
    }
    expect(Number.parseFloat(modeIcon.width)).toBeGreaterThan(10);

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const takeOverResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/take-over") && response.status() === 200,
    );
    await page.getByRole("menuitem").filter({ hasText: "Tư vấn viên" }).click();
    await takeOverResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Tư vấn viên");

    if (phone) {
      for (const width of [320, 360, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(
          page.getByRole("textbox", { name: "Tin nhắn trả lời" }),
        ).toBeVisible();
        await expectMobileControlGeometry(page, `human composer at ${width}px`);
        await expectUnboxedConversationGlyphs(page, [".composer-action.send"]);
      }
    }

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const releaseResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/release") && response.status() === 200,
    );
    await page.getByRole("menuitem", { name: /^Chatbot\s/ }).click();
    await releaseResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Chatbot");
    if (phone) {
      // Direct detail reload must retain the focused phone layout. Returning
      // to the directory restores global navigation and its full-height flow.
      await page.reload();
      await expect(
        page.getByRole("log", { name: "Luồng tin nhắn" }),
      ).toBeVisible();
      await expect(globalBar).toBeHidden();
      await page
        .getByRole("button", { name: "Mở danh sách hội thoại" })
        .click();
      await expect(
        page.getByRole("heading", { name: "Hộp thư" }),
      ).toBeVisible();
      await expect(globalBar).toBeVisible();
      await expect(page).not.toHaveURL(/\bid=/);
      await expect(
        page.locator('.conversation[aria-current="page"]'),
      ).toBeFocused();
      await expect(
        page.getByRole("button", { name: "Mở danh sách hội thoại" }),
      ).toBeHidden();
    }
  });
});
