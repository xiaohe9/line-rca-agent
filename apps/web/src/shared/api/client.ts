import { z } from "zod";

import { createSseParser, type TraceEvent } from "../trace/events";

export const healthSchema = z.object({
  status: z.string(),
  env: z.string(),
  demoMode: z.boolean(),
  provider: z.string(),
  orchestrator: z.object({ planner: z.string(), executor: z.string() }),
  tools: z.array(z.string()),
  maxSteps: z.number(),
  traceSchemaVersion: z.string(),
});

export type Health = z.infer<typeof healthSchema>;

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/health", signal ? { signal } : {});
  if (!response.ok) {
    throw new Error(`GET /health 返回 ${response.status}`);
  }
  return healthSchema.parse(await response.json());
}

export interface StreamOptions {
  readonly signal?: AbortSignal;
  readonly onEvent: (event: TraceEvent) => void;
}

/**
 * Streams one analysis run.
 *
 * `fetch` + a readable stream is used instead of `EventSource` because the goal is a POST
 * body (EventSource is GET-only) and because we want to be able to cancel mid-run.
 */
export async function streamAnalysis(goal: string, options: StreamOptions): Promise<void> {
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ goal }),
    signal: options.signal ?? null,
  });

  if (!response.ok) {
    throw new Error(`POST /api/analyze 返回 ${response.status}`);
  }
  if (!response.body) {
    throw new Error("响应没有可读流，无法接收推理轨迹");
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = createSseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      for (const event of parser.push(value)) {
        options.onEvent(event);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
