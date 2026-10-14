import { describe, expect, it } from "vitest";

import {
  createSseParser,
  groupByStep,
  parseSseBlock,
  parseTraceEvent,
  summarise,
  TRACE_SCHEMA_VERSION,
  type TraceEvent,
} from "./events";

function frame(overrides: Partial<TraceEvent> = {}): Record<string, unknown> {
  return {
    run_id: "run-abc",
    seq: 1,
    type: "run.started",
    payload: { goal: "为什么 B-2041 良率下降？", planner: "plan-execute", executor: "react" },
    ts: "2026-10-14T09:00:00+00:00",
    schema_version: TRACE_SCHEMA_VERSION,
    ...overrides,
  };
}

describe("parseTraceEvent", () => {
  it("accepts a well-formed event", () => {
    const parsed = parseTraceEvent(frame());
    expect(parsed?.type).toBe("run.started");
  });

  it("rejects an unknown event type instead of guessing", () => {
    expect(parseTraceEvent(frame({ type: "totally.new" as TraceEvent["type"] }))).toBeNull();
  });

  it("rejects a schema-version mismatch rather than rendering nonsense", () => {
    expect(parseTraceEvent({ ...frame(), schema_version: "2" })).toBeNull();
  });

  it("rejects a missing payload", () => {
    const broken = frame();
    delete broken["payload"];
    expect(parseTraceEvent(broken)).toBeNull();
  });

  it("rejects non-objects", () => {
    expect(parseTraceEvent("nope")).toBeNull();
    expect(parseTraceEvent(null)).toBeNull();
  });
});

describe("parseSseBlock", () => {
  it("reads the data line and ignores the event name", () => {
    const block = `event: run.started\ndata: ${JSON.stringify(frame())}`;
    expect(parseSseBlock(block)?.seq).toBe(1);
  });

  it("returns null for a comment-only or empty block", () => {
    expect(parseSseBlock(": keep-alive")).toBeNull();
    expect(parseSseBlock("")).toBeNull();
  });

  it("returns null for malformed JSON rather than throwing", () => {
    expect(parseSseBlock("event: x\ndata: {not json")).toBeNull();
  });
});

describe("createSseParser", () => {
  it("reassembles frames split across chunk boundaries", () => {
    const parser = createSseParser();
    const payload = JSON.stringify(frame({ seq: 1 }));
    const whole = `event: run.started\ndata: ${payload}\n\n`;

    const first = parser.push(whole.slice(0, 20));
    const second = parser.push(whole.slice(20));

    expect(first).toHaveLength(0);
    expect(second).toHaveLength(1);
    expect(second[0]?.seq).toBe(1);
  });

  it("yields multiple frames from one chunk and keeps order", () => {
    const parser = createSseParser();
    const chunk = [1, 2, 3]
      .map((seq) => `event: step.started\ndata: ${JSON.stringify(frame({ seq, type: "step.started", payload: { stepId: `s${seq}`, index: seq, plannedSteps: 3 } }))}\n\n`)
      .join("");

    expect(parser.push(chunk).map((event) => event.seq)).toEqual([1, 2, 3]);
  });

  it("tolerates CRLF line endings", () => {
    const parser = createSseParser();
    const chunk = `event: run.started\r\ndata: ${JSON.stringify(frame())}\r\n\r\n`;
    expect(parser.push(chunk)).toHaveLength(1);
  });
});

describe("summarise", () => {
  it("summarises each event type without throwing", () => {
    const types = [
      "run.started",
      "plan.created",
      "step.started",
      "thought",
      "tool.called",
      "tool.result",
      "guardrail.blocked",
      "memory.recalled",
      "answer",
      "run.finished",
      "run.failed",
    ] as const;

    for (const type of types) {
      const summary = summarise({ ...(frame() as unknown as TraceEvent), type });
      expect(summary.title).not.toBe("");
      expect(typeof summary.detail).toBe("string");
    }
  });

  it("flags a failed tool result as danger", () => {
    const event = {
      ...frame(),
      type: "tool.result",
      payload: { tool: "query_defects", ok: false, observation: "unknown batch" },
    } as unknown as TraceEvent;
    expect(summarise(event).tone).toBe("danger");
  });
});

describe("groupByStep", () => {
  it("groups events under their step and puts pre-step events in a run group", () => {
    const events = [
      { ...frame(), type: "run.started" },
      { ...frame(), type: "plan.created" },
      { ...frame(), type: "step.started", payload: { stepId: "s1", index: 1, plannedSteps: 2 } },
      { ...frame(), type: "tool.called", payload: { tool: "query_defects" } },
      { ...frame(), type: "step.started", payload: { stepId: "s2", index: 2, plannedSteps: 2 } },
      { ...frame(), type: "answer", payload: { text: "根因是划伤" } },
    ] as TraceEvent[];

    const groups = groupByStep(events);

    expect(groups.map((group) => group.stepId)).toEqual(["run", "s1", "s2"]);
    expect(groups[1]?.events).toHaveLength(2);
    expect(groups[2]?.events).toHaveLength(2);
  });
});
