/**
 * The TypeScript mirror of the kernel's trace contract (`packages/agent-core/src/line_rca_agent/trace.py`).
 *
 * Two rules make this file the frontend's single source of truth:
 *
 * 1. It parses, it does not cast. The event stream is untrusted input, so every frame goes
 *    through zod; a malformed frame is dropped and reported rather than crashing the timeline.
 * 2. It is versioned. `schema_version` is checked against the version this build understands,
 *    so a backend change is a visible mismatch instead of a mysterious empty screen.
 */
import { z } from "zod";

export const TRACE_SCHEMA_VERSION = "1";

export const EVENT_TYPES = [
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

export const eventTypeSchema = z.enum(EVENT_TYPES);

export const traceEventSchema = z.object({
  run_id: z.string().min(1),
  seq: z.number().int().positive(),
  type: eventTypeSchema,
  payload: z.record(z.string(), z.unknown()),
  ts: z.string(),
  schema_version: z.literal(TRACE_SCHEMA_VERSION),
});

export type TraceEvent = z.infer<typeof traceEventSchema>;
export type EventType = z.infer<typeof eventTypeSchema>;

/** Parses one event. Returns `null` instead of throwing so one bad frame cannot kill a run. */
export function parseTraceEvent(input: unknown): TraceEvent | null {
  const result = traceEventSchema.safeParse(input);
  return result.success ? result.data : null;
}

/** Parses one `event:`/`data:` block from a Server-Sent Events stream. */
export function parseSseBlock(block: string): TraceEvent | null {
  const dataLines = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) {
    return null;
  }
  try {
    return parseTraceEvent(JSON.parse(dataLines.join("\n")));
  } catch {
    return null;
  }
}

/**
 * Incremental SSE parser. Frames can be split across network chunks, so partial data is
 * buffered until the terminating blank line arrives.
 */
export function createSseParser(): { push: (chunk: string) => TraceEvent[] } {
  let buffer = "";

  return {
    push(chunk: string): TraceEvent[] {
      buffer += chunk.replace(/\r\n/g, "\n");
      const events: TraceEvent[] = [];
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseSseBlock(block);
        if (event) {
          events.push(event);
        }
        boundary = buffer.indexOf("\n\n");
      }
      return events;
    },
  };
}

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

export interface EventSummary {
  readonly title: string;
  readonly detail: string;
  readonly tone: Tone;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function asArray(value: unknown): readonly unknown[] {
  return Array.isArray(value) ? value : [];
}

/** Turns an event into the one line the timeline shows, plus its expandable detail. */
export function summarise(event: TraceEvent): EventSummary {
  const { payload } = event;
  switch (event.type) {
    case "run.started":
      return {
        title: "开始分析",
        detail: `目标：${asString(payload["goal"])}\n规划器：${asString(payload["planner"])} · 执行器：${asString(payload["executor"])}`,
        tone: "accent",
      };
    case "plan.created": {
      const steps = asArray(payload["steps"]);
      const lines = steps.map((step, index) => {
        const record = (step ?? {}) as Record<string, unknown>;
        return `${index + 1}. ${asString(record["description"])}${
          record["tool"] ? `  [${asString(record["tool"])}]` : ""
        }`;
      });
      return {
        title: `生成计划 · ${steps.length} 步`,
        detail: [asString(payload["rationale"]), ...lines].filter(Boolean).join("\n"),
        tone: "accent",
      };
    }
    case "step.started":
      return {
        title: `第 ${asNumber(payload["index"])} 步`,
        detail: `已规划 ${asNumber(payload["plannedSteps"])} 步`,
        tone: "neutral",
      };
    case "thought":
      return { title: "推理", detail: asString(payload["text"]), tone: "neutral" };
    case "tool.called":
      return {
        title: `调用工具 · ${asString(payload["tool"])}`,
        detail: JSON.stringify(payload["arguments"] ?? {}, null, 2),
        tone: "warning",
      };
    case "tool.result": {
      const ok = payload["ok"] === true;
      return {
        title: `${asString(payload["tool"])} 返回`,
        detail: asString(payload["observation"]),
        tone: ok ? "success" : "danger",
      };
    }
    case "guardrail.blocked":
      return {
        title: "护栏拦截",
        detail: asString(payload["reason"], "该输出被规则拦下，未进入结论"),
        tone: "danger",
      };
    case "memory.recalled":
      return {
        title: `召回历史案例 · ${asArray(payload["items"]).length} 条`,
        detail: asArray(payload["items"])
          .map((item) => asString((item as Record<string, unknown>)["content"]))
          .join("\n---\n"),
        tone: "accent",
      };
    case "answer":
      return { title: "结论", detail: asString(payload["text"]), tone: "success" };
    case "run.finished":
      return {
        title: "分析完成",
        detail: `共 ${asNumber(payload["steps"])} 步 · ${asString(payload["reason"])}`,
        tone: "success",
      };
    case "run.failed":
      return {
        title: "分析中断",
        detail: `阶段：${asString(payload["stage"])}\n${asString(payload["error"])}`,
        tone: "danger",
      };
    default: {
      // Exhaustiveness guard: adding an event type to the enum without handling it here
      // becomes a compile error rather than a blank row.
      const never: never = event.type;
      return { title: String(never), detail: "", tone: "neutral" };
    }
  }
}

export interface StepGroup {
  readonly stepId: string;
  readonly events: readonly TraceEvent[];
}

/** Groups events by the step they belong to, which is how the timeline lays out. */
export function groupByStep(events: readonly TraceEvent[]): readonly StepGroup[] {
  const groups: { stepId: string; events: TraceEvent[] }[] = [];
  let current: { stepId: string; events: TraceEvent[] } | null = null;

  for (const event of events) {
    if (event.type === "step.started") {
      const group = {
        stepId: asString(event.payload["stepId"], `s${groups.length + 1}`),
        events: [event],
      };
      groups.push(group);
      current = group;
      continue;
    }
    if (current === null) {
      current = { stepId: "run", events: [event] };
      groups.push(current);
      continue;
    }
    current.events.push(event);
  }
  return groups;
}
