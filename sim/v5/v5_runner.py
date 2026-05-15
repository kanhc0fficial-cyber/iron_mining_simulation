"""V5 simulation runner.

Bridges the :class:`~sim.v5.engine.V5SimulationEngine` to the CLI entry
point in ``scripts/run_simulation.py``.  The runner:

1. Loads the V5 spec via :func:`~sim.v5.spec_loader.load_spec`.
2. Initialises and runs the :class:`~sim.v5.engine.V5SimulationEngine`.
3. Collects one output row per time step.
4. Writes rows to parquet or CSV via :class:`~sim.output.writer.Writer`.

The output columns are defined in :mod:`sim.v5.output_schema`.  Only
non-template, concrete variable names are included so that the schema
remains stable across parameter variations.

Usage
-----
    from sim.v5.v5_runner import V5Runner

    runner = V5Runner(
        output_path="output/v5_quick.parquet",
        fmt="parquet",
        n_steps=10,
        seed=42,
    )
    runner.run()
"""
from __future__ import annotations

import math
import random
import warnings
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from sim.output.writer import Writer
from sim.v5.engine import DEFAULT_PARAMS, V5SimulationEngine
from sim.v5.output_schema import V5_OUTPUT_COLUMNS
from sim.v5.spec_loader import load_spec


class V5Runner:
    """Run the V5 simulation engine and write output to file.

    Parameters
    ----------
    output_path :
        Destination file path (.parquet or .csv).
    fmt :
        Output format: ``"parquet"`` (default) or ``"csv"``.
    n_steps :
        Number of simulation time steps to execute (must be ≥ 1).
    seed :
        Global random seed for reproducibility (default: 42).
    dt :
        Simulation time step in seconds (default: 60 s).
    extra_params :
        Optional dictionary of parameter overrides merged on top of
        :data:`~sim.v5.engine.DEFAULT_PARAMS`.
    """

    def __init__(
        self,
        output_path: str | Path,
        fmt: Literal["parquet", "csv"] = "parquet",
        n_steps: int = 10,
        seed: int = 42,
        dt: float = 60.0,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        if n_steps <= 0:
            raise ValueError(f"n_steps must be a positive integer, got {n_steps!r}")
        self._output_path = Path(output_path)
        self._fmt = fmt
        self._n_steps = n_steps
        self._seed = seed
        self._dt = float(dt)
        self._extra_params = extra_params or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full simulation and write results to disk."""
        rng = random.Random(self._seed)

        # Load V5 specification
        registry = load_spec()

        # Build merged parameter set
        params = dict(DEFAULT_PARAMS)
        params.update(self._extra_params)
        params["dt"] = self._dt

        # Build engine
        engine = V5SimulationEngine(registry, params=params, dt=self._dt, rng=rng)
        engine.initialize(params)

        # Output writer
        writer = Writer(
            self._output_path,
            fmt=self._fmt,
            batch_size=1000,
            columns=V5_OUTPUT_COLUMNS,
        )

        try:
            for _ in range(self._n_steps):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    engine.step()
                row = self._collect_row(engine)
                writer.write_row(row)
        finally:
            writer.close()

        # Print a brief summary after completion
        print(engine.run_summary())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_row(self, engine: V5SimulationEngine) -> Dict[str, Any]:
        """Build one output row from the engine's current step state.

        All columns defined in :data:`~sim.v5.output_schema.V5_OUTPUT_COLUMNS`
        are included; variables not yet computed for this step are represented
        as ``float('nan')``.
        """
        current = engine.store.current
        row: Dict[str, Any] = {"t": engine.step_count}
        for col in V5_OUTPUT_COLUMNS:
            val = current.get(col)
            row[col] = float(val) if val is not None and not _is_none_or_nan(val) else float("nan")
        return row


def _is_none_or_nan(v: Any) -> bool:
    """Return True if *v* is ``None`` or ``float('nan')``."""
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False
