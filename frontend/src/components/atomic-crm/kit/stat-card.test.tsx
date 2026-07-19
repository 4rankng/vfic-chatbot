import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { StatCard } from "./stat-card";

describe("StatCard", () => {
  it("renders the value and label", async () => {
    const screen = await render(
      <StatCard value="142" label="Hồ sơ tuần này" />,
    );
    expect(screen.getByText("142")).toBeTruthy();
    expect(screen.getByText("Hồ sơ tuần này")).toBeTruthy();
  });

  it("renders an emerald up-delta when deltaPct is positive", async () => {
    const screen = await render(
      <StatCard value="142" label="Hồ sơ" deltaPct={17} />,
    );
    expect(screen.getByText("+17.0%")).toBeTruthy();
  });

  it("renders a rose down-delta when deltaPct is negative", async () => {
    const screen = await render(
      <StatCard value="32,4k" label="Lượt xem" deltaPct={-1.2} />,
    );
    expect(screen.getByText("-1.2%")).toBeTruthy();
  });

  it("omits the delta block when deltaPct is undefined", async () => {
    const screen = await render(<StatCard value="142" label="Hồ sơ" />);
    expect(screen.container.querySelector(".tt-stat-card-delta")).toBeNull();
  });

  it("renders a sparkline when a series with ≥ 2 points is passed", async () => {
    const screen = await render(
      <StatCard value="142" label="Hồ sơ" series={[3, 5, 4, 8, 7, 12]} />,
    );
    const svg = screen.container.querySelector(".tt-stat-card-spark svg");
    expect(svg).not.toBeNull();
    const paths = svg?.querySelectorAll("path");
    expect(paths?.length).toBe(2);
  });

  it("renders no sparkline when the series has fewer than 2 points", async () => {
    const screen = await render(
      <StatCard value="142" label="Hồ sơ" series={[3]} />,
    );
    expect(screen.container.querySelector(".tt-stat-card-spark")).toBeNull();
  });

  it("renders a hint under the label when provided", async () => {
    const screen = await render(
      <StatCard value="142" label="Hồ sơ" hint="from 12 products" />,
    );
    expect(screen.getByText("from 12 products")).toBeTruthy();
  });
});
