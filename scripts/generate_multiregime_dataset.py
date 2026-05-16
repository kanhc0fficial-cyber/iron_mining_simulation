#!/usr/bin/env python3
"""Generate multi-regime simulation datasets for OOD stability experiments."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_simulation import apply_data_quality_preset, apply_dcs_coupling_preset
from sim.config import (
    BallMillConfig,
    BoundaryConfig,
    DisturbanceConfig,
    FlotationConfig,
    MagSepConfig,
    ProcessLabConfig,
    SimConfig,
    TowerMillConfig,
)
from sim.simulator import Simulator


@dataclass(frozen=True)
class RegimeSpec:
    name: str
    feed_band: str
    ore_grade_band: str
    size_band: str
    shift_group: str
    seed_offset: int
    line_solid_nom_tph: float
    tfe_mean: float
    tfe_block_sigma: float
    f200_mean: float
    wi_mean: float
    clay_mean: float
    line_conc_mean: float
    water_pressure_mean: float
    collector_scale: float
    air_scale: float
    pump_scale: float


REGIMES: tuple[RegimeSpec, ...] = (
    RegimeSpec(
        name="R0_nominal_stable",
        feed_band="mid",
        ore_grade_band="mid",
        size_band="normal",
        shift_group="day",
        seed_offset=0,
        line_solid_nom_tph=265.0,
        tfe_mean=0.3149,
        tfe_block_sigma=0.009,
        f200_mean=0.770,
        wi_mean=1.00,
        clay_mean=0.080,
        line_conc_mean=0.390,
        water_pressure_mean=0.400,
        collector_scale=1.00,
        air_scale=1.00,
        pump_scale=1.00,
    ),
    RegimeSpec(
        name="R1_high_feed_coarse",
        feed_band="high",
        ore_grade_band="mid",
        size_band="coarse",
        shift_group="night",
        seed_offset=101,
        line_solid_nom_tph=286.0,
        tfe_mean=0.3130,
        tfe_block_sigma=0.010,
        f200_mean=0.748,
        wi_mean=1.12,
        clay_mean=0.105,
        line_conc_mean=0.405,
        water_pressure_mean=0.385,
        collector_scale=1.06,
        air_scale=1.10,
        pump_scale=1.08,
    ),
    RegimeSpec(
        name="R2_low_feed_fine_high_grade",
        feed_band="low",
        ore_grade_band="high",
        size_band="fine",
        shift_group="day",
        seed_offset=202,
        line_solid_nom_tph=244.0,
        tfe_mean=0.3260,
        tfe_block_sigma=0.007,
        f200_mean=0.812,
        wi_mean=0.92,
        clay_mean=0.055,
        line_conc_mean=0.374,
        water_pressure_mean=0.420,
        collector_scale=0.94,
        air_scale=0.92,
        pump_scale=0.94,
    ),
    RegimeSpec(
        name="R3_low_grade_carbonate",
        feed_band="mid",
        ore_grade_band="low",
        size_band="normal",
        shift_group="night",
        seed_offset=303,
        line_solid_nom_tph=264.0,
        tfe_mean=0.3030,
        tfe_block_sigma=0.011,
        f200_mean=0.768,
        wi_mean=1.04,
        clay_mean=0.125,
        line_conc_mean=0.392,
        water_pressure_mean=0.395,
        collector_scale=1.08,
        air_scale=1.02,
        pump_scale=1.02,
    ),
    RegimeSpec(
        name="R4_water_pressure_swing",
        feed_band="mid",
        ore_grade_band="mid",
        size_band="variable",
        shift_group="swing",
        seed_offset=404,
        line_solid_nom_tph=270.0,
        tfe_mean=0.3160,
        tfe_block_sigma=0.010,
        f200_mean=0.776,
        wi_mean=1.02,
        clay_mean=0.090,
        line_conc_mean=0.397,
        water_pressure_mean=0.360,
        collector_scale=1.02,
        air_scale=1.08,
        pump_scale=1.12,
    ),
    RegimeSpec(
        name="R5_hard_ore_high_clay",
        feed_band="high",
        ore_grade_band="low",
        size_band="coarse",
        shift_group="swing",
        seed_offset=505,
        line_solid_nom_tph=278.0,
        tfe_mean=0.3070,
        tfe_block_sigma=0.012,
        f200_mean=0.752,
        wi_mean=1.16,
        clay_mean=0.150,
        line_conc_mean=0.410,
        water_pressure_mean=0.375,
        collector_scale=1.16,
        air_scale=1.14,
        pump_scale=1.10,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a labeled multi-regime simulation dataset.")
    parser.add_argument("--output", default="output/multiregime_6x14400_seq_hybrid.parquet")
    parser.add_argument("--steps-per-regime", type=int, default=14_400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dcs-coupling",
        choices=[
            "baseline",
            "balanced",
            "upstream-visible",
            "seq-memory",
            "seq-upstream",
            "seq-hybrid",
            "tuned",
            "strong",
        ],
        default="seq-hybrid",
    )
    parser.add_argument(
        "--data-quality",
        choices=["normal", "clean", "very-clean"],
        default="normal",
    )
    parser.add_argument("--process-lab-interval-min", type=int, default=15)
    parser.add_argument("--process-lab-interval-max", type=int, default=30)
    parser.add_argument("--assay-interval-min", type=int, default=None)
    parser.add_argument("--assay-interval-max", type=int, default=None)
    parser.add_argument("--keep-segments", action="store_true")
    return parser.parse_args()


def _apply_regime(
    regime: RegimeSpec,
    boundary_cfg: BoundaryConfig,
    flo_cfg: FlotationConfig,
) -> None:
    boundary_cfg.line_solid_nom_tph = regime.line_solid_nom_tph
    boundary_cfg.line_solid_min_tph = max(regime.line_solid_nom_tph - 26.0, 180.0)
    boundary_cfg.line_solid_max_tph = regime.line_solid_nom_tph + 26.0
    boundary_cfg.tfe_mean = regime.tfe_mean
    boundary_cfg.tfe_block_sigma = regime.tfe_block_sigma
    boundary_cfg.tfe_min = max(regime.tfe_mean - 0.030, 0.270)
    boundary_cfg.tfe_max = min(regime.tfe_mean + 0.030, 0.360)
    boundary_cfg.f200_mean = regime.f200_mean
    boundary_cfg.wi_mean = regime.wi_mean
    boundary_cfg.clay_mean = regime.clay_mean
    boundary_cfg.line_conc_mean = regime.line_conc_mean
    boundary_cfg.line_conc_min = max(regime.line_conc_mean - 0.045, 0.32)
    boundary_cfg.line_conc_max = min(regime.line_conc_mean + 0.045, 0.46)
    boundary_cfg.water_pressure_mean = regime.water_pressure_mean
    boundary_cfg.water_pressure_min = max(regime.water_pressure_mean - 0.08, 0.25)
    boundary_cfg.water_pressure_max = min(regime.water_pressure_mean + 0.08, 0.52)

    flo_cfg.f_td_rough_nom *= regime.collector_scale
    flo_cfg.f_td_clean_nom *= regime.collector_scale
    flo_cfg.f_k6_rough_nom *= regime.collector_scale
    flo_cfg.f_naoh_nom *= max(0.90, min(1.12, regime.collector_scale))
    flo_cfg.Q_air_nom *= regime.air_scale
    flo_cfg.f_pump_flo_nom *= regime.pump_scale


def _soften_final_grade_ceiling_pressure(flo_cfg: FlotationConfig) -> None:
    """Keep multi-regime labels away from the hard 70% final-grade ceiling."""
    flo_cfg.flo_stage_gangue_rate_h = tuple(v * 0.92 for v in flo_cfg.flo_stage_gangue_rate_h)
    flo_cfg.flo_sil_float_mult *= 0.95
    flo_cfg.flo_carb_float_mult *= 0.95
    flo_cfg.flo_collector_gain *= 0.96
    flo_cfg.flo_air_gain *= 0.97


def _run_regime(
    regime: RegimeSpec,
    args: argparse.Namespace,
    segment_path: Path,
    regime_idx: int,
) -> pd.DataFrame:
    sim_cfg = SimConfig(seed=args.seed + regime.seed_offset, open_loop=True)
    dist_cfg = DisturbanceConfig()
    ball_cfg = BallMillConfig()
    mag_cfg = MagSepConfig()
    tm_cfg = TowerMillConfig()
    flo_cfg = FlotationConfig()
    lab_cfg = ProcessLabConfig()
    boundary_cfg = BoundaryConfig.from_legacy(dist_cfg, ball_cfg, dt=sim_cfg.dt)

    apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, args.dcs_coupling)
    apply_data_quality_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, lab_cfg, args.data_quality)
    _soften_final_grade_ceiling_pressure(flo_cfg)
    _apply_regime(regime, boundary_cfg, flo_cfg)

    lab_cfg.interval_min_steps = args.process_lab_interval_min
    lab_cfg.interval_max_steps = args.process_lab_interval_max
    if args.assay_interval_min is not None:
        flo_cfg.assay_interval_min = args.assay_interval_min
    if args.assay_interval_max is not None:
        flo_cfg.assay_interval_max = args.assay_interval_max

    sim = Simulator(
        sim_cfg=sim_cfg,
        dist_cfg=dist_cfg,
        ball_cfg=ball_cfg,
        mag_cfg=mag_cfg,
        boundary_cfg=boundary_cfg,
        tm_cfg=tm_cfg,
        flo_cfg=flo_cfg,
        lab_cfg=lab_cfg,
        output_path=segment_path,
        fmt="parquet",
    )
    sim.run_steps(args.steps_per_regime)
    df = pd.read_parquet(segment_path)
    df.insert(0, "global_t", df["t"] + regime_idx * args.steps_per_regime)
    df["regime_id"] = regime_idx
    df["regime_name"] = regime.name
    df["feed_rate_band"] = regime.feed_band
    df["ore_grade_band"] = regime.ore_grade_band
    df["size_band"] = regime.size_band
    df["shift_group"] = regime.shift_group
    df["batch_id"] = f"batch_{regime_idx:02d}"
    df["is_ood_holdout_suggested"] = regime_idx in {3, 5}
    return df


def main() -> None:
    args = parse_args()
    if args.steps_per_regime <= 0:
        raise ValueError("--steps-per-regime must be positive")
    if args.process_lab_interval_min <= 0 or args.process_lab_interval_max < args.process_lab_interval_min:
        raise ValueError("process lab interval must satisfy 0 < min <= max")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment_dir = output_path.parent / f".{output_path.stem}_segments"
    if segment_dir.exists():
        shutil.rmtree(segment_dir)
    segment_dir.mkdir(parents=True)

    t0 = time.perf_counter()
    frames: list[pd.DataFrame] = []
    for idx, regime in enumerate(REGIMES):
        segment_path = segment_dir / f"{idx:02d}_{regime.name}.parquet"
        print(f"[multi-regime] {idx + 1}/{len(REGIMES)} {regime.name} -> {segment_path}", flush=True)
        frames.append(_run_regime(regime, args, segment_path, idx))

    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(output_path, index=False)
    elapsed = time.perf_counter() - t0
    print(
        f"[multi-regime] done rows={len(out)} regimes={len(REGIMES)} "
        f"elapsed={elapsed:.2f}s output={output_path}",
        flush=True,
    )

    if not args.keep_segments:
        shutil.rmtree(segment_dir)


if __name__ == "__main__":
    main()
