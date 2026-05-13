"""Helpers for device-group aggregation.

The public ``agg_*`` columns are compatibility columns.  They should look like
plant-level aggregate signals, but the aggregate should still preserve enough
structure for diagnostics: active unit count, spread, and stage-specific means.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class AggregateStats:
    mean: float
    std: float
    min: float
    max: float
    active_count: int
    total_count: int


def active_mask(total_count: int, active_count: int) -> np.ndarray:
    """Return a deterministic leading active-unit mask."""
    n = max(int(total_count), 0)
    k = int(np.clip(active_count, 0, n))
    mask = np.zeros(n, dtype=bool)
    mask[:k] = True
    return mask


def aggregate_active(values: np.ndarray, active: np.ndarray | None = None) -> AggregateStats:
    """Aggregate only running devices and report spread diagnostics.

    If no device is active, all devices are used as a fallback so the public
    DCS value remains finite during simulated shutdown/transient states.
    """
    arr = np.asarray(values, dtype=float)
    if active is None:
        selected = arr
        active_count = arr.size
    else:
        mask = np.asarray(active, dtype=bool)
        selected = arr[mask]
        active_count = int(mask.sum())
        if selected.size == 0:
            selected = arr

    if selected.size == 0:
        return AggregateStats(0.0, 0.0, 0.0, 0.0, 0, int(arr.size))

    return AggregateStats(
        mean=float(np.mean(selected)),
        std=float(np.std(selected)),
        min=float(np.min(selected)),
        max=float(np.max(selected)),
        active_count=active_count,
        total_count=int(arr.size),
    )


def write_aggregate(bus: dict, prefix: str, stats: AggregateStats, *, public_key: str | None = None) -> None:
    """Write compatibility aggregate plus diagnostics to ``bus``."""
    key = public_key or prefix
    bus[key] = stats.mean
    bus[f"{prefix}_std"] = stats.std
    bus[f"{prefix}_min"] = stats.min
    bus[f"{prefix}_max"] = stats.max
    bus[f"{prefix}_on_count"] = stats.active_count
    bus[f"{prefix}_source_count"] = stats.total_count
