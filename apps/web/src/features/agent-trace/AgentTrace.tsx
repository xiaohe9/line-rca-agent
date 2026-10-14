import { motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { downloadMarkdown, traceToMarkdown } from "../../shared/trace/exportTrace";
import { groupByStep, summarise } from "../../shared/trace/events";
import type { Tone, TraceEvent } from "../../shared/trace/events";

const TONE_CARD: Record<Tone, string> = {
  neutral: "border-white/10 bg-white/[0.03]",
  accent: "border-sky-500/40 bg-sky-500/[0.07]",
  success: "border-emerald-500/40 bg-emerald-500/[0.07]",
  warning: "border-amber-500/40 bg-amber-500/[0.07]",
  danger: "border-rose-500/40 bg-rose-500/[0.07]",
};

const TONE_DOT: Record<Tone, string> = {
  neutral: "bg-slate-400",
  accent: "bg-sky-400",
  success: "bg-emerald-400",
  warning: "bg-amber-400",
  danger: "bg-rose-400",
};

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-slate-300",
  accent: "text-sky-300",
  success: "text-emerald-300",
  warning: "text-amber-300",
  danger: "text-rose-300",
};

export interface AgentTraceProps {
  readonly events: readonly TraceEvent[];
  readonly goal: string;
  readonly streaming: boolean;
  /** Replay tick. Exposed so tests do not have to wait on real time. */
  readonly replayIntervalMs?: number;
}

/**
 * The reasoning timeline.
 *
 * It renders the versioned event stream directly, which is what makes the decision auditable
 * rather than a black box. Replay and Markdown export are pure client capabilities: they need
 * no extra backend call, so they keep working on a finished, saved run.
 */
