import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentTrace } from "./AgentTrace";
import { traceToMarkdown } from "../../shared/trace/exportTrace";
import { TRACE_SCHEMA_VERSION } from "../../shared/trace/events";
import type { EventType, TraceEvent } from "../../shared/trace/events";

let seq = 0;

function event(type: EventType, payload: Record<string, unknown> = {}): TraceEvent {
  seq += 1;
  return {
    run_id: "run-test",
    seq,
    type,
    payload,
    ts: "2026-10-14T09:00:00+00:00",
    schema_version: TRACE_SCHEMA_VERSION,
  };
}

const EVENTS: TraceEvent[] = [
  event("run.started", { goal: "为什么 B-2041 良率下降？", planner: "plan-execute", executor: "react" }),
  event("plan.created", { rationale: "先查缺陷分布", steps: [{ id: "s1", description: "查缺陷分布", tool: "query_defects" }] }),
  event("step.started", { stepId: "s1", index: 1, plannedSteps: 2 }),
  event("tool.called", { tool: "query_defects", arguments: { batch: "B-2041" } }),
  event("tool.result", { tool: "query_defects", ok: true, observation: "scratchRate=0.41" }),
  event("answer", { text: "根因：镀膜工位划伤。" }),
  event("run.finished", { steps: 1, reason: "answered" }),
];

function renderTrace(overrides: Partial<Parameters<typeof AgentTrace>[0]> = {}) {
  return render(
    <AgentTrace events={EVENTS} goal="为什么 B-2041 良率下降？" streaming={false} {...overrides} />,
  );
}

function visibleCount(): string {
  return screen.getByTestId("visible-count").textContent ?? "";
}

beforeEach(() => {
  seq = 0;
  URL.createObjectURL = vi.fn(() => "blob:mock");
  URL.revokeObjectURL = vi.fn();
  // jsdom has no navigation; without this the download anchor makes it log a warning.
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("AgentTrace", () => {
  it("shows an empty state when there are no events", () => {
    render(<AgentTrace events={[]} goal="" streaming={false} />);
    expect(screen.getByText(/还没有事件/)).toBeInTheDocument();
  });

  it("renders every event in live mode", () => {
    renderTrace();
    expect(screen.getAllByTestId("trace-entry")).toHaveLength(EVENTS.length);
    expect(visibleCount()).toBe(String(EVENTS.length));
  });

  it("groups events under their step", () => {
    renderTrace();
    expect(screen.getByText("运行")).toBeInTheDocument();
    expect(screen.getByText("s1")).toBeInTheDocument();
  });

  it("shows a one-line preview when collapsed and the full detail when expanded", () => {
    renderTrace();
    const button = screen.getByText("query_defects 返回").closest("button");
    expect(button).not.toBeNull();

    // Collapsed: scannable preview only, no <pre> block.
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector("pre")).toBeNull();
    expect(screen.getByText(/scratchRate=0.41/)).toBeInTheDocument();

    fireEvent.click(button as HTMLElement);

    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/scratchRate=0.41/).tagName).toBe("PRE");
  });

  it("steps the replay cursor backwards and forwards", () => {
    renderTrace();
    fireEvent.click(screen.getByRole("button", { name: "上一步" }));
    expect(visibleCount()).toBe(String(EVENTS.length - 1));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(visibleCount()).toBe(String(EVENTS.length));
  });

  it("marks the view as replaying and can return to live", () => {
    renderTrace();
    fireEvent.click(screen.getByRole("button", { name: "上一步" }));
    expect(screen.getByText("回放中")).toBeInTheDocument();
    expect(screen.getAllByTestId("trace-entry")).toHaveLength(EVENTS.length - 1);

    fireEvent.click(screen.getByRole("button", { name: "回到实时" }));
    expect(screen.queryByText("回放中")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("trace-entry")).toHaveLength(EVENTS.length);
  });

  it("plays the replay forward and stops at the end", () => {
    vi.useFakeTimers();
    renderTrace({ replayIntervalMs: 10 });

    fireEvent.click(screen.getByRole("button", { name: "播放回放" }));
    expect(visibleCount()).toBe("0");

    act(() => {
      vi.advanceTimersByTime(10 * (EVENTS.length + 2));
    });

    expect(visibleCount()).toBe(String(EVENTS.length));
    expect(screen.getByRole("button", { name: "播放回放" })).toBeInTheDocument();
  });

  it("is keyboard drivable", () => {
    renderTrace();
    const region = screen.getByTestId("agent-trace");

    fireEvent.keyDown(region, { key: "ArrowLeft" });
    expect(visibleCount()).toBe(String(EVENTS.length - 1));

    fireEvent.keyDown(region, { key: "ArrowRight" });
    expect(visibleCount()).toBe(String(EVENTS.length));

    fireEvent.keyDown(region, { key: " " });
    expect(visibleCount()).toBe("0");
    expect(screen.getByRole("button", { name: "暂停回放" })).toBeInTheDocument();

    fireEvent.keyDown(region, { key: "End" });
    expect(visibleCount()).toBe(String(EVENTS.length));
    expect(screen.queryByText("回放中")).not.toBeInTheDocument();
  });

  it("exports the run as Markdown", () => {
    renderTrace();
    fireEvent.click(screen.getByRole("button", { name: "导出报告" }));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});

describe("traceToMarkdown", () => {
  it("includes the goal, the answer and every event title", () => {
    const markdown = traceToMarkdown(EVENTS, "为什么 B-2041 良率下降？");

    expect(markdown).toContain("# 产线良率根因分析报告");
    expect(markdown).toContain("为什么 B-2041 良率下降？");
    expect(markdown).toContain("根因：镀膜工位划伤。");
    expect(markdown).toContain("`tool.called`");
    expect(markdown).toContain("调用工具 · query_defects");
  });

  it("reports an interrupted run instead of pretending it finished", () => {
    const failed = [event("run.started", { goal: "g" }), event("run.failed", { stage: "budget", error: "exhausted" })];
    const markdown = traceToMarkdown(failed, "g");

    expect(markdown).toContain("## 中断原因");
    expect(markdown).toContain("exhausted");
  });

  it("handles an empty run", () => {
    expect(traceToMarkdown([], "g")).toContain("没有产生事件");
  });
});
