"""Evaluation tests.

Synthetic references only: the harness itself must be testable without the 5 MB dataset, and
CI should not need the network to check the metrics arithmetic. The dataset-dependent path is
exercised by `python -m eval.run_eval` and its recorded baseline.
"""

from __future__ import annotations

import numpy as np
import pytest
from eval.diagnoser import DeviationDiagnoser, calibrate_threshold
from eval.injection import Fault, FaultKind, apply_fault, group_of, make_case
from eval.run_eval import Metrics, build_cases, compare, per_kind, run_suite

SENSORS = 32
SENSORS_PER_GROUP = 8


def reference(seed: int = 1, rows: int = 200, sensors: int = SENSORS) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, 1.0, size=(rows, sensors))


@pytest.fixture
def pool() -> np.ndarray:
    return np.random.default_rng(99).normal(0.0, 1.0, size=(400, SENSORS))


def test_group_of_blocks_sensors() -> None:
    assert group_of(0, 8) == 0
    assert group_of(7, 8) == 0
    assert group_of(8, 8) == 1
    assert group_of(31, 8) == 3


def test_injection_is_deterministic_and_touches_one_sensor() -> None:
    base = reference()
    fault = Fault(kind=FaultKind.STEP, sensor=5, group=0, magnitude=4.0)

    first = apply_fault(base[-60:], fault, np.random.default_rng(3))
    second = apply_fault(base[-60:], fault, np.random.default_rng(3))

    assert np.array_equal(first, second), "the same seed must produce the same fault"
    changed = np.flatnonzero(np.any(first != base[-60:], axis=0))
    assert changed.tolist() == [5]


def test_injection_does_not_modify_the_caller_array() -> None:
    window = reference()[-60:]
    original = window.copy()
    apply_fault(window, Fault(FaultKind.SPIKE, 2, 0, 10.0), np.random.default_rng(3))
    assert np.array_equal(window, original)


@pytest.mark.parametrize("kind", [FaultKind.DRIFT, FaultKind.STEP, FaultKind.SPIKE, FaultKind.DEAD])
def test_clear_faults_are_located_in_the_right_group(kind: FaultKind) -> None:
    base = reference()
    magnitudes = {
        FaultKind.DRIFT: 6.0,
        FaultKind.STEP: 6.0,
        FaultKind.SPIKE: 12.0,
        FaultKind.DEAD: 1.0,
    }
    case = make_case(
        base,
        base[-60:],
        np.random.default_rng(5),
        sensors_per_group=SENSORS_PER_GROUP,
    )
    fault = Fault(
        kind=kind, sensor=11, group=group_of(11, SENSORS_PER_GROUP), magnitude=magnitudes[kind]
    )
    faulty = apply_fault(case.window, fault, np.random.default_rng(5))
    injected = make_case(
        base, faulty, np.random.default_rng(5), sensors_per_group=SENSORS_PER_GROUP, kinds=()
    )
    object.__setattr__(injected, "fault", fault)

    diagnosis = DeviationDiagnoser(sensors_per_group=SENSORS_PER_GROUP, threshold=5.0).diagnose(
        injected
    )

    assert diagnosis.flagged
    assert diagnosis.ranked_groups[0] == fault.group


def test_a_decorrelated_sensor_is_the_documented_blind_spot() -> None:
    """Same mean, same spread, no relationship left — a deviation test cannot see it."""
    base = reference()
    case = make_case(
        base, base[-60:], np.random.default_rng(5), sensors_per_group=SENSORS_PER_GROUP, kinds=()
    )
    fault = Fault(FaultKind.DECORRELATE, 11, group_of(11, SENSORS_PER_GROUP), 1.0)
    decorrelated = apply_fault(case.window, fault, np.random.default_rng(5))
    injected = make_case(
        base, decorrelated, np.random.default_rng(5), sensors_per_group=SENSORS_PER_GROUP, kinds=()
    )
    object.__setattr__(injected, "fault", fault)

    diagnosis = DeviationDiagnoser(sensors_per_group=SENSORS_PER_GROUP, threshold=5.0).diagnose(
        injected
    )

    assert not diagnosis.flagged or diagnosis.ranked_groups[0] != fault.group


