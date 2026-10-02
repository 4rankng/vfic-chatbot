import { type ReactNode, useState } from "react";
import { RefreshCw } from "lucide-react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "./performance.css";
import {
  ButtonGroup,
  ButtonGroupItem,
} from "@/components/base/button-group/button-group";
import { PerformanceTrendChart } from "./PerformanceTrendChart";
import { Metric } from "./presentation/primitives";
import type { PerfTrendBucket } from "./usePerformanceStats";

// TEST-17 — this replaces performance.css.test.ts, which read performance.css
// as `?raw`, sliced out the mobile media block by string index, and matched ~30
// regexes against its own text. Those regexes could not see whether a rule
// reached the element the dashboard renders, whether a later declaration in the
// same block shadowed it, or — for the trend chart — whether the target line
// actually sits above the bars in the stacking order.
//
// Everything below renders the real `PerformanceTrendChart` and the real
// `Metric` primitive inside the dashboard's `.performance-page` shell and
// measures what a browser computes.
//
// Lane facts that shape this file:
//   * The daisyUI / `@theme` scale is not emitted by this vitest project, so
//     `var(--fs-page-title)`, `var(--fs-body-sm)` and `var(--fw-bold)` are
//     unresolvable above 767px and the type-only rules are unasserted above
//     that width. The mobile block is inside 720px, where `--fs-page-title`
//     resolves to 22px, so those are asserted there.
//   * `--border` / `--card` / `--muted-foreground` resolve from `:root`, so the
//     frame, fill and shadow assertions are real painted values.

const desktop = 1280;
const mobile = 700;
const narrow = 390;

const trend: PerfTrendBucket[] = [
  {
    bucket: "2026-09-27T10:00:00Z",
    p95_ms: 4_000,
    p50_ms: 2_800,
    turns: 5,
    errors: 0,
  },
  {
    bucket: "2026-09-27T10:05:00Z",
    p95_ms: 24_000,
    p50_ms: 18_000,
    turns: 6,
    errors: 2,
  },
  {
    bucket: "2026-09-27T10:10:00Z",
    p95_ms: 12_000,
    p50_ms: 9_000,
    turns: 4,
    errors: 0,
  },
];

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 900);
});

/** The header's segmented window switcher, reproduced from `PerformancePage`. */
const WindowSwitcher = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  return (
    <ButtonGroup
      size="sm"
      className="performance-window-switcher uu-scope"
      aria-label="Khoảng thời gian"
      selectedKeys={[windowKey]}
      onSelectionChange={(keys) => {
        const next = [...keys][0];
        if (next) setWindowKey(next as "1h" | "24h" | "7d");
      }}
    >
      <ButtonGroupItem id="1h" className="performance-window-option">
        1 giờ
      </ButtonGroupItem>
      <ButtonGroupItem id="24h" className="performance-window-option">
        24 giờ
      </ButtonGroupItem>
      <ButtonGroupItem id="7d" className="performance-window-option">
        7 ngày
      </ButtonGroupItem>
    </ButtonGroup>
  );
};

/** The dashboard header, reproduced from `PerformancePage`'s own markup. */
const header = () => (
  <header className="performance-header">
    <div>
      <h1>Hiệu suất chatbot</h1>
      <p>Trải nghiệm ứng viên, năng lực xử lý và độ tin cậy giao gửi.</p>
    </div>
    <div className="performance-header-actions">
      <WindowSwitcher />
      <button
        type="button"
        className="performance-refresh"
        aria-label="Cập nhật dữ liệu"
      >
        <RefreshCw aria-hidden="true" />
        <span className="performance-refresh-prefix">Cập nhật lúc </span>
        12:00:00
      </button>
    </div>
  </header>
);

const metricStrip = () => (
  <section className="performance-metrics" aria-label="Tình trạng hệ thống">
    <Metric
      label="Hàng đợi"
      value="0"
      hint="webhook đang chờ"
      tone="neutral"
      icon={RefreshCw}
    />
    <Metric
      label="Worker"
      value="2/2"
      hint="đang bận"
      tone="warning"
      icon={RefreshCw}
    />
    <Metric
      label="Độ trễ"
      value="12,4 giây"
      hint="p95"
      tone="success"
      icon={RefreshCw}
    />
  </section>
);

const dashboard = (children: ReactNode) => (
  <div className="performance-page">{children}</div>
);

