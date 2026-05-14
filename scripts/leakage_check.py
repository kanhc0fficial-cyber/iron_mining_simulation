#!/usr/bin/env python3
"""Run calibration/leakage diagnostics on an exported simulation file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.validation.leakage import build_leakage_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check DCS leakage against final concentrate labels.")
    parser.add_argument("--input", required=True, help="Simulation output file (.parquet or .csv).")
    parser.add_argument("--target", default="y_fx_xin1", help="Target column to inspect.")
    parser.add_argument("--lags", default="0,1,5,10,30,60", help="Comma-separated lag list.")
    parser.add_argument("--window-lags", default="0,5,10,30,60", help="Comma-separated window lag list.")
    parser.add_argument("--top", type=int, default=12, help="Number of rows to print per table.")
    parser.add_argument("--max-single-r2", type=float, default=0.95, help="Suspicious single-proxy R2 threshold.")
    parser.add_argument("--min-window-gain", type=float, default=None, help="Optional minimum window-vs-instant R2 gain.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if thresholds fail.")
    return parser.parse_args()


def _parse_lags(text: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in text.split(",") if part.strip())


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def main() -> None:
    args = parse_args()
    df = _read_frame(Path(args.input))
    summary = build_leakage_summary(
        df,
        target=args.target,
        lags=_parse_lags(args.lags),
        window_lags=_parse_lags(args.window_lags),
        top_n=args.top,
    )
    print(summary.to_text(top_n=args.top))

    failed = False
    if summary.single_proxy_suspicious(args.max_single_r2):
        print(
            f"[FAIL] single-feature R2 {summary.max_single_feature_r2:.4f} "
            f">= {args.max_single_r2:.4f}",
            file=sys.stderr,
        )
        failed = True
    if args.min_window_gain is not None and summary.window_gain < args.min_window_gain:
        print(
            f"[FAIL] window gain {summary.window_gain:.4f} "
            f"< {args.min_window_gain:.4f}",
            file=sys.stderr,
        )
        failed = True
    if args.check and failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

