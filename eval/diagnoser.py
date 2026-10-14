"""The deterministic baseline the agent has to beat.

Two signals per sensor, both measured against the healthy reference window and both
normalised by the **standard error** of the statistic rather than by the raw spread:

* a **level shift** in the window's median, whose standard error follows from the window
  length — comparing a 50-sample median against a 200-sample median using the population
  spread would report noise as a 6-sigma excursion, which is exactly the mistake the first
  version of this file made;
* a **spread change**, expressed as a log-variance ratio with its own standard error, which
  is what a frozen sensor looks like when its median has not moved.

A group is scored by its worst sensor: averaging across a subsystem would let one clearly
broken signal be diluted by its quiet neighbours, which is the opposite of how an engineer
reads a trend.

The threshold is **calibrated**, not guessed. `eval.run_eval --calibrate` measures the null
distribution on held-out control windows and sets the threshold at the requested false
positive quantile, because testing ~400 sensors at once means the largest of 400 null
statistics is routinely around 3.5 by chance alone.

What this cannot see is a sensor that keeps its mean and its spread but loses its relationship
to the rest of the line (`DECORRELATE`). That blind spot is reported rather than hidden, and
it is a large part of why an agent that can plan a comparison is worth having at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from eval.injection import Case, group_of

#: Standard error of a sample median, as a multiple of sigma/sqrt(n).
MEDIAN_SE_FACTOR = 1.2533
EPSILON = 1e-9
#: A window is frozen when it does not move at all while the reference did. Testing
#: `spread < ratio * reference_spread` instead looks reasonable and is wrong: a sensor whose
#: values repeat heavily can have a median absolute deviation of exactly zero over 60 rows,
#: which fired this rule on healthy windows and pinned the calibrated threshold at its ceiling.
DEAD_EVIDENCE = 1000.0
#: Points beyond this many robust sigmas of the reference count as outliers.
SPIKE_SIGMAS = 8.0
#: Evidence per outlier. One exceedance at 8 sigma is already far outside what a healthy
#: sensor produces, so the score starts above any calibrated threshold and grows with count.
SPIKE_BASE_EVIDENCE = 40.0
#: A single point beyond 8 sigma is not evidence of a spike fault: SECOM's healthy sensors are
#: heavy-tailed enough to produce one. A spike fault contaminates a run of rows, so the rule
#: requires a minimum count — measured, because one outlier drove the calibrated threshold to
#: 59 and left nothing else detectable.
SPIKE_MIN_OUTLIERS = 3
SPIKE_MIN_OUTLIER_FRACTION = 0.05


@dataclass(frozen=True, slots=True)
class Diagnosis:
    #: Groups, most suspicious first.
    ranked_groups: tuple[int, ...]
    scores: dict[str, float]
    flagged: bool

    @property
    def top_groups(self) -> tuple[int, ...]:
        return self.ranked_groups[:3]


def _robust_scale(reference: np.ndarray) -> np.ndarray:
    """Scale for the standard error of the median.

    Deliberately the sample standard deviation, not the MAD. SECOM's sensors are heavy-tailed
    enough that the MAD understates their spread, which shrinks the standard error and inflates
    every z-score by roughly an order of magnitude — measured, that is what put a healthy
    adjacent window at a 63-sigma excursion. The standard deviation is inflated by the same
    tails, which errs the safe way: this baseline would rather miss a fault than cry wolf.
    """
    spread = np.std(reference, axis=0)
    return np.asarray(np.where(spread > EPSILON, spread, 1.0), dtype=np.float64)


class DeviationDiagnoser:
    name = "deviation-baseline"

    def __init__(self, *, sensors_per_group: int, threshold: float) -> None:
        self._sensors_per_group = sensors_per_group
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def sensors_per_group(self) -> int:
        return self._sensors_per_group

    def sensor_scores(self, case: Case) -> np.ndarray:
        reference = case.reference
        window = case.window
        n_reference = reference.shape[0]
        n_window = window.shape[0]

        reference_centre = np.median(reference, axis=0)
        window_centre = np.median(window, axis=0)

        scale = _robust_scale(reference)
        shift = np.abs(window_centre - reference_centre)
        # Two medians, each with its own standard error. Dividing by the raw spread instead
        # would report ordinary sampling noise as a multi-sigma excursion.
        median_se = MEDIAN_SE_FACTOR * scale * np.sqrt(1.0 / n_window + 1.0 / n_reference)
        shift_z = shift / median_se

        reference_range = np.ptp(reference, axis=0)
        window_range = np.ptp(window, axis=0)
        frozen = (reference_range > EPSILON) & (window_range <= EPSILON)
        dead_evidence = np.where(frozen, DEAD_EVIDENCE, 0.0)

        # Outlier count, not a variance ratio: variance on a nearly-constant column is
        # numerical noise, while counting points beyond a robust threshold is stable under
        # heavy tails and is exactly the shape a spike fault has.
        outliers = np.sum(
            np.abs(window - reference_centre) > SPIKE_SIGMAS * scale,
            axis=0,
        )
        minimum_outliers = max(
            SPIKE_MIN_OUTLIERS, int(np.ceil(SPIKE_MIN_OUTLIER_FRACTION * n_window))
        )
        spike_evidence = np.where(
            outliers >= minimum_outliers,
            SPIKE_BASE_EVIDENCE + outliers.astype(float),
            0.0,
        )

        combined = np.maximum(np.maximum(shift_z, dead_evidence), spike_evidence)
        return np.asarray(combined, dtype=np.float64)

    def group_scores(self, sensor_scores: np.ndarray) -> dict[int, float]:
        n_groups = group_of(sensor_scores.shape[0] - 1, self._sensors_per_group) + 1
        return {
            group: float(
                np.max(
                    sensor_scores[
                        group * self._sensors_per_group : (group + 1) * self._sensors_per_group
                    ],
                    initial=0.0,
                )
            )
            for group in range(n_groups)
        }

    def peak_score(self, case: Case) -> float:
        """The largest group score. Used for calibration, where no ranking is needed."""
        scores = self.group_scores(self.sensor_scores(case))
        return max(scores.values(), default=0.0)

    def diagnose(self, case: Case) -> Diagnosis:
        scores = self.group_scores(self.sensor_scores(case))
        ranked = tuple(
            group for group, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        best = scores[ranked[0]] if ranked else 0.0
        return Diagnosis(
            ranked_groups=ranked,
            scores={str(group): value for group, value in scores.items()},
            flagged=best >= self._threshold,
        )


def calibrate_threshold(
    pool: np.ndarray,
    *,
    sensors_per_group: int,
    reference_rows: int,
    window_rows: int,
    controls: int,
    seed: int,
    target_false_positive_rate: float,
) -> tuple[float, float]:
    """Pick the threshold from the null distribution. Returns (threshold, observed max).

    Nothing is injected: each probe is an adjacent pair of real windows from a healthy
    process. Whatever the largest group statistic reaches here is what "no fault" looks like,
    and the threshold is set so that only `target_false_positive_rate` of such windows would
    be flagged.
    """
    from eval.injection import make_case

    rng = np.random.default_rng(seed)
    probe = DeviationDiagnoser(sensors_per_group=sensors_per_group, threshold=float("inf"))
    span = reference_rows + window_rows
    max_start = max(1, pool.shape[0] - span)

    peaks: list[float] = []
    for _ in range(controls):
        start = int(rng.integers(0, max_start + 1))
        case = make_case(
            np.ascontiguousarray(pool[start : start + reference_rows]),
            np.ascontiguousarray(pool[start + reference_rows : start + span]),
            rng,
            sensors_per_group=sensors_per_group,
            kinds=(),
        )
        peaks.append(probe.peak_score(case))

    threshold = float(np.quantile(peaks, 1.0 - target_false_positive_rate))
    return threshold, float(np.max(peaks))