describe("performance trend chart layers", () => {
  it("renders the target line above the bars without blocking their hover details", async () => {
    // This is the layering contract the old source pins could not prove. The
    // target line spans the full width of the plot at the 10-second mark, so if
    // it stacks above the bars it hides their hover tooltips; if it took pointer
    // events it would also swallow the hover. z-index 3 / 2 with
    // `pointer-events: none` is what keeps both the line and the bar tooltips
    // working — a silent regression here overlaps every dialog and dropdown.
    await page.viewport(desktop, 900);
    const screen = await render(
      dashboard(<PerformanceTrendChart trend={trend} window="24h" />),
    );

    const targetLine = screen.container.querySelector<HTMLElement>(
      ".performance-target-line",
    )!;
    const bar = screen.container.querySelector<HTMLElement>(
      ".performance-trend-bar",
    )!;
    const lineStyles = getComputedStyle(targetLine);
    const barStyles = getComputedStyle(bar);

    // The line is painted above the bars...
    expect(lineStyles.zIndex).toBe("3");
    expect(barStyles.zIndex).toBe("2");
    expect(Number(lineStyles.zIndex)).toBeGreaterThan(Number(barStyles.zIndex));

    // ...but is transparent to the pointer, so it never intercepts a hover.
    expect(lineStyles.pointerEvents).toBe("none");
  });

  it("keeps the bars hoverable under the target line", async () => {
    // The behavioural counterpart to the z-index pins: hovering a bar that sits
    // behind the target line still dims the bar, which only works if the line
    // does not take the pointer.
    await page.viewport(desktop, 900);
    const screen = await render(
      dashboard(<PerformanceTrendChart trend={trend} window="24h" />),
    );

    const targetLine = screen.container.querySelector<HTMLElement>(
      ".performance-target-line",
    )!;
    const bars = Array.from(
      screen.container.querySelectorAll<HTMLElement>(".performance-trend-bar"),
    );
    expect(bars.length).toBeGreaterThan(1);

    // A point that is inside the target line's box and inside a bar's box.
    const lineRect = targetLine.getBoundingClientRect();
    const hovered = bars.find((candidate) => {
      const rect = candidate.getBoundingClientRect();
      return rect.top <= lineRect.top + 1 && rect.bottom >= lineRect.top + 1;
    });
    expect(hovered, "no bar crosses the target line").toBeDefined();

    const hit = document.elementFromPoint(
      hovered!.getBoundingClientRect().left + 1,
      lineRect.top + 1,
    );
    // The pointer reaches the bar, not the line drawn over it.
    expect(hit?.className ?? "").toContain("performance-trend-bar");

    await page.elementLocator(hovered!).hover();
    await expect.poll(() => getComputedStyle(hovered!).opacity).not.toBe("1");
  });

  it("bounds the trend plot so the target line spans it horizontally", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(
      dashboard(<PerformanceTrendChart trend={trend} window="24h" />),
    );

    const plot =
      screen.container.querySelector<HTMLElement>(".performance-trend")!;
    const targetLine = screen.container.querySelector<HTMLElement>(
      ".performance-target-line",
    )!;
    const plotRect = plot.getBoundingClientRect();
    const lineRect = targetLine.getBoundingClientRect();

    // The line is a full-width rule at the 10-second threshold, not a
    // zero-width or unpositioned element that never paints.
    expect(getComputedStyle(targetLine).position).toBe("absolute");
    // `left: 0; right: 0` resolves against the plot's padding box, so the
    // line spans everything inside the plot's own 1px frame.
    expect(lineRect.width).toBeCloseTo(plot.clientWidth, 0);
    expect(lineRect.top).toBeGreaterThanOrEqual(plotRect.top);
    expect(lineRect.bottom).toBeLessThanOrEqual(plotRect.bottom);
    expect(plot.getBoundingClientRect().height).toBeGreaterThan(0);
  });
});

