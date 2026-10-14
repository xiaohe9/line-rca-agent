import { motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { fetchBatchDefects, fetchBatches } from "../../shared/api/client";
import type { Batch, BatchDefects } from "../../shared/api/client";

/**
 * Yield overview.
 *
 * The bars are HTML buttons on a CSS baseline rather than an SVG chart: keyboard access,
 * focus rings and click targets come for free, and the data is one-dimensional. A charting
 * library earns its place when the shape is not a ranking — see docs/adr for that tradeoff.
 */
export interface BatchYieldProps {
  /** Bump to refetch, for example after a run has written a work order. */
  readonly version: number;
  readonly limit?: number;
}

/** Above this share of defects, a batch is treated as an excursion worth looking at. */
const ANOMALY_THRESHOLD = 0.1;

function barTone(rate: number): string {
  if (rate >= ANOMALY_THRESHOLD) {
    return "bg-rose-400/80 hover:bg-rose-300";
  }
  if (rate >= ANOMALY_THRESHOLD / 2) {
    return "bg-amber-400/70 hover:bg-amber-300";
  }
  return "bg-sky-500/60 hover:bg-sky-400";
}

export function BatchYield({ version, limit = 6 }: BatchYieldProps) {
  const [batches, setBatches] = useState<readonly Batch[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<BatchDefects | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchBatches(limit, controller.signal)
      .then((loaded) => {
        setBatches(loaded);
        setError(null);
        setSelected((current) =>
          current && loaded.some((batch) => batch.batchId === current)
            ? current
            : (loaded.at(-1)?.batchId ?? null),
        );
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [version, limit]);

  useEffect(() => {
    if (!selected) {
      setDetails(null);
      return;
    }
    const controller = new AbortController();
    fetchBatchDefects(selected, controller.signal)
      .then(setDetails)
      .catch(() => {
        if (!controller.signal.aborted) {
          setDetails(null);
        }
      });
    return () => controller.abort();
  }, [selected, version]);

  const onSelect = useCallback((batchId: string) => setSelected(batchId), []);

  const peak = Math.max(...batches.map((batch) => batch.defectRate), 0.01);
  const source = batches[0]?.source ?? "";

  return (
    <section
      aria-label="批次良率"
      className="rounded-lg border border-white/10 bg-ink-900/60 p-3"
      data-testid="batch-yield"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">良率总览</h2>
        <span className="text-[11px] text-slate-500">不良率 · 由低到高</span>
        {source && (
          <span className="ml-auto rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400">
            source: {source}
          </span>
        )}
      </header>

      {error && <p className="text-xs text-rose-300">读取批次失败：{error}</p>}
      {loading && batches.length === 0 && <p className="text-xs text-slate-500">加载中…</p>}

      {batches.length > 0 && (
        <div className="flex items-end gap-1.5" data-testid="yield-bars" style={{ height: 96 }}>
          {batches.map((batch) => {
            const ratio = batch.defectRate / peak;
            const active = batch.batchId === selected;
            return (
              <button
                aria-label={`批次 ${batch.batchId}，不良率 ${(batch.defectRate * 100).toFixed(2)}%`}
                aria-pressed={active}
                className={`group flex min-w-0 flex-1 flex-col items-center justify-end gap-1 rounded-t transition ${
                  active ? "ring-1 ring-white/40" : ""
                }`}
                data-testid="yield-bar"
                key={batch.batchId}
                onClick={() => onSelect(batch.batchId)}
                style={{ height: "100%" }}
                type="button"
              >
                <span className="font-mono text-[10px] text-slate-400">
                  {(batch.defectRate * 100).toFixed(1)}
                </span>
                <motion.span
                  animate={{ height: `${Math.max(ratio * 62, 3)}%` }}
                  className={`w-full rounded-t ${barTone(batch.defectRate)}`}
                  initial={{ height: "3%" }}
                  transition={{ duration: 0.25 }}
                />
                <span
                  className={`truncate text-[10px] ${
                    active ? "text-slate-200" : "text-slate-500 group-hover:text-slate-300"
                  }`}
                >
                  {batch.batchId}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {details?.found && (
        <div className="mt-3 border-t border-white/10 pt-2" data-testid="yield-breakdown">
          <p className="mb-1.5 text-[11px] text-slate-400">
            {details.batchId} · 不良 {details.defects} / 投产 {details.units} · 缺陷构成
          </p>
          <ul className="space-y-1">
            {details.breakdown.slice(0, 5).map((item) => {
              const top = details.breakdown[0]?.count ?? 1;
              return (
                <li className="flex items-center gap-2" key={`${item.station}-${item.defectType}`}>
                  <span className="w-28 shrink-0 truncate text-[11px] text-slate-400">
                    {item.station} · {item.defectType}
                  </span>
                  <span className="h-2 min-w-0 flex-1 overflow-hidden rounded bg-white/5">
                    <span
                      className="block h-full rounded bg-rose-400/70"
                      style={{ width: `${Math.max((item.count / top) * 100, 2)}%` }}
                    />
                  </span>
                  <span className="w-10 shrink-0 text-right font-mono text-[10px] text-slate-400">
                    {item.count}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
