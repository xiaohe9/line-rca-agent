"""Put the agent next to the baseline on the same cases.

The point of this file is the word "same". Comparing a result on one set of injected faults with
a result on another set proves nothing, so both diagnosers are scored by the same `run_suite`
over the same `build_cases` output with the same seed. The threshold the baseline uses is the
one calibrated exactly as `eval/baselines/baseline.json` records it.

    uv run python -m eval.run_agent_eval --cases 25 --controls 25

Needs a real provider. With `LRC_LLM_PROVIDER=fake` the agent is a scripted replay and the
comparison would be meaningless, so the script refuses that configuration rather than printing
a number nobody should trust.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from eval import secom
from eval.agent_diagnoser import AgentDiagnoser
from eval.diagnoser import DeviationDiagnoser, calibrate_threshold
from eval.injection import Case
from eval.run_eval import Metrics, build_cases, per_kind, run_suite
from line_rca_agent.contracts import LLMProvider

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "baselines" / "agent.json"


def build_agent_provider() -> LLMProvider:
    """Build the configured provider, refusing the scripted one."""
    from line_rca_api.agent_factory import build_provider
    from line_rca_api.config import Settings

    settings = Settings()
    if settings.llm_provider == "fake":
        print(
            "Refusing to run: LRC_LLM_PROVIDER=fake would score a scripted replay, not a model.\n"
            "Set LRC_LLM_PROVIDER and a key in .env first."
        )
        raise SystemExit(2)
    return build_provider(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score the agent and the deterministic baseline on identical cases."
    )
    parser.add_argument("--cases", type=int, default=25, help="injected-fault cases")
    parser.add_argument("--controls", type=int, default=25, help="healthy control cases")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--calibration-seed", type=int, default=7)
    parser.add_argument("--calibration-controls", type=int, default=400)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--sensors-per-group", type=int, default=8)
    parser.add_argument("--reference-rows", type=int, default=200)
    parser.add_argument("--window-rows", type=int, default=60)
    parser.add_argument("--pool-rows", type=int, default=400)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="agent steps per case; the first run used 4 and the agent ran out before reporting",
    )
    parser.add_argument("--dataset", type=Path, default=secom.DEFAULT_DIRECTORY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="skip the agent and just report the baseline on this case set",
    )
    args = parser.parse_args(argv)

    if not secom.available(args.dataset):
        print(f"SECOM is not in {args.dataset}. Run `python scripts/fetch_secom.py` first.")
        return 2

    dataset = secom.load(args.dataset)
    pool = secom.healthy_window(dataset, args.pool_rows)

    threshold, _ = calibrate_threshold(
        pool,
        sensors_per_group=args.sensors_per_group,
        reference_rows=args.reference_rows,
        window_rows=args.window_rows,
        controls=args.calibration_controls,
        seed=args.calibration_seed,
        target_false_positive_rate=args.target_fpr,
        correlation=False,
    )
    cases = build_cases(
        pool,
        reference_rows=args.reference_rows,
        window_rows=args.window_rows,
        cases=args.cases,
        controls=args.controls,
        seed=args.seed,
        sensors_per_group=args.sensors_per_group,
    )

    print(
        f"SECOM {dataset.shape[0]}x{dataset.shape[1]}   pool {pool.shape[0]}x{pool.shape[1]}   "
        f"{args.cases} faults + {args.controls} controls (seed {args.seed})"
    )
    print(f"baseline threshold {threshold:.2f}, calibrated on seed {args.calibration_seed}\n")

    baseline = DeviationDiagnoser(sensors_per_group=args.sensors_per_group, threshold=threshold)
    baseline_metrics, baseline_detail = run_suite(cases, baseline)
    print(
        f"baseline {baseline.name}: top1={baseline_metrics.top1_rate:.1%} "
        f"fpr={baseline_metrics.false_positive_rate:.1%}"
    )

    agent_metrics: Metrics | None = None
    agent_detail: list[dict[str, Any]] = []
    failures: list[str] = []
    elapsed = 0.0
    provider: LLMProvider | None = None

    if not args.baseline_only:
        provider = build_agent_provider()
        agent = AgentDiagnoser(
            provider,
            sensors_per_group=args.sensors_per_group,
            max_steps=args.max_steps,
        )
        print(f"\nrunning {agent.name} over {len(cases)} cases (max {args.max_steps} steps)...")

        started = time.monotonic()

        def progress(position: int, total: int, case: Case, diagnosis: object) -> None:
            if position % 5 == 0 or position == total:
                rate = (time.monotonic() - started) / position
                remaining = rate * (total - position)
                print(
                    f"  {position:>4}/{total}  {rate:.1f}s/case  ~{remaining / 60:.1f} min left",
                    flush=True,
                )

        agent_metrics, agent_detail = run_suite(cases, agent, progress=progress)
        elapsed = time.monotonic() - started
        failures = list(agent.failures)
        print(
            f"done in {elapsed / 60:.1f} min, {agent.calls} completed runs, {len(failures)} errors"
        )

    # ------------------------------------------------------------------ report
    print("\n" + "=" * 68)
    print(f"{'':<26}{'baseline':>14}{'agent':>14}")
    print("-" * 68)

    def row(label: str, base: float, other: float | None = None, percent: bool = True) -> None:
        if percent:
            left, right = f"{base:.1%}", ("—" if other is None else f"{other:.1%}")
        else:
            left, right = f"{base:.0f}", ("—" if other is None else f"{other:.0f}")
        print(f"{label:<26}{left:>14}{right:>14}")

    row("cases", baseline_metrics.cases, agent_metrics.cases if agent_metrics else None, False)
    row(
        "detected",
        baseline_metrics.detected,
        agent_metrics.detected if agent_metrics else None,
        False,
    )
    row(
        "root cause Top-1",
        baseline_metrics.top1_rate,
        agent_metrics.top1_rate if agent_metrics else None,
    )
    row(
        "root cause Top-3",
        baseline_metrics.top3_rate,
        agent_metrics.top3_rate if agent_metrics else None,
    )
    row(
        "controls",
        baseline_metrics.controls,
        agent_metrics.controls if agent_metrics else None,
        False,
    )
    row(
        "false positives",
        baseline_metrics.false_positive_rate,
        agent_metrics.false_positive_rate if agent_metrics else None,
    )
    print("=" * 68)

    baseline_kinds = per_kind(baseline_detail)
    agent_kinds = per_kind(agent_detail) if agent_metrics else {}
    print(f"\n{'per fault kind':<16}{'baseline top1':>15}{'agent top1':>13}{'n':>6}")
    for kind in sorted(baseline_kinds):
        left = baseline_kinds[kind]["top1Rate"]
        right = agent_kinds.get(kind, {}).get("top1Rate")
        count = baseline_kinds[kind]["cases"]
        print(f"{kind:<16}{left:>14.1%}{('—' if right is None else f'{right:.1%}'):>13}{count:>6}")

    if failures:
        print(f"\n{len(failures)} case(s) failed to produce a diagnosis, counted as no fault:")
        for message in failures[:5]:
            print(f"  - {message[:160]}")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cases": args.cases,
            "controls": args.controls,
            "seed": args.seed,
            "sensorsPerGroup": args.sensors_per_group,
            "referenceRows": args.reference_rows,
            "windowRows": args.window_rows,
            "baseline": {
                "diagnoser": baseline.name,
                "threshold": round(threshold, 4),
                "metrics": baseline_metrics.as_dict(),
                "perKind": baseline_kinds,
            },
            "agent": (
                None
                if agent_metrics is None or provider is None
                else {
                    "diagnoser": f"agent-{provider.name}",
                    "model": getattr(provider, "model", None),
                    "maxSteps": args.max_steps,
                    "elapsedSeconds": round(elapsed, 1),
                    "failures": len(failures),
                    "stepLimitHits": agent.exhausted,
                    "metrics": agent_metrics.as_dict(),
                    "perKind": agent_kinds,
                    # What it said and why. A detection rate on its own is a number with no
                    # explanation, and the explanation is the part worth reading.
                    "samples": agent.answers[:40],
                }
            ),
        }
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