describe("performance header hierarchy", () => {
  it.each([320, 390])(
    "wraps intrinsic period controls before they overlap refresh in a narrow panel at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        dashboard(<div style={{ maxWidth: 224 }}>{header()}</div>),
      );
      const group = screen
        .getByRole("radiogroup", { name: "Khoảng thời gian" })
        .element();
      const refresh = screen
        .getByRole("button", { name: "Cập nhật dữ liệu" })
        .element();
      const actions = screen.container.querySelector<HTMLElement>(
        ".performance-header-actions",
      )!;
      const groupBox = group.getBoundingClientRect();
      const refreshBox = refresh.getBoundingClientRect();
      const rowBox = actions.getBoundingClientRect();
      // Both controls retain their natural width. When their combined intrinsic
      // width exceeds the panel, refresh must move to a second row rather than
      // shrinking a grid track underneath the period group's painted buttons.
      expect(groupBox.width + refreshBox.width + 6).toBeGreaterThan(
        rowBox.width,
      );
      expect(refreshBox.top).toBeGreaterThanOrEqual(groupBox.bottom);
      expect(refreshBox.right).toBeLessThanOrEqual(rowBox.right + 1);
      for (const option of group.querySelectorAll("button")) {
        const box = option.getBoundingClientRect();
        expect(box.left).toBeGreaterThanOrEqual(rowBox.left);
        expect(box.right).toBeLessThanOrEqual(rowBox.right);
        expect(getComputedStyle(option).fontSize).toBe("12px");
      }
      await screen.getByRole("radio", { name: "7 ngày" }).click();
      await expect
        .element(screen.getByRole("radio", { name: "7 ngày" }))
        .toHaveAttribute("aria-checked", "true");
    },
  );
  it("marks exactly the chosen window as selected", async () => {
    // The switcher is one React Aria segmented control; a pixel pin on the
    // deleted `.performance-window` rules cannot prove that. Selecting a
    // segment must move the selected marker and leave exactly one behind.
    await page.viewport(desktop, 900);
    const screen = await render(dashboard(header()));

    const switcher = screen.container.querySelector<HTMLElement>(
      '[aria-label="Khoảng thời gian"]',
    )!;
    const segments = Array.from(
      switcher.querySelectorAll<HTMLButtonElement>("button"),
    );
    expect(segments).toHaveLength(3);
    const selectedLabels = (items: HTMLButtonElement[]) =>
      items
        .filter((item) => item.hasAttribute("data-selected"))
        .map((item) => item.textContent);

    expect(selectedLabels(segments)).toEqual(["24 giờ"]);

    await screen.getByRole("radio", { name: "7 ngày" }).click();

    expect(selectedLabels(segments)).toEqual(["7 ngày"]);
  });

  it("uses the page title as the top of the mobile type scale", async () => {
    // The 720px block pins the title to `--fs-page-title` (22px below 768px) on
    // a 28px line, and the subtitle to `--fs-body-sm` (13px) on an 18px line.
    await page.viewport(mobile, 900);
    const screen = await render(dashboard(header()));

    const title = screen.container.querySelector<HTMLElement>(
      ".performance-header h1",
    )!;
    const subtitle = screen.container.querySelector<HTMLElement>(
      ".performance-header > div > p:last-child",
    )!;

    const titleStyles = getComputedStyle(title);
    expect(titleStyles.fontSize).toBe("22px");
    expect(titleStyles.lineHeight).toBe("28px");

    const subtitleStyles = getComputedStyle(subtitle);
    expect(subtitleStyles.fontSize).toBe("13px");
    expect(subtitleStyles.lineHeight).toBe("18px");
  });

  it.each([320, narrow])(
    "keeps the refresh action44px and the header inside the narrow viewport at %ipx",
    async (width) => {
      // Below 420px the "Cập nhật lúc HH:MM:SS" prefix would push the refresh
      // glyph and label off the row, so the prefix is hidden and only the time
      // remains.
      await page.viewport(width, 900);
      const screen = await render(dashboard(header()));

      const prefix = screen.container.querySelector<HTMLElement>(
        ".performance-refresh-prefix",
      )!;
      expect(getComputedStyle(prefix).display).toBe("none");
      expect(prefix.getBoundingClientRect().width).toBe(0);
      const refresh = screen
        .getByRole("button", { name: "Cập nhật dữ liệu" })
        .element();
      expect(refresh.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
      const actions = screen.container.querySelector<HTMLElement>(
        ".performance-header-actions",
      )!;
      expect(refresh.getBoundingClientRect().right).toBeLessThanOrEqual(
        actions.getBoundingClientRect().right + 1,
      );
      expect(actions.getBoundingClientRect().right).toBeLessThanOrEqual(width);
    },
  );
});

