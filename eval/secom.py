"""Load the SECOM dataset.

SECOM is a real semiconductor line: 1567 production entities, ~590 sensor readings each, a
pass/fail label, and a lot of missing values. It has **no root-cause labels** — its own task
is feature selection — which is why root-cause evaluation in this repository runs on
controlled fault injection over a real baseline rather than on the dataset's own label column.

    python scripts/fetch_secom.py     # downloads into eval/datasets/secom/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "datasets" / "secom"

#: A sensor is treated as constant — and therefore useless as a fault carrier — when its
#: robust spread is below this fraction of its own magnitude. Measured: at 1e-6 a sensor whose
#: spread is 0.03% of its level survived and produced variance ratios of 1000x on healthy
#: windows, which is numerical noise, not a signal.
CONSTANT_SENSOR_FLOOR = 1e-3


class DatasetMissingError(FileNotFoundError):
    """The dataset has not been fetched. The message says how."""


@dataclass(frozen=True, slots=True)
class SecomDataset:
    #: (n_samples, n_sensors), NaN where a sensor did not report.
    features: np.ndarray
    #: (n_samples,) with -1 for a passing entity and 1 for a failing one.
    labels: np.ndarray
    source: Path

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.features.shape[0]), int(self.features.shape[1]))

    @property
    def missing_fraction(self) -> float:
        return float(np.isnan(self.features).mean())

    @property
    def fail_fraction(self) -> float:
        return float((self.labels == 1).mean())


def available(directory: Path = DEFAULT_DIRECTORY) -> bool:
    return (directory / "secom.data").is_file()


def load(directory: Path = DEFAULT_DIRECTORY) -> SecomDataset:
    data_path = directory / "secom.data"
    labels_path = directory / "secom_labels.data"
    if not data_path.is_file() or not labels_path.is_file():
        raise DatasetMissingError(
            f"SECOM is not present in {directory}. Run `python scripts/fetch_secom.py` first."
        )

    features = np.loadtxt(data_path, dtype=np.float64, ndmin=2)
    raw_labels = np.loadtxt(labels_path, dtype=str, usecols=0, ndmin=1)
    labels = raw_labels.astype(np.int64)

    if features.shape[0] != labels.shape[0]:
        raise ValueError(
            f"SECOM is inconsistent: {features.shape[0]} feature rows vs {labels.shape[0]} labels"
        )
    return SecomDataset(features=features, labels=labels, source=data_path)


def healthy_window(dataset: SecomDataset, rows: int) -> np.ndarray:
    """A window of passing entities, which is what a line looks like when nothing is wrong.

    Two filters, both because leaving either in place makes the evaluation measure something
    other than the diagnoser:

    * **complete columns only** — a fault injected into a mostly-NaN sensor would be measuring
      the dataset's sparsity;
    * **non-constant columns only** — SECOM contains sensors that barely move. Their robust
      spread is numerically zero, so any tiny difference becomes a hundred-sigma "excursion",
      which is what drove the first calibrated threshold to 141. A signal that cannot vary
      cannot carry a fault.
    """
    passing = dataset.features[dataset.labels == -1]
    if passing.shape[0] < rows:
        raise ValueError(f"SECOM has only {passing.shape[0]} passing entities, needed {rows}")

    window = passing[:rows]
    complete = ~np.isnan(window).any(axis=0)
    window = window[:, complete]

    centre = np.median(window, axis=0)
    mad = np.median(np.abs(window - centre), axis=0) * 1.4826
    informative = mad > CONSTANT_SENSOR_FLOOR * (np.abs(centre) + 1.0)
    window = window[:, informative]

    if window.shape[1] == 0:
        raise ValueError("no sensor survived the completeness and variability filters")
    return np.ascontiguousarray(window, dtype=np.float64)
