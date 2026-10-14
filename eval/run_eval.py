"""The evaluation harness.

Runs the diagnoser over injected cases and control cases and reports the numbers that matter
for a zero-tolerance setting: how often the true subsystem is named first, how often it is
named at all, and how often a healthy line is flagged.

    python -m eval.run_eval                        # report, threshold calibrated on the fly
    python -m eval.run_eval --out baseline.json    # record a baseline
    python -m eval.run_eval --check baseline.json  # fail on regression, for CI

The reference window and the window under investigation come from **disjoint rows**, so a
control case is two independent samples of a healthy process rather than a sample compared
with itself. Without that, the false-positive number is meaningless — which is how the first
version of this harness reported 100%.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from eval import secom
from eval.diagnoser import DeviationDiagnoser, calibrate_threshold
from eval.injection import BASELINE_BLIND_SPOTS, Case, FaultKind, make_case

DEFAULT_BASELINE = Path(__file__).resolve().parent / "baselines" / "baseline.json"
#: A regression is a drop larger than this in a rate, or a rise larger than this in false
#: positives. Tolerance exists because the suite is sampled, not exhaustive.
TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class Metrics:
    cases: int
    detected: int
    top1: int
    top3: int
    controls: int
    false_positives: int
    blind_spot_cases: int
    blind_spot_detected: int

    @property
    def detection_rate(self) -> float:
        return self.detected / self.cases if self.cases else 0.0

    @property
    def top1_rate(self) -> float:
        return self.top1 / self.cases if self.cases else 0.0

    @property
    def top3_rate(self) -> float:
        return self.top3 / self.cases if self.cases else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / self.controls if self.controls else 0.0

    @property
    def blind_spot_rate(self) -> float:
        return self.blind_spot_detected / self.blind_spot_cases if self.blind_spot_cases else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            **asdict(self),
            "detectionRate": round(self.detection_rate, 4),
            "top1Rate": round(self.top1_rate, 4),
            "top3Rate": round(self.top3_rate, 4),
            "falsePositiveRate": round(self.false_positive_rate, 4),
            "blindSpotRate": round(self.blind_spot_rate, 4),
        }


def build_cases(
    pool: np.ndarray,
    *,
    reference_rows: int,
    window_rows: int,
    cases: int,
    controls: int,
    seed: int,
    sensors_per_group: int,
) -> list[Case]:
    """Draw each case as an adjacent pair: the reference period, then the period under review.

    SECOM rows are time-ordered and the process drifts over months, so a reference taken from
    one part of the file and a window from another are two different processes — which is how
    an earlier version of this harness reported a 91-sigma "excursion" on a healthy line.
    Comparing adjacent periods is both what a plant actually does and what makes a control
    case a genuine null.
    """
    rng = np.random.default_rng(seed)
    span = reference_rows + window_rows
    max_start = max(1, pool.shape[0] - span)

    built: list[Case] = []
    for index in range(cases + controls):
        start = int(rng.integers(0, max_start + 1))
        kinds: tuple[FaultKind, ...] = () if index >= cases else tuple(FaultKind)
        built.append(
            make_case(
                np.ascontiguousarray(pool[start : start + reference_rows]),
                np.ascontiguousarray(pool[start + reference_rows : start + span]),
                rng,
                sensors_per_group=sensors_per_group,
                kinds=kinds,
            )
        )
    return built


def run_suite(
    cases: list[Case], diagnoser: DeviationDiagnoser
) -> tuple[Metrics, list[dict[str, Any]]]:
    detected = top1 = top3 = false_positives = 0
    blind_spot_cases = blind_spot_detected = 0
    detail: list[dict[str, Any]] = []

    for case in cases:
        diagnosis = diagnoser.diagnose(case)
        if case.is_control:
            if diagnosis.flagged:
                false_positives += 1
            detail.append(
                {
                    "kind": "control",
                    "truthGroup": None,
                    "ranked": list(diagnosis.top_groups),
                    "flagged": diagnosis.flagged,
                }
            )
            continue

        truth = case.truth_group
        assert truth is not None
        if diagnosis.flagged:
            detected += 1
            if diagnosis.ranked_groups[0] == truth:
                top1 += 1
            if truth in diagnosis.top_groups:
                top3 += 1
        if case.fault is not None and case.fault.kind in BASELINE_BLIND_SPOTS:
            blind_spot_cases += 1
            if diagnosis.flagged:
                blind_spot_detected += 1
        detail.append(
            {
                "kind": case.fault.kind if case.fault else "none",
                "truthGroup": truth,
                "ranked": list(diagnosis.top_groups),
                "flagged": diagnosis.flagged,
            }
        )

    metrics = Metrics(
        cases=sum(1 for case in cases if not case.is_control),
        detected=detected,
        top1=top1,
        top3=top3,
        controls=sum(1 for case in cases if case.is_control),
        false_positives=false_positives,
        blind_spot_cases=blind_spot_cases,
        blind_spot_detected=blind_spot_detected,
    )
    return metrics, detail


def per_kind(detail: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    """Detection and Top-1 per fault kind, because an aggregate hides which fault is missed."""
    summary: dict[str, dict[str, float | int]] = {}
    for entry in detail:
        if entry["kind"] == "control":
            continue
        bucket = summary.setdefault(str(entry["kind"]), {"cases": 0, "detected": 0, "top1": 0})
        bucket["cases"] = int(bucket["cases"]) + 1
        if entry["flagged"]:
            bucket["detected"] = int(bucket["detected"]) + 1
        ranked = entry["ranked"]
        if entry["flagged"] and ranked and ranked[0] == entry["truthGroup"]:
            bucket["top1"] = int(bucket["top1"]) + 1
    for bucket in summary.values():
        cases = int(bucket["cases"]) or 1
        bucket["detectionRate"] = round(int(bucket["detected"]) / cases, 4)
        bucket["top1Rate"] = round(int(bucket["top1"]) / cases, 4)
    return summary


def compare(metrics: Metrics, baseline: dict[str, Any]) -> list[str]:
    """Return the regressions, if any. Empty means the run is at least as good."""
    problems: list[str] = []
    checks = (
        ("top1Rate", metrics.top1_rate, "lower"),
        ("top3Rate", metrics.top3_rate, "lower"),
        ("detectionRate", metrics.detection_rate, "lower"),
        ("falsePositiveRate", metrics.false_positive_rate, "higher"),
    )
    for key, actual, worse in checks:
        expected = baseline.get(key)
        if expected is None:
            continue
        if worse == "lower" and actual < expected - TOLERANCE:
            problems.append(f"{key}: {actual:.4f} < baseline {expected:.4f}")
        if worse == "higher" and actual > expected + TOLERANCE:
            problems.append(f"{key}: {actual:.4f} > baseline {expected:.4f}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the RCA baseline on SECOM.")
    parser.add_argument("--cases", type=int, default=150)
    parser.add_argument("--controls", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--calibration-seed", type=int, default=7)
    parser.add_argument("--calibration-controls", type=int, default=400)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--sensors-per-group", type=int, default=8)
    parser.add_argument("--reference-rows", type=int, default=200)
    parser.add_argument("--window-rows", type=int, default=60)
    parser.add_argument("--pool-rows", type=int, default=400)
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="override the calibrated threshold (default: calibrate)",
    )
    parser.add_argument("--dataset", type=Path, default=secom.DEFAULT_DIRECTORY)
    parser.add_argument("--out", type=Path, default=None, help="write the metrics here")
    parser.add_argument("--check", type=Path, default=None, help="fail on regression vs this")
    args = parser.parse_args(argv)

    if not secom.available(args.dataset):
        print(f"SECOM is not in {args.dataset}. Run `python scripts/fetch_secom.py` first.")
        return 2

    dataset = secom.load(args.dataset)
    pool = secom.healthy_window(dataset, args.pool_rows)

    print(
        f"SECOM {dataset.shape[0]}x{dataset.shape[1]}  "
        f"missing={dataset.missing_fraction:.1%}  fail={dataset.fail_fraction:.1%}"
    )
    print(
        f"healthy pool {pool.shape[0]}x{pool.shape[1]} "
        "(complete and non-constant sensors, passing entities only)"
    )

    if args.threshold is None:
        threshold, observed_max = calibrate_threshold(
            pool,
            sensors_per_group=args.sensors_per_group,
            reference_rows=args.reference_rows,
            window_rows=args.window_rows,
            controls=args.calibration_controls,
            seed=args.calibration_seed,
            target_false_positive_rate=args.target_fpr,
        )
        print(
            f"\ncalibration: {args.calibration_controls} adjacent control window pairs, "
            f"target FPR {args.target_fpr:.0%}"
        )
        print(f"  null peak statistic: max {observed_max:.2f}")
        print(f"  threshold set to   : {threshold:.2f}")
    else:
        threshold = args.threshold
        print(f"\nthreshold supplied: {threshold:.2f}")

    cases = build_cases(
        pool,
        reference_rows=args.reference_rows,
        window_rows=args.window_rows,
        cases=args.cases,
        controls=args.controls,
        seed=args.seed,
        sensors_per_group=args.sensors_per_group,
    )
    diagnoser = DeviationDiagnoser(sensors_per_group=args.sensors_per_group, threshold=threshold)
    metrics, detail = run_suite(cases, diagnoser)

    print(f"\ndiagnoser: {diagnoser.name}  threshold={diagnoser.threshold:.2f}")
    print(f"  cases                {metrics.cases}  (+{metrics.controls} controls)")
    print(f"  detected             {metrics.detected}  ({metrics.detection_rate:.1%})")
    print(f"  root cause Top-1     {metrics.top1}  ({metrics.top1_rate:.1%})")
    print(f"  root cause Top-3     {metrics.top3}  ({metrics.top3_rate:.1%})")
    print(f"  false positives      {metrics.false_positives}  ({metrics.false_positive_rate:.1%})")
    print(
        f"  blind spot ({', '.join(kind.value for kind in BASELINE_BLIND_SPOTS)})  "
        f"{metrics.blind_spot_detected}/{metrics.blind_spot_cases}  "
        f"({metrics.blind_spot_rate:.1%})"
    )

    print("\nper fault kind:")
    for kind, bucket in sorted(per_kind(detail).items()):
        print(
            f"  {kind:<14} n={bucket['cases']:<4} "
            f"detection={bucket['detectionRate']:.1%}  top1={bucket['top1Rate']:.1%}"
        )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": "deterministic",
            "diagnoser": diagnoser.name,
            "threshold": round(threshold, 4),
            "thresholdSource": "calibrated" if args.threshold is None else "supplied",
            "targetFalsePositiveRate": args.target_fpr,
            "seed": args.seed,
            "calibrationSeed": args.calibration_seed,
            "sensorsPerGroup": args.sensors_per_group,
            "referenceRows": args.reference_rows,
            "windowRows": args.window_rows,
            "dataset": {"samples": dataset.shape[0], "sensors": dataset.shape[1]},
            "metrics": metrics.as_dict(),
            "perKind": per_kind(detail),
        }
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"\nwrote {args.out}")

    if args.check is not None:
        if not args.check.is_file():
            print(f"\nno baseline at {args.check}; nothing to compare against")
            return 0
        baseline = json.loads(args.check.read_text("utf-8"))
        problems = compare(metrics, baseline.get("metrics", {}))
        if problems:
            print("\nREGRESSION:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(f"\nno regression against {args.check}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