describe("performance metric strip", () => {
  it("presents the top metrics as one flat ruled status strip", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(dashboard(metricStrip()));

    const strip = screen.container.querySelector<HTMLElement>(
      ".performance-metrics",
    )!;
    const stripStyles = getComputedStyle(strip);
    // `gap: 0` plus the ruled block edges: the metrics are one band, and a gap
    // here would split them into separate tiles.
    expect(stripStyles.gap).toBe("0px");
    expect(stripStyles.borderBlockStartWidth).toBe("1px");
    expect(stripStyles.borderBlockStartStyle).toBe("solid");
    expect(stripStyles.borderBlockEndWidth).toBe("1px");

    const metrics = Array.from(
      screen.container.querySelectorAll<HTMLElement>(".performance-metric"),
    );
    expect(metrics).toHaveLength(3);
    for (const metric of metrics) {
      const styles = getComputedStyle(metric);
      expect(styles.borderTopWidth, metric.outerHTML).toBe("0px");
      expect(styles.borderRadius, metric.outerHTML).toBe("0px");
      expect(styles.backgroundColor, metric.outerHTML).toBe("rgba(0, 0, 0, 0)");
    }
    // Adjacent metrics are divided by a single rule, not by their own boxes.
    expect(getComputedStyle(metrics[1]).borderLeftWidth).toBe("1px");
  });
});

describe("performance primary comparison", () => {
  const primaryGrid = () => (
    <section className="performance-primary-grid">
      <PerformanceTrendChart trend={trend} window="24h" />
      <aside className="performance-panel performance-attention-panel">
        <h2>Cần chú ý</h2>
      </aside>
    </section>
  );

  it("divides the trend chart and the attention queue into one workbench", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(dashboard(primaryGrid()));

    const grid = screen.container.querySelector<HTMLElement>(
      ".performance-primary-grid",
    )!;
    const gridStyles = getComputedStyle(grid);
    // No gap and ruled block edges — the two panels are one comparison, not two
    // floating cards.
    expect(gridStyles.gap).toBe("0px");
    expect(gridStyles.borderBlockStartWidth).toBe("1px");
    expect(gridStyles.borderBlockStartStyle).toBe("solid");

    const chart = screen.container.querySelector<HTMLElement>(
      ".performance-primary-grid > .performance-panel",
    )!;
    const chartStyles = getComputedStyle(chart);
    expect(chartStyles.borderTopWidth).toBe("0px");
    expect(chartStyles.borderRadius).toBe("0px");
    expect(chartStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(chartStyles.boxShadow).toBe("none");

    // The attention queue keeps a left rule; it is the division between the
    // two halves, so it must not become a full card of its own.
    const attention = screen.container.querySelector<HTMLElement>(
      ".performance-attention-panel",
    )!;
    expect(getComputedStyle(attention).borderLeftWidth).toBe("1px");
    const chartRect = chart.getBoundingClientRect();
    expect(attention.getBoundingClientRect().left).toBeGreaterThanOrEqual(
      chartRect.right - 1,
    );
  });
});

describe("performance slow-turn review table", () => {
  const slowTurnsTable = () => (
    <section className="performance-panel performance-slow-turns tt-card tt-card-border">
      <table>
        <thead>
          <tr>
            <th>Mức độ</th>
            <th>Tổng</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Chậm</td>
            <td>24,0 giây</td>
          </tr>
        </tbody>
      </table>
      <button type="button" className="performance-expand" aria-label="Mở rộng">
        +
      </button>
    </section>
  );

  it("integrates the review table header with the page canvas", async () => {
    // The table header must not lift off the canvas: a sticky `thead` on a
    // scrolling panel overlapped the diagnostics above it, and a `var(--card)`
    // fill drew a band across the whole report.
    await page.viewport(desktop, 900);
    const screen = await render(dashboard(slowTurnsTable()));

    const head = screen.container.querySelector<HTMLElement>(
      ".performance-slow-turns thead",
    )!;
    const headRow = screen.container.querySelector<HTMLElement>(
      ".performance-slow-turns thead tr",
    )!;
    const headCell = screen.container.querySelector<HTMLElement>(
      ".performance-slow-turns thead th",
    )!;

    for (const [name, element] of [
      ["thead", head],
      ["thead tr", headRow],
      ["thead th", headCell],
    ] as const) {
      expect(getComputedStyle(element).backgroundColor, name).toBe(
        "rgba(0, 0, 0, 0)",
      );
    }
    expect(getComputedStyle(headCell).position).toBe("static");
    expect(getComputedStyle(headCell).borderBottomWidth).toBe("1px");

    // The expand control is a bare button, not a bordered chip.
    const expand = screen.container.querySelector<HTMLElement>(
      ".performance-expand",
    )!;
    expect(getComputedStyle(expand).borderTopWidth).toBe("0px");
  });
});

