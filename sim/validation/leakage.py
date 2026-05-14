"""Calibration and leakage diagnostics for simulation outputs.

The functions here are deliberately read-only. They inspect exported data and
never feed results back into the process mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from sim.output.schema import PROCESS_LAB_COLUMNS, STEP1_COLUMNS, STEP2_COLUMNS, STEP3_COLUMNS


TARGET_COLUMNS = {"y_fx_xin1", "y_fx_xin2"}


@dataclass(frozen=True)
class LeakageSummary:
    target: str
    top_instant_corr: pd.DataFrame
    top_lag_corr: pd.DataFrame
    top_univariate_r2: pd.DataFrame
    instant_multivariate_r2: float
    window_multivariate_r2: float
    lab_target_corr: pd.DataFrame
    selected_features: list[str]

    @property
    def max_single_feature_r2(self) -> float:
        if self.top_univariate_r2.empty:
            return float("nan")
        return float(self.top_univariate_r2["r2"].iloc[0])

    @property
    def window_gain(self) -> float:
        return float(self.window_multivariate_r2 - self.instant_multivariate_r2)

    def single_proxy_suspicious(self, threshold: float = 0.95) -> bool:
        r2 = self.max_single_feature_r2
        return bool(np.isfinite(r2) and r2 >= threshold)

    def to_text(self, top_n: int = 8) -> str:
        lines = [
            f"target: {self.target}",
            f"max single-feature R2: {self.max_single_feature_r2:.4f}",
            f"instant multivariate R2: {self.instant_multivariate_r2:.4f}",
            f"window multivariate R2: {self.window_multivariate_r2:.4f}",
            f"window gain: {self.window_gain:.4f}",
            "",
            "top instant correlations:",
            _frame_to_text(self.top_instant_corr.head(top_n), ["feature", "corr", "n"]),
            "",
            "top lagged correlations:",
            _frame_to_text(self.top_lag_corr.head(top_n), ["feature", "lag", "corr", "n"]),
            "",
            "top univariate R2:",
            _frame_to_text(self.top_univariate_r2.head(top_n), ["feature", "lag", "r2", "n"]),
        ]
        if not self.lab_target_corr.empty:
            lines.extend([
                "",
                "lab-target correlations:",
                _frame_to_text(self.lab_target_corr.head(top_n), ["feature", "corr", "n"]),
            ])
        return "\n".join(lines)


def default_dcs_columns(df: pd.DataFrame | None = None) -> list[str]:
    """Return DCS columns that are allowed for leakage checks.

    `lab_*`, targets, and hidden `_x_*` values are intentionally excluded.
    """
    schema_cols = [*STEP1_COLUMNS, *STEP2_COLUMNS, *STEP3_COLUMNS]
    seen: set[str] = set()
    cols: list[str] = []
    available = set(df.columns) if df is not None else None
    for col in schema_cols:
        if col in seen:
            continue
        seen.add(col)
        if col in TARGET_COLUMNS or col.startswith("lab_") or col.startswith("_x_"):
            continue
        if col in PROCESS_LAB_COLUMNS:
            continue
        if available is not None and col not in available:
            continue
        cols.append(col)
    return cols


def default_lab_columns(df: pd.DataFrame) -> list[str]:
    return [
        c for c in df.columns
        if c.startswith("lab_") and c not in TARGET_COLUMNS
    ]


def pearson_corr(x: Sequence[float], y: Sequence[float], min_samples: int = 8) -> tuple[float, int]:
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(y, dtype=float)
    mask = np.isfinite(xs) & np.isfinite(ys)
    n = int(mask.sum())
    if n < min_samples:
        return float("nan"), n
    xs = xs[mask]
    ys = ys[mask]
    if float(np.std(xs)) <= 1e-12 or float(np.std(ys)) <= 1e-12:
        return float("nan"), n
    return float(np.corrcoef(xs, ys)[0, 1]), n


def lagged_correlations(
    df: pd.DataFrame,
    target: str,
    feature_cols: Sequence[str],
    lags: Sequence[int] = (0, 1, 5, 10, 30, 60),
    min_samples: int = 30,
) -> pd.DataFrame:
    """Compute corr(feature(t-lag), target(t)) for candidate DCS columns."""
    if target not in df.columns:
        raise KeyError(f"target column not found: {target}")
    rows: list[dict[str, float | int | str]] = []
    y = df[target].to_numpy(dtype=float)
    for feature in feature_cols:
        if feature not in df.columns:
            continue
        x = df[feature].to_numpy(dtype=float)
        for lag in lags:
            if lag < 0:
                raise ValueError("lags must be non-negative")
            if lag == 0:
                x_lag = x
                y_aligned = y
            elif lag >= len(df):
                continue
            else:
                x_lag = x[:-lag]
                y_aligned = y[lag:]
            corr, n = pearson_corr(x_lag, y_aligned, min_samples=min_samples)
            rows.append({
                "feature": feature,
                "lag": int(lag),
                "corr": corr,
                "abs_corr": abs(corr) if np.isfinite(corr) else float("nan"),
                "r2": corr * corr if np.isfinite(corr) else float("nan"),
                "n": n,
            })
    out = pd.DataFrame(rows, columns=["feature", "lag", "corr", "abs_corr", "r2", "n"])
    if out.empty:
        return out
    return out.sort_values(["abs_corr", "n"], ascending=[False, False]).reset_index(drop=True)


def build_lagged_matrix(
    df: pd.DataFrame,
    target: str,
    feature_cols: Sequence[str],
    lags: Sequence[int],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    pieces: list[pd.DataFrame] = []
    names: list[str] = []
    for lag in lags:
        if lag < 0:
            raise ValueError("lags must be non-negative")
        shifted = df[list(feature_cols)].shift(lag)
        shifted.columns = [f"{c}__lag{lag}" for c in shifted.columns]
        pieces.append(shifted)
        names.extend(list(shifted.columns))
    frame = pd.concat([*pieces, df[[target]]], axis=1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    if frame.empty:
        return np.empty((0, len(names))), np.empty((0,)), names
    return frame[names].to_numpy(dtype=float), frame[target].to_numpy(dtype=float), names


def time_split_linear_r2(
    df: pd.DataFrame,
    target: str,
    feature_cols: Sequence[str],
    lags: Sequence[int] = (0,),
    train_fraction: float = 0.7,
    ridge_alpha: float = 1e-6,
    min_samples: int = 80,
) -> float:
    """Fit a time-split ridge model and return test-set R2."""
    feature_cols = [c for c in feature_cols if c in df.columns]
    if not feature_cols:
        return float("nan")
    X, y, _ = build_lagged_matrix(df, target, feature_cols, lags)
    n = len(y)
    if n < min_samples:
        return float("nan")
    split = int(np.clip(round(n * train_fraction), 1, n - 1))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    x_mean = X_train.mean(axis=0)
    x_std = X_train.std(axis=0)
    keep = x_std > 1e-12
    if not np.any(keep):
        return float("nan")
    X_train = (X_train[:, keep] - x_mean[keep]) / x_std[keep]
    X_test = (X_test[:, keep] - x_mean[keep]) / x_std[keep]
    y_mean = float(y_train.mean())
    yc = y_train - y_mean

    xtx = X_train.T @ X_train
    reg = ridge_alpha * np.eye(xtx.shape[0])
    beta = np.linalg.solve(xtx + reg, X_train.T @ yc)
    pred = X_test @ beta + y_mean
    return r2_score(y_test, pred)


def r2_score(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(yt) & np.isfinite(yp)
    if int(mask.sum()) < 2:
        return float("nan")
    yt = yt[mask]
    yp = yp[mask]
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    if ss_tot <= 1e-12:
        return float("nan")
    ss_res = float(np.sum((yt - yp) ** 2))
    return 1.0 - ss_res / ss_tot


def build_leakage_summary(
    df: pd.DataFrame,
    target: str = "y_fx_xin1",
    feature_cols: Sequence[str] | None = None,
    lags: Sequence[int] = (0, 1, 5, 10, 30, 60),
    window_lags: Sequence[int] = (0, 5, 10, 30, 60),
    top_n: int = 20,
    max_window_features: int = 25,
    min_samples: int = 80,
) -> LeakageSummary:
    feature_cols = list(feature_cols) if feature_cols is not None else default_dcs_columns(df)
    lag_corr = lagged_correlations(df, target, feature_cols, lags=lags, min_samples=min_samples)
    instant = lag_corr[lag_corr["lag"] == 0].copy() if not lag_corr.empty else lag_corr
    top_univar = lag_corr.sort_values(["r2", "n"], ascending=[False, False]).reset_index(drop=True)

    selected: list[str] = []
    for feature in lag_corr["feature"].tolist() if not lag_corr.empty else []:
        if feature not in selected:
            selected.append(feature)
        if len(selected) >= max_window_features:
            break
    instant_r2 = time_split_linear_r2(
        df, target, selected, lags=(0,), min_samples=min_samples
    )
    window_r2 = time_split_linear_r2(
        df, target, selected, lags=window_lags, min_samples=min_samples
    )

    lab_corr = lagged_correlations(
        df,
        target,
        default_lab_columns(df),
        lags=(0,),
        min_samples=max(8, min_samples // 4),
    )
    return LeakageSummary(
        target=target,
        top_instant_corr=instant.head(top_n).reset_index(drop=True),
        top_lag_corr=lag_corr.head(top_n).reset_index(drop=True),
        top_univariate_r2=top_univar.head(top_n).reset_index(drop=True),
        instant_multivariate_r2=float(instant_r2),
        window_multivariate_r2=float(window_r2),
        lab_target_corr=lab_corr.head(top_n).reset_index(drop=True),
        selected_features=selected,
    )


def estimate_response_lag(
    cause: Sequence[float],
    effect: Sequence[float],
    lags: Sequence[int],
    min_samples: int = 30,
) -> dict[str, float | int]:
    """Return the lag where cause(t-lag) best correlates with effect(t)."""
    rows = []
    cause_arr = np.asarray(cause, dtype=float)
    effect_arr = np.asarray(effect, dtype=float)
    for lag in lags:
        if lag < 0:
            raise ValueError("lags must be non-negative")
        if lag == 0:
            x = cause_arr
            y = effect_arr
        elif lag >= len(cause_arr):
            continue
        else:
            x = cause_arr[:-lag]
            y = effect_arr[lag:]
        corr, n = pearson_corr(x, y, min_samples=min_samples)
        rows.append((lag, corr, abs(corr) if np.isfinite(corr) else float("nan"), n))
    if not rows:
        return {"lag": -1, "corr": float("nan"), "abs_corr": float("nan"), "n": 0}
    best = max(rows, key=lambda row: (-1 if not np.isfinite(row[2]) else row[2], row[3]))
    return {"lag": int(best[0]), "corr": float(best[1]), "abs_corr": float(best[2]), "n": int(best[3])}


def _frame_to_text(df: pd.DataFrame, columns: Sequence[str]) -> str:
    if df.empty:
        return "  <empty>"
    use_cols = [c for c in columns if c in df.columns]
    return df[use_cols].to_string(index=False)