export function AgentTrace({
  events,
  goal,
  streaming,
  replayIntervalMs = 320,
}: AgentTraceProps) {
  const entries = useMemo(
    () => events.map((event) => ({ event, summary: summarise(event) })),
    [events],
  );
  const groups = useMemo(() => groupByStep(events), [events]);
  const indexOf = useMemo(() => {
    const map = new Map<TraceEvent, number>();
    events.forEach((event, index) => map.set(event, index));
    return map;
  }, [events]);

  const total = entries.length;
  // `null` means "follow the live stream"; a number means the user took over and is replaying.
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set());

  const visibleCount = cursor === null ? total : Math.min(cursor, total);
  const replaying = cursor !== null;

  useEffect(() => {
    if (!playing) {
      return;
    }
    const timer = window.setInterval(
      () => setCursor((previous) => Math.min((previous ?? 0) + 1, total)),
      replayIntervalMs,
    );
    return () => window.clearInterval(timer);
  }, [playing, replayIntervalMs, total]);

  useEffect(() => {
    if (playing && cursor !== null && cursor >= total) {
      setPlaying(false);
    }
  }, [playing, cursor, total]);

  const play = useCallback(() => {
    setCursor(0);
    setPlaying(true);
  }, []);
  const pause = useCallback(() => setPlaying(false), []);
  const step = useCallback(
    (delta: number) => {
      setPlaying(false);
      setCursor((previous) => Math.max(0, Math.min((previous ?? total) + delta, total)));
    },
    [total],
  );
  const goLive = useCallback(() => {
    setPlaying(false);
    setCursor(null);
  }, []);

  const toggle = useCallback((index: number) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === " ") {
        event.preventDefault();
        if (playing) {
          pause();
        } else {
          play();
        }
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        step(1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        step(-1);
      } else if (event.key === "End") {
        event.preventDefault();
        goLive();
      }
    },
    [goLive, pause, play, playing, step],
  );

  const onExport = useCallback(() => {
    const runId = events[0]?.run_id ?? "run";
    downloadMarkdown(`${runId}.md`, traceToMarkdown(events, goal));
  }, [events, goal]);

  return (
    <section
      aria-label="推理轨迹"
      className="flex min-h-0 flex-1 flex-col rounded-lg border border-white/10 bg-ink-900/60"
      data-testid="agent-trace"
      onKeyDown={onKeyDown}
      tabIndex={0}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">推理轨迹</h2>
        <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-slate-400">
          <span data-testid="visible-count">{visibleCount}</span>/{total}
        </span>
        {streaming && cursor === null && (
          <span className="flex items-center gap-1 text-[11px] text-sky-300">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            实时
          </span>
        )}
        {replaying && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-300">
            回放中
          </span>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-1">
          <button
            className="rounded border border-white/10 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
            disabled={total === 0}
            onClick={playing ? pause : play}
            type="button"
          >
            {playing ? "暂停回放" : "播放回放"}
          </button>
          <button
            className="rounded border border-white/10 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
            disabled={total === 0}
            onClick={() => step(-1)}
            type="button"
          >
            上一步
          </button>
          <button
            className="rounded border border-white/10 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
            disabled={total === 0}
            onClick={() => step(1)}
            type="button"
          >
            下一步
          </button>
          <button
            className="rounded border border-white/10 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
            disabled={!replaying}
            onClick={goLive}
            type="button"
          >
            回到实时
          </button>
          <button
            className="rounded border border-white/10 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
            disabled={total === 0}
            onClick={onExport}
            type="button"
          >
            导出报告
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3" data-testid="trace-list">
        {total === 0 ? (
          <p className="px-1 py-8 text-center text-sm text-slate-500">
            {streaming ? "正在等待第一个事件…" : "还没有事件。提出一个产线问题开始分析。"}
          </p>
        ) : (
          <ol className="space-y-4">
            {groups.map((group) => {
              const shown = group.events.filter(
                (event) => (indexOf.get(event) ?? 0) < visibleCount,
              );
              if (shown.length === 0) {
                return null;
              }
              return (
                <li key={`${group.stepId}-${String(indexOf.get(shown[0] as TraceEvent) ?? 0)}`}>
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                      {group.stepId === "run" ? "运行" : group.stepId}
                    </span>
                    <span className="h-px flex-1 bg-white/10" />
                  </div>

                  <ul className="space-y-1.5">
                    {shown.map((event) => {
                      const index = indexOf.get(event) ?? 0;
                      const summary = summarise(event);
                      const isOpen = expanded.has(index);
                      return (
                        <motion.li
                          animate={{ opacity: 1, y: 0 }}
                          className={`rounded border px-2.5 py-2 ${TONE_CARD[summary.tone]}`}
                          data-testid="trace-entry"
                          initial={{ opacity: 0, y: 4 }}
                          key={event.seq}
                          transition={{ duration: 0.18 }}
                        >
                          <button
                            aria-expanded={isOpen}
                            className="flex w-full items-start gap-2 text-left"
                            onClick={() => toggle(index)}
                            type="button"
                          >
                            <span
                              className={`mt-1.5 size-1.5 shrink-0 rounded-full ${TONE_DOT[summary.tone]}`}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex items-baseline gap-2">
                                <span className="font-mono text-[10px] text-slate-500">
                                  {event.seq}
                                </span>
                                <span className={`text-sm ${TONE_TEXT[summary.tone]}`}>
                                  {summary.title}
                                </span>
                              </span>
                              {!isOpen && summary.detail && (
                                <span className="mt-0.5 block truncate text-xs text-slate-500">
                                  {summary.detail.split("\n")[0]}
                                </span>
                              )}
                            </span>
                          </button>

                          {isOpen && summary.detail && (
                            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded bg-black/40 p-2 text-[11px] leading-relaxed text-slate-300">
                              {summary.detail}
                            </pre>
                          )}
                        </motion.li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <footer className="border-t border-white/10 px-3 py-1.5 text-[10px] text-slate-500">
        快捷键：空格 播放/暂停 · ← → 单步 · End 回到实时
      </footer>
    </section>
  );
}
