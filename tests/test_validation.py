from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.validation.leakage import (
    build_leakage_summary,
    default_dcs_columns,
    estimate_response_lag,
    time_split_linear_r2,
)


def test_default_dcs_columns_excludes_targets_labs_and_hidden() -> None:
    df = pd.DataFrame({
        "agg_mag_excit_voltage": [1.0, 2.0],
        "fx_s1_ph": [9.5, 9.6],
        "y_fx_xin1": [0.66, 0.67],
        "lab_1_eryi_tfe": [np.nan, 31.2],
        "_x_flo_final_conc_s1_tfe": [0.66, 0.67],
    })
    cols = default_dcs_columns(df)

    assert "agg_mag_excit_voltage" in cols
    assert "fx_s1_ph" in cols
    assert "y_fx_xin1" not in cols
    assert "lab_1_eryi_tfe" not in cols
    assert "_x_flo_final_conc_s1_tfe" not in cols


def test_estimate_response_lag_finds_delayed_effect() -> None:
    rng = np.random.default_rng(123)
    n = 400
    cause = rng.normal(size=n)
    effect = np.zeros(n)
    effect[8:] = 0.8 * cause[:-8] + rng.normal(0.0, 0.05, size=n - 8)

    result = estimate_response_lag(cause, effect, lags=range(0, 20), min_samples=80)

    assert result["lag"] == 8
    assert result["corr"] > 0.95


def test_time_window_model_beats_single_time_for_delayed_synthetic() -> None:
    rng = np.random.default_rng(456)
    n = 500
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = np.zeros(n)
    y[12:] += 0.7 * x1[:-12]
    y[24:] += 0.4 * x2[:-24]
    y += rng.normal(0.0, 0.05, size=n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})

    instant_r2 = time_split_linear_r2(df, "y", ["x1", "x2"], lags=(0,), min_samples=120)
    window_r2 = time_split_linear_r2(
        df, "y", ["x1", "x2"], lags=(0, 12, 24), min_samples=120
    )

    assert instant_r2 < 0.10
    assert window_r2 > 0.80


def test_leakage_summary_flags_direct_single_proxy() -> None:
    rng = np.random.default_rng(789)
    n = 300
    target = rng.normal(size=n)
    df = pd.DataFrame({
        "proxy": target + rng.normal(0.0, 0.01, size=n),
        "weak_feature": rng.normal(size=n),
        "y": target,
    })

    summary = build_leakage_summary(
        df,
        target="y",
        feature_cols=["proxy", "weak_feature"],
        lags=(0, 1, 5),
        window_lags=(0, 1, 5),
        min_samples=80,
    )

    assert summary.top_univariate_r2.iloc[0]["feature"] == "proxy"
    assert summary.max_single_feature_r2 > 0.98
    assert summary.single_proxy_suspicious(threshold=0.95)

