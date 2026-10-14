"""Controlled fault injection.

The evaluation problem with SECOM is that it labels outcomes, not causes. So causes are
created: take a real healthy window as the reference, perturb one sensor in a way that has a
name and a known location, and the ground truth is whatever you injected.

That is also how industrial RCA benchmarks work. The alternative — asking a model to guess at
ungrounded causes — produces numbers that cannot be checked.

Magnitudes are stated in units of the sensor's own spread, and default to levels a line would
actually notice. A 0.4-sigma nudge over a 50-sample window is not a fault, it is noise; the
sensitivity of the diagnoser to small excursions belongs in a separate sweep, not in a
detection suite whose numbers are supposed to mean something.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class FaultKind(StrEnum):
    DRIFT = "drift"
    STEP = "step"
    SPIKE = "spike"
    DEAD = "dead"
    DECORRELATE = "decorrelate"


#: Kinds the deviation baseline has no mechanism to see. Kept explicit so the evaluation
#: reports the blind spot instead of quietly dropping the case.
BASELINE_BLIND_SPOTS = (FaultKind.DECORRELATE,)

DEFAULT_MAGNITUDES: dict[FaultKind, float] = {
    # total drift across the window, in sigma
    FaultKind.DRIFT: 4.0,
    # level shift over the second half, in sigma
    FaultKind.STEP: 4.0,
    # outlier size, in sigma
    FaultKind.SPIKE: 10.0,
    FaultKind.DEAD: 1.0,
    FaultKind.DECORRELATE: 1.0,
}


@dataclass(frozen=True, slots=True)
class Fault:
    kind: FaultKind
    sensor: int
    group: int
    magnitude: float


@dataclass(frozen=True, slots=True)
class Case:
    """One evaluation case: what an operator would be looking at, and what was done to it."""

    #: The window under investigation.
    window: np.ndarray
    #: The healthy reference the window is compared against. Rows are disjoint from the
    #: window's own source, so a control case is genuinely two samples of the same process
    #: rather than one sample compared with itself.
    reference: np.ndarray
    #: None for a control case that must not be flagged.
    fault: Fault | None
    sensors_per_group: int

    @property
    def is_control(self) -> bool:
        return self.fault is None

    @property
    def truth_group(self) -> int | None:
        return None if self.fault is None else self.fault.group


def group_of(sensor: int, sensors_per_group: int) -> int:
    """Subsystem a sensor belongs to. SECOM has no sensor names, so blocks stand in for them."""
    return sensor // sensors_per_group


def _scale(reference: np.ndarray, sensor: int) -> float:
    column = reference[:, sensor]
    spread = float(np.nanstd(column))
    if spread == 0.0 or np.isnan(spread):
        return float(abs(np.nanmedian(column))) or 1.0
    return spread


def apply_fault(window: np.ndarray, fault: Fault, rng: np.random.Generator) -> np.ndarray:
    """Perturb one sensor. Returns a new array; the input is not modified."""
    affected = window.copy()
    rows = affected.shape[0]
    column = affected[:, fault.sensor]
    scale = _scale(affected, fault.sensor)
    axis = np.linspace(0.0, 1.0, rows)

    match fault.kind:
        case FaultKind.DRIFT:
            column += axis * fault.magnitude * scale
        case FaultKind.STEP:
            column[rows // 2 :] += fault.magnitude * scale
        case FaultKind.SPIKE:
            outliers = rng.choice(rows, size=max(1, rows // 10), replace=False)
            column[outliers] += fault.magnitude * scale
        case FaultKind.DEAD:
            # A frozen sensor: the value stops reflecting the process.
            column[:] = float(np.nanmedian(column))
        case FaultKind.DECORRELATE:
            # Same mean and spread, different relationship to the rest of the line. A
            # deviation detector cannot see this; that is the point of including it.
            column[:] = rng.permutation(column)

    affected[:, fault.sensor] = column
    return affected


def make_case(
    reference: np.ndarray,
    source_window: np.ndarray,
    rng: np.random.Generator,
    *,
    sensors_per_group: int,
    kinds: tuple[FaultKind, ...] = tuple(FaultKind),
) -> Case:
    """Build one case. Empty `kinds` produces a control that must not be flagged.

    `source_window` holds rows that are not in `reference`; it is copied before anything is
    done to it, so the caller's array survives and cases stay independent.
    """
    window = np.ascontiguousarray(source_window, dtype=np.float64).copy()
    fault: Fault | None = None

    if kinds:
        sensor = int(rng.integers(0, reference.shape[1]))
        kind = kinds[int(rng.integers(0, len(kinds)))]
        fault = Fault(
            kind=kind,
            sensor=sensor,
            group=group_of(sensor, sensors_per_group),
            magnitude=DEFAULT_MAGNITUDES[kind],
        )
        window = apply_fault(window, fault, rng)

    return Case(
        window=window,
        reference=reference,
        fault=fault,
        sensors_per_group=sensors_per_group,
    )
