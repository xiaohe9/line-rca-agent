import { useCallback, useRef, useState } from "react";

import { streamAnalysis } from "../../shared/api/client";
import type { TraceEvent } from "../../shared/trace/events";

export type RunStatus = "idle" | "streaming" | "done" | "error";

export interface RunState {
  readonly status: RunStatus;
  readonly goal: string;
  readonly events: readonly TraceEvent[];
  readonly answer: string | null;
  readonly error: string | null;
}

const INITIAL: RunState = { status: "idle", goal: "", events: [], answer: null, error: null };

export interface RunStream extends RunState {
  readonly run: (goal: string) => Promise<void>;
  readonly cancel: () => void;
  readonly reset: () => void;
}

export function useRunStream(): RunStream {
  const [state, setState] = useState<RunState>(INITIAL);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async (goal: string) => {
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;

    setState({ status: "streaming", goal, events: [], answer: null, error: null });

    try {
      await streamAnalysis(goal, {
        signal: active.signal,
        onEvent: (event) => {
          setState((previous) => ({
            ...previous,
            events: [...previous.events, event],
            answer:
              event.type === "answer"
                ? String(event.payload["text"] ?? "")
                : previous.answer,
          }));
        },
      });
      setState((previous) =>
        previous.status === "error" ? previous : { ...previous, status: "done" },
      );
    } catch (error) {
      // A user-initiated cancel is not a failure; `cancel()` already reset the status.
      if (active.signal.aborted) {
        return;
      }
      setState((previous) => ({
        ...previous,
        status: "error",
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, []);

  const cancel = useCallback(() => {
    controller.current?.abort();
    setState((previous) => ({ ...previous, status: "idle" }));
  }, []);

  const reset = useCallback(() => {
    controller.current?.abort();
    setState(INITIAL);
  }, []);

  return { ...state, run, cancel, reset };
}
