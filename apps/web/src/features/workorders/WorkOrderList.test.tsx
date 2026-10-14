import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkOrderList } from "./WorkOrderList";

const ORDERS = {
  workOrders: [
    {
      id: "WO-20261014-001",
      batchId: "B-2041",
      station: "镀膜",
      symptom: "B-2041 划伤占比 41%，镀膜工位振动超标 3.3 倍",
      rootCause: "镀膜工位传送夹具导向轮磨损导致镜片划伤",
      action: "停机检查传送夹具与导向轮",
      priority: "high",
      status: "open",
      createdAt: "2026-10-14T09:44:51Z",
    },
    {
      id: "WO-20260901-001",
      batchId: "B-2039",
      station: "镀膜",
      symptom: "镀膜后镜片表面出现细密划痕",
      rootCause: "传送夹具导向轮磨损",
      action: "更换导向轮",
      priority: "high",
      status: "closed",
      createdAt: "2026-09-01T02:00:00Z",
    },
  ],
};

function stubFetch(body: unknown, status = 200) {
  const stub = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  );
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

describe("WorkOrderList", () => {
  it("lists work orders with their status, priority and suspected cause", async () => {
    stubFetch(ORDERS);

    render(<WorkOrderList version={0} />);

    const rows = await screen.findAllByTestId("work-order");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("WO-20261014-001");
    expect(rows[0]).toHaveTextContent("open");
    expect(rows[0]).toHaveTextContent("high");
    expect(rows[0]).toHaveTextContent("疑似根因：镀膜工位传送夹具导向轮磨损");
    expect(rows[0]).toHaveTextContent("batch B-2041");
  });

  it("shows the count", async () => {
    stubFetch(ORDERS);

    render(<WorkOrderList version={0} />);
    await screen.findAllByTestId("work-order");

    expect(screen.getByTestId("work-order-count")).toHaveTextContent("2");
  });

  it("explains how to create one when there are none", async () => {
    stubFetch({ workOrders: [] });

    render(<WorkOrderList version={0} />);

    expect(await screen.findByText(/还没有工单/)).toBeInTheDocument();
  });

  it("reports a failed read rather than claiming there are none", async () => {
    stubFetch({ detail: "boom" }, 500);

    render(<WorkOrderList version={0} />);

    expect(await screen.findByText(/读取工单失败/)).toBeInTheDocument();
  });

  it("refetches when the version changes", async () => {
    const stub = stubFetch(ORDERS);

    const { rerender } = render(<WorkOrderList version={0} />);
    await screen.findAllByTestId("work-order");
    const before = stub.mock.calls.length;

    rerender(<WorkOrderList version={1} />);

    await waitFor(() => {
      expect(stub.mock.calls.length).toBeGreaterThan(before);
    });
  });
});