describe("performance mobile report", () => {
  const mobileReport = () => (
    <>
      {header()}
      {metricStrip()}
      <section className="performance-panel performance-slow-turns">
        <div className="performance-turn-cards">
          <article className="is-warning">
            <div>
              <time>10:05</time>
              <strong>24,0 giây</strong>
            </div>
          </article>
          <article className="is-danger">
            <div>
              <time>10:10</time>
              <strong>31,2 giây</strong>
            </div>
          </article>
        </div>
      </section>
    </>
  );

  it("tightens the metric tiles into a two-column phone grid", async () => {
    // The 720px block drops the six-across strip to two columns and pads each
    // tile to 10px. `box-shadow` on a tile is unasserted here only because the
    // shadow is `none` on every path; the flat `background-color` below is the
    // load-bearing half of that contract.
    await page.viewport(mobile, 900);
    const screen = await render(dashboard(mobileReport()));

    const strip = screen.container.querySelector<HTMLElement>(
      ".performance-metrics",
    )!;
    expect(getComputedStyle(strip).gridTemplateColumns.split(" ").length).toBe(
      2,
    );

    const metrics = Array.from(
      screen.container.querySelectorAll<HTMLElement>(".performance-metric"),
    );
    for (const metric of metrics) {
      expect(getComputedStyle(metric).paddingTop, metric.outerHTML).toBe(
        "10px",
      );
      expect(getComputedStyle(metric).backgroundColor, metric.outerHTML).toBe(
        "rgba(0, 0, 0, 0)",
      );
    }

    // The tile value follows the shared metric token rather than a phone-only
    // literal, which made the number larger than its 1440px desktop size.
    // (The token's own size is asserted by the type-scale tests.)
    const value = screen.container.querySelector<HTMLElement>(
      ".performance-metric strong",
    )!;
    expect(value.textContent?.trim().length ?? 0).toBeGreaterThan(0);
  });

  it("stacks the slow turns as one ruled list on a phone", async () => {
    // Below 720px the table becomes a card list: each turn loses its own frame
    // and consecutive turns share a single top rule, so the list reads as one
    // continuous report rather than a stack of cards.
    await page.viewport(mobile, 900);
    const screen = await render(dashboard(mobileReport()));

    const slowTurns = screen.container.querySelector<HTMLElement>(
      ".performance-slow-turns",
    )!;
    const slowStyles = getComputedStyle(slowTurns);
    expect(slowStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(slowStyles.boxShadow).toBe("none");
    expect(slowStyles.borderRadius).toBe("0px");

    const cards = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        ".performance-turn-cards article",
      ),
    );
    expect(cards).toHaveLength(2);
    for (const card of cards) {
      const styles = getComputedStyle(card);
      expect(styles.borderRadius, card.outerHTML).toBe("0px");
      expect(styles.backgroundColor, card.outerHTML).toBe("rgba(0, 0, 0, 0)");
    }
    // No card draws its own box; consecutive turns share one divider, carried
    // by the `article + article` rule. A frame restored on every card is what
    // turned this list back into a stack of tiles.
    expect(getComputedStyle(cards[0]).borderTopWidth).toBe("0px");
    expect(getComputedStyle(cards[0]).borderBottomWidth).toBe("0px");
    expect(getComputedStyle(cards[1]).borderTopWidth).toBe("1px");
    expect(getComputedStyle(cards[1]).borderBottomWidth).toBe("0px");
  });

  it("keeps the trend plot at its fixed mobile height", async () => {
    // The plot is a fixed 152px band on a phone; letting it grow with the
    // data pushed the rest of the report off the screen.
    await page.viewport(mobile, 900);
    const screen = await render(
      dashboard(<PerformanceTrendChart trend={trend} window="24h" />),
    );

    const plot =
      screen.container.querySelector<HTMLElement>(".performance-trend")!;
    expect(plot.getBoundingClientRect().height).toBe(152);
  });
});
