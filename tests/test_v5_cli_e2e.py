"""End-to-end tests for the V5 CLI (PR-5).

Tests cover:
- CLI runs 10 steps via ``--engine v5``
- Output file is created
- Output has no all-NaN columns
- ``y_fx_xin*`` variables do not leak before the label stage
- DCS columns come from the DCS registry
- Lab columns are produced by the lab sampler (not raw external inputs)
"""
from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Repo root and output directory
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TMP_OUTPUT = _REPO_ROOT / "output" / "_test_v5_cli_e2e.parquet"

# Ensure the project root is on sys.path once at module level so that all
# tests can import ``sim.*`` without repeating this in every test method.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Helper: run CLI as subprocess
# ---------------------------------------------------------------------------


def _run_cli(*extra_args: str, output: Path = _TMP_OUTPUT) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_REPO_ROOT / "scripts" / "run_simulation.py"),
        "--engine", "v5",
        "--steps", "10",
        "--output", str(output),
        *extra_args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def output_df() -> pd.DataFrame:
    """Run the CLI once and return the resulting DataFrame."""
    _TMP_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result = _run_cli()
    assert result.returncode == 0, (
        f"CLI exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return pd.read_parquet(_TMP_OUTPUT)


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


class TestV5CLIE2E:
    """Smoke tests: CLI runs and produces valid output."""

    def test_cli_exits_zero(self) -> None:
        """CLI with --engine v5 --steps 10 must exit successfully."""
        result = _run_cli()
        assert result.returncode == 0, (
            f"CLI failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_output_file_exists(self, output_df: pd.DataFrame) -> None:
        """Output parquet file must be created."""
        assert _TMP_OUTPUT.exists(), f"Output file not found: {_TMP_OUTPUT}"

    def test_output_has_10_rows(self, output_df: pd.DataFrame) -> None:
        """Output must contain exactly 10 rows (one per step)."""
        assert len(output_df) == 10, f"Expected 10 rows, got {len(output_df)}"

    def test_output_has_timestamp_column(self, output_df: pd.DataFrame) -> None:
        """Output must include a 't' (step) column."""
        assert "t" in output_df.columns, "Column 't' missing from output"

    def test_timestamp_column_is_sequential(self, output_df: pd.DataFrame) -> None:
        """'t' values must be monotonically increasing integers."""
        t_vals = output_df["t"].tolist()
        assert t_vals == sorted(t_vals), "'t' column is not monotonically increasing"
        assert all(isinstance(v, (int, float)) for v in t_vals), "'t' column contains non-numeric values"


# ---------------------------------------------------------------------------
# No all-NaN columns
# ---------------------------------------------------------------------------


class TestV5OutputQuality:
    """Output columns must not be entirely NaN."""

    def test_no_all_nan_columns(self, output_df: pd.DataFrame) -> None:
        """Every data column must have at least one non-NaN value."""
        bad = [
            col for col in output_df.columns
            if col != "t" and output_df[col].isna().all()
        ]
        assert not bad, f"All-NaN columns: {bad}"

    def test_no_negative_dcs_magnitudes(self, output_df: pd.DataFrame) -> None:
        """Physical magnitude DCS columns must be non-negative."""
        from sim.v5.output_schema import _MAG_DCS, _TM_DCS

        # Only check known DCS columns from the V5 output schema
        dcs_cols = _MAG_DCS + _TM_DCS
        non_negative_cols = [
            c for c in dcs_cols
            if c in output_df.columns and any(
                kw in c
                for kw in ("_current", "_temp", "_flow", "_freq", "_pressure", "_level")
            )
        ]
        for col in non_negative_cols:
            series = output_df[col].dropna()
            assert (series >= 0).all(), f"Column '{col}' has negative values: {series[series < 0].tolist()}"


# ---------------------------------------------------------------------------
# y_fx_xin* leakage guard — must NOT appear before label stage
# ---------------------------------------------------------------------------


class TestV5LabelLeakageGuard:
    """y_fx_xin* variables must only be produced in the label stage."""

    def test_y_fx_xin_columns_in_output(self, output_df: pd.DataFrame) -> None:
        """Output must contain y_fx_xin_s and y_fx_xin_s_true."""
        assert "y_fx_xin_s" in output_df.columns, "'y_fx_xin_s' missing from output"
        assert "y_fx_xin_s_true" in output_df.columns, "'y_fx_xin_s_true' missing from output"

    def test_y_fx_xin_not_in_pre_label_stages(self) -> None:
        """y_fx_xin* must not be computed in boundary/magnetic/tower_mill/flotation stages."""
        from sim.v5.spec_loader import load_spec
        from sim.v5.engine import V5SimulationEngine, DEFAULT_PARAMS, LABEL_ONLY_LHS

        registry = load_spec()
        engine = V5SimulationEngine(registry, params=DEFAULT_PARAMS)
        engine.initialize(DEFAULT_PARAMS)

        pre_label_stages = ["boundary", "magnetic", "tower_mill", "flotation", "dcs", "lab"]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            engine.step()

        for stage in pre_label_stages:
            outputs = engine.stage_outputs(stage)
            leaked = LABEL_ONLY_LHS & outputs
            assert not leaked, (
                f"Stage '{stage}' produced label-only variables: {leaked}"
            )

    def test_y_fx_xin_produced_in_label_stage(self) -> None:
        """y_fx_xin_s and y_fx_xin_s_true must appear in label stage outputs."""
        from sim.v5.spec_loader import load_spec
        from sim.v5.engine import V5SimulationEngine, DEFAULT_PARAMS, LABEL_ONLY_LHS

        registry = load_spec()
        engine = V5SimulationEngine(registry, params=DEFAULT_PARAMS)
        engine.initialize(DEFAULT_PARAMS)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            engine.run(3)

        label_outputs = engine.stage_outputs("label")
        for var in LABEL_ONLY_LHS:
            assert var in label_outputs, (
                f"'{var}' not produced in label stage. label_outputs={label_outputs}"
            )


# ---------------------------------------------------------------------------
# DCS columns come from DCS registry
# ---------------------------------------------------------------------------


class TestV5DCSSchemaCoverage:
    """DCS columns in output must be a subset of DCS registry names."""

    def test_dcs_columns_from_registry(self, output_df: pd.DataFrame) -> None:
        """Every DCS column (agg_* / fx_*) in the output must resolve in the DCS registry."""
        from sim.v5.spec_loader import load_spec
        from sim.v5.dcs_registry import DCSOutputRegistry
        from sim.v5.output_schema import V5_OUTPUT_COLUMNS

        registry = load_spec()
        dcs_reg = DCSOutputRegistry(registry)

        # Columns in output that look like DCS signals
        dcs_like = [
            col for col in V5_OUTPUT_COLUMNS
            if col.startswith("agg_") or col.startswith("fx_")
        ]
        unregistered = [
            col for col in dcs_like
            if dcs_reg.get(col) is None
        ]
        assert not unregistered, (
            f"Output contains DCS columns not in registry: {unregistered}"
        )

    def test_output_dcs_columns_present(self, output_df: pd.DataFrame) -> None:
        """Output file must contain at least the expected DCS column names."""
        from sim.v5.output_schema import _MAG_DCS, _TM_DCS

        expected_dcs = _MAG_DCS + _TM_DCS
        missing = [c for c in expected_dcs if c not in output_df.columns]
        assert not missing, f"DCS columns missing from output: {missing}"


# ---------------------------------------------------------------------------
# Lab columns produced by lab sampler
# ---------------------------------------------------------------------------


class TestV5LabColumns:
    """Lab columns must be present and produced by the lab sampler formula."""

    def test_lab_columns_in_output(self, output_df: pd.DataFrame) -> None:
        """Output must include lab_tm_overflow_tfe and lab_mag_mixed_conc_tfe."""
        from sim.v5.output_schema import _LAB_COLS

        missing = [c for c in _LAB_COLS if c not in output_df.columns]
        assert not missing, f"Lab columns missing from output: {missing}"

    def test_lab_columns_not_all_nan(self, output_df: pd.DataFrame) -> None:
        """Lab columns must have at least one non-NaN value."""
        from sim.v5.output_schema import _LAB_COLS

        for col in _LAB_COLS:
            assert not output_df[col].isna().all(), f"Lab column '{col}' is all-NaN"

    def test_lab_columns_from_lab_sampler_formula(self) -> None:
        """lab_tm_overflow_tfe must be produced by lab_sample_template, not a raw external input."""
        from sim.v5.spec_loader import load_spec
        from sim.v5.external_input_registry import ExternalInputRegistry

        registry = load_spec()
        ext_reg = ExternalInputRegistry(registry)

        # These must NOT be raw external inputs — they are generated by lab_sample_template
        lab_generated = ["lab_tm_overflow_tfe", "lab_mag_mixed_conc_tfe"]
        ext_names = ext_reg.all_registered()
        for var in lab_generated:
            assert var not in ext_names, (
                f"'{var}' is incorrectly registered as an external input. "
                "It must be generated by lab_sample_template."
            )

    def test_lab_columns_have_realistic_values(self, output_df: pd.DataFrame) -> None:
        """lab TFe values must be in a physically plausible range (30–80 %)."""
        for col in ["lab_tm_overflow_tfe", "lab_mag_mixed_conc_tfe"]:
            series = output_df[col].dropna()
            assert (series >= 30).all() and (series <= 80).all(), (
                f"'{col}' contains values outside [30, 80]: {series.tolist()}"
            )


# ---------------------------------------------------------------------------
# Output schema stability
# ---------------------------------------------------------------------------


class TestV5OutputSchemaStability:
    """Output schema must be deterministic and stable."""

    def test_output_columns_match_schema(self, output_df: pd.DataFrame) -> None:
        """Output parquet columns must match V5_OUTPUT_COLUMNS (plus 't')."""
        from sim.v5.output_schema import V5_OUTPUT_COLUMNS

        expected = ["t"] + V5_OUTPUT_COLUMNS
        assert list(output_df.columns) == expected, (
            f"Column mismatch.\n"
            f"  expected : {expected}\n"
            f"  actual   : {list(output_df.columns)}"
        )

    def test_two_runs_same_seed_are_identical(self) -> None:
        """Two runs with the same seed must produce identical output."""
        out1 = _REPO_ROOT / "output" / "_test_v5_seed_a.parquet"
        out2 = _REPO_ROOT / "output" / "_test_v5_seed_b.parquet"

        _run_cli("--seed", "99", output=out1)
        _run_cli("--seed", "99", output=out2)

        df1 = pd.read_parquet(out1)
        df2 = pd.read_parquet(out2)
        pd.testing.assert_frame_equal(df1, df2, check_exact=False)

    def test_different_seeds_may_differ(self) -> None:
        """Two runs with different seeds should produce different output (probabilistic guard)."""
        out1 = _REPO_ROOT / "output" / "_test_v5_diff_a.parquet"
        out2 = _REPO_ROOT / "output" / "_test_v5_diff_b.parquet"

        _run_cli("--seed", "1", output=out1)
        _run_cli("--seed", "2", output=out2)

        df1 = pd.read_parquet(out1)
        df2 = pd.read_parquet(out2)
        # At least some columns should differ between seeds
        any_diff = any(
            not df1[c].equals(df2[c]) for c in df1.columns if c != "t"
        )
        assert any_diff, "Runs with different seeds produced identical output — RNG not wired?"
