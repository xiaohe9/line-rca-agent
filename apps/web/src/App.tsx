import { useEffect, useState, type FormEvent } from "react";

import { AgentTrace } from "./features/agent-trace/AgentTrace";
import { useRunStream } from "./features/agent-trace/useRunStream";
import { BatchYield } from "./features/yield-overview/BatchYield";
import { WorkOrderList } from "./features/workorders/WorkOrderList";
import { fetchHealth } from "./shared/api/client";
import type { Health } from "./shared/api/client";

const DEFAULT_GOAL = "为什么 B-2041 批次良率下降？";

function Chip({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <span className="rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-slate-400">
      {label} <span className="font-mono text-slate-200">{value}</span>
    </span>
  );
}

export function App() {
  const stream = useRunStream();
  const [goal, setGoal] = useState(DEFAULT_GOAL);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  // Bumped when a run finishes so the panels that read the database pick up its side effect:
  // a completed analysis may have opened a work order, and that should appear without a reload.
  const [dataVersion, setDataVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHealthError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (stream.status === "done") {
      setDataVersion((current) => current + 1);
    }
  }, [stream.status]);

  const streaming = stream.status === "streaming";

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = goal.trim();
    if (trimmed.length > 0 && !streaming) {
      void stream.run(trimmed);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <h1 className="text-sm font-semibold tracking-wide">
          产线良率<span className="text-sky-400">根因分析</span>
        </h1>
        <span className="text-[11px] text-slate-500">line-rca-agent</span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {healthError && <Chip label="API" value="不可达" />}
          {health && (
            <>
              <Chip label="模型" value={health.provider} />
              <Chip label="编排" value={`${health.orchestrator.planner} / ${health.orchestrator.executor}`} />
              <Chip label="工具" value={String(health.tools.length)} />
              <Chip label="trace" value={`v${health.traceSchemaVersion}`} />
            </>
          )}
        </div>
      </header>

      {health?.demoMode && (
        <p className="border-b border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-200">
          演示模式：使用脚本化的 fake 模型与<strong>模拟数据集</strong>，不是真实产线数据。
        </p>
      )}

      <form className="flex flex-wrap items-center gap-2 px-3 py-2" onSubmit={submit}>
        <input
          aria-label="产线问题"
          className="min-w-0 flex-1 rounded border border-white/15 bg-black/30 px-2.5 py-1.5 text-sm outline-none placeholder:text-slate-600"
          disabled={streaming}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="描述产线异常，例如：为什么 B-2041 批次良率下降？"
          value={goal}
        />
        <button
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium hover:bg-sky-500 disabled:opacity-40"
          disabled={streaming || goal.trim().length === 0}
          type="submit"
        >
          {streaming ? "分析中…" : "开始分析"}
        </button>
        <button
          className="rounded border border-white/15 px-3 py-1.5 text-sm hover:bg-white/10 disabled:opacity-40"
          disabled={!streaming}
          onClick={stream.cancel}
          type="button"
        >
          取消
        </button>
      </form>

      <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-3">
          <BatchYield version={dataVersion} />
          <AgentTrace events={stream.events} goal={stream.goal || goal} streaming={streaming} />
        </div>

        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <section
            aria-label="结论"
            className="rounded-lg border border-emerald-500/40 bg-emerald-500/[0.07] p-3"
          >
            <h2 className="mb-2 text-sm font-semibold text-emerald-300">结论</h2>
            {stream.answer ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-200">
                {stream.answer}
              </pre>
            ) : (
              <p className="text-sm text-slate-500">
                {streaming ? "等待分析完成…" : "尚未产生结论。"}
              </p>
            )}
          </section>

          {stream.error && (
            <section
              aria-label="错误"
              className="rounded-lg border border-rose-500/40 bg-rose-500/[0.07] p-3"
            >
              <h2 className="mb-1 text-sm font-semibold text-rose-300">出错了</h2>
              <p className="break-all text-xs text-rose-200">{stream.error}</p>
            </section>
          )}

          <WorkOrderList version={dataVersion} />

          <section className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <h2 className="mb-2 text-sm font-semibold text-slate-300">本次运行</h2>
            <dl className="space-y-1 text-xs text-slate-400">
              <div className="flex justify-between gap-2">
                <dt>状态</dt>
                <dd className="font-mono text-slate-200">{stream.status}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>事件数</dt>
                <dd className="font-mono text-slate-200">{stream.events.length}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>运行 ID</dt>
                <dd className="truncate font-mono text-slate-200">
                  {stream.events[0]?.run_id ?? "—"}
                </dd>
              </div>
            </dl>
          </section>
        </aside>
      </main>
    </div>
  );
}
