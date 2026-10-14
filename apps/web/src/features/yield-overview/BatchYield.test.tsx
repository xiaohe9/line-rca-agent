import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BatchYield } from "./BatchYield";

const BATCHES = {
  batches: [
    { batchId: "B-2041", product: "A2", units: 1186, defects: 486, defectRate: 0.4098, producedAt: "2026-10-14T09:20:00Z", source: "simulated" },
    { batchId: "B-2040", product: "A2", units: 1200, defects: 48, defectRate: 0.04, producedAt: "2026-10-14T08:40:00Z", source: "simulated" },
    { batchId: "B-2039", product: "A2", units: 1195, defects: 29, defectRate: 0.0243, producedAt: "2026-10-14T08:00:00Z", source: "simulated" },
  ],
};

const BREAKDOWN = {
  "B-2041": {
    batchId: "B-2041",
    found: true,
    defectRate: 0.4098,
    units: 1186,
    defects: 486,
    breakdown: [
      { station: "镀膜", defectType: "划伤", count: 372 },
      { station: "镀膜", defectType: "气泡", count: 10 },
    ],
  },
  "B-2040": {
    batchId: "B-2040",
    found: true,
    defectRate: 0.04,
    units: 1200,
    defects: 48,
    breakdown: [{ station: "蚀刻", defectType: "异物", count: 20 }],
  },
};

function stubFetch(routes: readonly (readonly [string, unknown])[], fail = false) {
  const stub = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : String(input);
    for (const [fragment, body] of routes) {
      if (url.includes(fragment)) {
        if (fail) {
          return new Response("boom", { status: 500 });
        }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", stub);
  return stub;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("BatchYield", () => {
  it("renders one bar per batch, oldest first", async () => {
    stubFetch([
      ["/api/batches?", BATCHES],
      ["/api/batches/B-2041/defects", BREAKDOWN["B-2041"]],
    ]);

    render(<BatchYield version={0} />);

    const bars = await screen.findAllByTestId("yield-bar");
    expect(bars).toHaveLength(3);
    // The chart reads left to right in production order, not in API order.
    expect(bars.map((bar) => bar.textContent)).toEqual([
      expect.stringContaining("B-2039"),
      expect.stringContaining("B-2040"),
      expect.stringContaining("B-2041"),
    ]);
  });

  it("states the origin of the data instead of assuming it", async () => {
    stubFetch([["/api/batches?", BATCHES]]);

    render(<BatchYield version={0} />);

    expect(await screen.findByText(/source: simulated/)).toBeInTheDocument();
  });

  it("selects the most recent batch and shows its defect breakdown", async () => {
    stubFetch([
      ["/api/batches?", BATCHES],
      ["/api/batches/B-2041/defects", BREAKDOWN["B-2041"]],
    ]);

    render(<BatchYield version={0} />);

    const breakdown = await screen.findByTestId("yield-breakdown");
    expect(breakdown).toHaveTextContent("镀膜 · 划伤");
    expect(breakdown).toHaveTextContent("372");
  });

  it("loads a different breakdown when another bar is chosen", async () => {
    stubFetch([
      ["/api/batches?", BATCHES],
      ["/api/batches/B-2041/defects", BREAKDOWN["B-2041"]],
      ["/api/batches/B-2040/defects", BREAKDOWN["B-2040"]],
    ]);

    render(<BatchYield version={0} />);
    await screen.findByTestId("yield-breakdown");

    const bars = await screen.findAllByTestId("yield-bar");
    fireEvent.click(bars[1] as HTMLElement);

    await waitFor(() => {
      expect(screen.getByTestId("yield-breakdown")).toHaveTextContent("蚀刻 · 异物");
    });
    expect(bars[1]).toHaveAttribute("aria-pressed", "true");
  });

  it("describes each bar for assistive technology", async () => {
    stubFetch([["/api/batches?", BATCHES]]);

    render(<BatchYield version={0} />);
    await screen.findAllByTestId("yield-bar");

    expect(
      screen.getByRole("button", { name: /批次 B-2041，不良率 40\.98%/ }),
    ).toBeInTheDocument();
  });

  it("reports a failed read rather than rendering an empty chart", async () => {
    stubFetch([["/api/batches?", BATCHES]], true);

    render(<BatchYield version={0} />);

    expect(await screen.findByText(/读取批次失败/)).toBeInTheDocument();
  });

  it("refetches when the version changes", async () => {
    const stub = stubFetch([
      ["/api/batches?", BATCHES],
      ["/api/batches/B-2041/defects", BREAKDOWN["B-2041"]],
    ]);

    const { rerender } = render(<BatchYield version={0} />);
    await screen.findAllByTestId("yield-bar");
    const before = stub.mock.calls.length;

    rerender(<BatchYield version={1} />);

    await waitFor(() => {
      expect(stub.mock.calls.length).toBeGreaterThan(before);
    });
  });
});