def test_calibration_returns_a_threshold_above_the_null(pool: np.ndarray) -> None:
    threshold, observed_max = calibrate_threshold(
        pool,
        sensors_per_group=SENSORS_PER_GROUP,
        reference_rows=200,
        window_rows=60,
        controls=200,
        seed=11,
        target_false_positive_rate=0.05,
    )

    assert observed_max >= 0
    assert threshold <= observed_max + 1e-9, "the threshold sits inside the observed null"


def test_suite_separates_detection_from_false_positives(pool: np.ndarray) -> None:
    cases = build_cases(
        pool,
        reference_rows=200,
        window_rows=60,
        cases=40,
        controls=40,
        seed=2,
        sensors_per_group=SENSORS_PER_GROUP,
    )
    # A very low threshold: everything is flagged, so detection is perfect and so is the
    # false-positive count. The two numbers must move together, not be conflated.
    metrics, detail = run_suite(
        cases, DeviationDiagnoser(sensors_per_group=SENSORS_PER_GROUP, threshold=0.0)
    )

    assert metrics.cases == 40
    assert metrics.controls == 40
    assert metrics.detected == 40
    assert metrics.false_positives == 40
    assert metrics.detection_rate == 1.0
    assert metrics.false_positive_rate == 1.0
    assert len(detail) == 80


def test_metrics_arithmetic_and_serialisation() -> None:
    metrics = Metrics(
        cases=10,
        detected=6,
        top1=3,
        top3=4,
        controls=20,
        false_positives=1,
        blind_spot_cases=4,
        blind_spot_detected=1,
    )
    payload = metrics.as_dict()

    assert payload["top1Rate"] == 0.3
    assert payload["top3Rate"] == 0.4
    assert payload["detectionRate"] == 0.6
    assert payload["falsePositiveRate"] == 0.05
    assert payload["blindSpotRate"] == 0.25


def test_zero_denominators_do_not_divide_by_zero() -> None:
    empty = Metrics(0, 0, 0, 0, 0, 0, 0, 0)
    assert empty.top1_rate == 0.0
    assert empty.false_positive_rate == 0.0
    assert empty.blind_spot_rate == 0.0


def test_per_kind_reports_detection_and_top1() -> None:
    detail: list[dict[str, object]] = [
        {"kind": "step", "truthGroup": 1, "ranked": [1, 2], "flagged": True},
        {"kind": "step", "truthGroup": 2, "ranked": [1, 2], "flagged": True},
        {"kind": "step", "truthGroup": 3, "ranked": [1, 2], "flagged": False},
        {"kind": "control", "truthGroup": None, "ranked": [1], "flagged": False},
    ]
    summary = per_kind(detail)["step"]

    assert summary["cases"] == 3
    assert summary["detected"] == 2
    assert summary["top1"] == 1
    assert summary["detectionRate"] == pytest.approx(0.6667)
    assert summary["top1Rate"] == pytest.approx(0.3333)


def test_compare_reports_only_real_regressions() -> None:
    good = Metrics(10, 8, 6, 7, 10, 0, 0, 0)
    assert compare(good, {"top1Rate": 0.5, "falsePositiveRate": 0.0}) == []

    worse_top1 = Metrics(10, 8, 1, 7, 10, 0, 0, 0)
    problems = compare(worse_top1, {"top1Rate": 0.5})
    assert problems and "top1Rate" in problems[0]

    worse_fp = Metrics(10, 8, 6, 7, 10, 5, 0, 0)
    problems = compare(worse_fp, {"falsePositiveRate": 0.0})
    assert problems and "falsePositiveRate" in problems[0]


def test_compare_tolerates_sampling_noise() -> None:
    slightly_worse = Metrics(150, 59, 47, 50, 150, 10, 0, 0)
    assert compare(slightly_worse, {"top1Rate": 0.33}) == []
