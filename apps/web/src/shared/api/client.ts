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

export const batchSchema = z.object({
  batchId: z.string(),
  product: z.string(),
  units: z.number(),
  defects: z.number(),
  defectRate: z.number(),
  producedAt: z.string(),
  //: Carried so the UI can label the data's origin instead of assuming it.
  source: z.string(),
});

export type Batch = z.infer<typeof batchSchema>;

export const defectCountSchema = z.object({
  station: z.string(),
  defectType: z.string(),
  count: z.number(),
});

export type DefectCount = z.infer<typeof defectCountSchema>;

export const batchDefectsSchema = z.object({
  batchId: z.string(),
  found: z.boolean(),
  defectRate: z.number().optional(),
  units: z.number().optional(),
  defects: z.number().optional(),
  breakdown: z.array(defectCountSchema),
});

export type BatchDefects = z.infer<typeof batchDefectsSchema>;

export const workOrderSchema = z.object({
  id: z.string(),
  batchId: z.string().nullable(),
  station: z.string(),
  symptom: z.string(),
  rootCause: z.string().nullable(),
  action: z.string(),
  priority: z.string(),
  status: z.string(),
  createdAt: z.string(),
});

export type WorkOrder = z.infer<typeof workOrderSchema>;

/**
 * One place that fetches and validates. Responses are parsed rather than cast, for the same
 * reason the SSE stream is: the API is a separate process and its shape can drift.
 */
async function getJson<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, signal ? { signal } : {});
  if (!response.ok) {
    throw new Error(`GET ${path} 返回 ${response.status}`);
  }
  return schema.parse(await response.json());
}

export function fetchHealth(signal?: AbortSignal): Promise<Health> {
  return getJson("/health", healthSchema, signal);
}

export async function fetchBatches(limit = 6, signal?: AbortSignal): Promise<Batch[]> {
  const body = await getJson(
    `/api/batches?limit=${String(limit)}`,
    z.object({ batches: z.array(batchSchema) }),
    signal,
  );
  // Oldest first: a yield chart reads left to right in production order.
  return [...body.batches].reverse();
}

export function fetchBatchDefects(batchId: string, signal?: AbortSignal): Promise<BatchDefects> {
  return getJson(`/api/batches/${encodeURIComponent(batchId)}/defects`, batchDefectsSchema, signal);
}

export async function fetchWorkOrders(options?: {
  status?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<WorkOrder[]> {
  const params = new URLSearchParams();
  if (options?.status) {
    params.set("status", options.status);
  }
  params.set("limit", String(options?.limit ?? 10));
  const body = await getJson(
    `/api/workorders?${params.toString()}`,
    z.object({ workOrders: z.array(workOrderSchema) }),
    options?.signal,
  );
  return body.workOrders;
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
