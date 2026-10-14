import { useEffect, useState } from "react";

import { fetchWorkOrders } from "../../shared/api/client";
import type { WorkOrder } from "../../shared/api/client";

const STATUS_TONE: Record<string, string> = {
  open: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  in_progress: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  closed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
};

const PRIORITY_TONE: Record<string, string> = {
  high: "text-rose-300",
  medium: "text-amber-300",
  low: "text-slate-400",
};

export interface WorkOrderListProps {
  /** Bump to refetch, for example after a run has written one. */
  readonly version: number;
  readonly limit?: number;
}

/**
 * Work orders.
 *
 * This is the panel that shows the analysis leaving the chat window: a run that recommended
 * an action has a row here, and it exists whether or not anyone was watching the stream.
 */
export function WorkOrderList({ version, limit = 8 }: WorkOrderListProps) {
  const [orders, setOrders] = useState<readonly WorkOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchWorkOrders({ limit, signal: controller.signal })
      .then((loaded) => {
        setOrders(loaded);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [version, limit]);

  return (
    <section
      aria-label="维修工单"
      className="flex min-h-0 flex-col rounded-lg border border-white/10 bg-white/[0.03] p-3"
      data-testid="work-orders"
    >
      <header className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-200">维修工单</h2>
        <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
          <span data-testid="work-order-count">{orders.length}</span>
        </span>
      </header>

      {error && <p className="text-xs text-rose-300">读取工单失败：{error}</p>}
      {loading && orders.length === 0 && <p className="text-xs text-slate-500">加载中…</p>}
      {!loading && orders.length === 0 && !error && (
        <p className="text-xs text-slate-500">还没有工单。跑一次分析，它会开一张。</p>
      )}

      <ul className="min-h-0 space-y-2 overflow-y-auto">
        {orders.map((order) => (
          <li
            className="rounded border border-white/10 bg-black/20 p-2"
            data-testid="work-order"
            key={order.id}
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[11px] text-slate-300">{order.id}</span>
              <span
                className={`rounded border px-1.5 py-0.5 text-[10px] ${
                  STATUS_TONE[order.status] ?? "border-white/10 bg-white/5 text-slate-300"
                }`}
              >
                {order.status}
              </span>
              <span className={`text-[10px] ${PRIORITY_TONE[order.priority] ?? "text-slate-400"}`}>
                {order.priority}
              </span>
              <span className="ml-auto text-[10px] text-slate-500">{order.station}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-400">
              {order.symptom}
            </p>
            {order.rootCause && (
              <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-emerald-300/80">
                疑似根因：{order.rootCause}
              </p>
            )}
            {order.batchId && (
              <p className="mt-1 font-mono text-[10px] text-slate-500">batch {order.batchId}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
