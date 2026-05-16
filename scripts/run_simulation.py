#!/usr/bin/env python3
"""
仿真 CLI 入口。

用法示例：
  python scripts/run_simulation.py
  python scripts/run_simulation.py --steps 100 --format csv --output /tmp/out.csv
  python scripts/run_simulation.py --no-warmup --seed 123
  python scripts/run_simulation.py --engine v5 --steps 10 --output output/v5_quick.parquet
"""

from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

# 将项目根目录加入 sys.path，使 `sim` 包可直接导入
sys.path.insert(0, str(Path(__file__).parent.parent))

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


DCS_COUPLING_PRESETS = (
    "baseline",
    "balanced",
    "upstream-visible",
    "seq-memory",
    "seq-upstream",
    "seq-hybrid",
    "tuned",
    "strong",
)
DATA_QUALITY_PRESETS = ("normal", "clean", "very-clean")


def _scale_attrs(obj: object, names: tuple[str, ...], factor: float) -> None:
    for name in names:
        if hasattr(obj, name):
            setattr(obj, name, getattr(obj, name) * factor)


def apply_dcs_coupling_preset(
    boundary_cfg: BoundaryConfig,
    mag_cfg: MagSepConfig,
    tm_cfg: TowerMillConfig,
    flo_cfg: FlotationConfig,
    preset: str,
) -> None:
    """Tune observable DCS coupling without changing the simulator structure."""
    if preset == "baseline":
        return
    if preset not in DCS_COUPLING_PRESETS:
        raise ValueError(f"unknown DCS coupling preset: {preset!r}")

    if preset == "balanced":
        boundary_cfg.tfe_open_sigma_factor *= 1.08
        boundary_cfg.f200_wi_coeff *= 1.12
        boundary_cfg.f200_load_coeff *= 1.10
        boundary_cfg.f200_clay_coeff *= 1.10
        mag_cfg.k_mf *= 1.18
        mag_cfg.k_mm *= 1.20
        mag_cfg.k_pipe *= 1.12
        tm_cfg.k_ms *= 1.18
        tm_cfg.k_md *= 1.16
        tm_cfg.k_mrho *= 1.22
        tm_cfg.k_alpha_d *= 1.18
        tm_cfg.k_alpha_P *= 1.16
        tm_cfg.lib_class_fe_gain *= 1.15
        tm_cfg.lib_class_gangue_gain *= 1.15
        flo_cfg.flo_size_gain *= 1.12
        flo_cfg.flo_air_gain *= 1.08
        flo_cfg.flo_collector_gain *= 1.08
        return

    if preset == "upstream-visible":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "balanced")
        boundary_cfg.tfe_open_sigma_factor *= 1.08
        boundary_cfg.r_component_sigma *= 1.12
        boundary_cfg.f200_wi_coeff *= 1.10
        boundary_cfg.f200_clay_coeff *= 1.10
        mag_cfg.lambda_s *= 1.10
        mag_cfg.k_mf *= 1.12
        mag_cfg.k_mm *= 1.18
        mag_cfg.unit_cv_electrical *= 0.88
        mag_cfg.unit_cv_mechanical *= 0.88
        tm_cfg.k_ms *= 1.14
        tm_cfg.k_md *= 1.18
        tm_cfg.k_f325 *= 1.14
        tm_cfg.lib_class_fe_gain *= 1.18
        tm_cfg.lib_class_gangue_gain *= 1.18
        flo_cfg.flo_size_gain *= 1.18
        flo_cfg.flo_air_gain *= 1.04
        return

    if preset == "seq-memory":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "balanced")
        boundary_cfg.tau_blend_s *= 1.20
        tm_cfg.delay_steps = max(tm_cfg.delay_steps, 28)
        tm_cfg.tau_mill = max(tm_cfg.tau_mill, 12)
        flo_cfg.delay_steps_tm = max(flo_cfg.delay_steps_tm, 45)
        flo_cfg.tau_flo = max(flo_cfg.tau_flo, 1100.0)
        flo_cfg.tau_flo_pre_thickener = max(flo_cfg.tau_flo_pre_thickener, 4800.0)
        flo_cfg.phi_drug = min(0.997, max(flo_cfg.phi_drug, 0.994))
        flo_cfg.phi_Q_air_sp = min(0.9996, max(flo_cfg.phi_Q_air_sp, 0.9992))
        flo_cfg.phi_blower = min(0.996, max(flo_cfg.phi_blower, 0.993))
        return

    if preset == "seq-upstream":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "upstream-visible")
        tm_cfg.delay_steps = max(tm_cfg.delay_steps, 28)
        tm_cfg.tau_mill = max(tm_cfg.tau_mill, 12)
        flo_cfg.delay_steps_tm = max(flo_cfg.delay_steps_tm, 45)
        flo_cfg.tau_flo = max(flo_cfg.tau_flo, 1000.0)
        flo_cfg.flo_collector_gain *= 0.92
        flo_cfg.flo_air_gain *= 0.94
        return

    if preset == "seq-hybrid":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "seq-memory")
        boundary_cfg.tfe_open_sigma_factor *= 1.10
        boundary_cfg.f200_wi_coeff *= 1.12
        boundary_cfg.f200_clay_coeff *= 1.12
        mag_cfg.k_mf *= 1.10
        mag_cfg.k_mm *= 1.14
        tm_cfg.k_ms *= 1.12
        tm_cfg.k_md *= 1.14
        tm_cfg.k_f325 *= 1.10
        tm_cfg.lib_class_fe_gain *= 1.12
        tm_cfg.lib_class_gangue_gain *= 1.12
        flo_cfg.flo_size_gain *= 1.15
        flo_cfg.flo_collector_gain *= 1.02
        return

    if preset == "tuned":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "upstream-visible")
        flo_cfg.flo_collector_gain *= 1.15
        flo_cfg.flo_air_gain *= 1.10
        flo_cfg.flo_size_gain *= 1.12
        return

    if preset == "strong":
        apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, "upstream-visible")
        boundary_cfg.tfe_open_sigma_factor *= 1.20
        boundary_cfg.r_component_sigma *= 1.20
        tm_cfg.lib_class_fe_gain *= 1.25
        tm_cfg.lib_class_gangue_gain *= 1.25
        flo_cfg.flo_size_gain *= 1.25
        flo_cfg.flo_collector_gain *= 1.20
        flo_cfg.flo_air_gain *= 1.15


def apply_data_quality_preset(
    boundary_cfg: BoundaryConfig,
    mag_cfg: MagSepConfig,
    tm_cfg: TowerMillConfig,
    flo_cfg: FlotationConfig,
    lab_cfg: ProcessLabConfig,
    preset: str,
) -> None:
    """Scale simulator data-quality degradations while preserving dynamics."""
    if preset == "normal":
        return
    if preset not in DATA_QUALITY_PRESETS:
        raise ValueError(f"unknown data quality preset: {preset!r}")

    factor = 0.55 if preset == "clean" else 0.30
    fault_factor = 0.40 if preset == "clean" else 0.15
    cv_factor = 0.65 if preset == "clean" else 0.40

    _scale_attrs(
        boundary_cfg,
        (
            "lab_sigma_tfe_pct",
            "lab_sigma_f200_pct",
            "line_flow_common_sigma",
            "line_flow_ind_sigma",
            "line_conc_sigma",
            "f200_sigma",
            "water_pressure_sigma",
        ),
        factor,
    )
    _scale_attrs(
        mag_cfg,
        (
            "sigma_V_exc",
            "sigma_I_exc",
            "sigma_T_coil",
            "sigma_b_level",
            "sigma_L_level",
            "sigma_blow",
            "sigma_pul",
            "sigma_ring",
            "sigma_I_motor",
            "sigma_Vgrid",
            "sigma_V_motor",
            "sigma_P_flush",
        ),
        factor,
    )
    _scale_attrs(mag_cfg, ("unit_cv_electrical", "unit_cv_mechanical"), cv_factor)
    _scale_attrs(
        tm_cfg,
        (
            "sigma_b_pool",
            "sigma_L_pool",
            "sigma_eta_f",
            "sigma_I_pump",
            "sigma_Q_pump",
            "sigma_alpha",
            "sigma_Q_feed",
            "sigma_P_mech",
            "sigma_f325",
            "sigma_I_motor_tm",
            "sigma_u_sand_fb",
            "sigma_Q_sand_water",
            "sigma_b1",
            "sigma_b2",
            "sigma_sA",
            "sigma_AB",
            "sigma_red",
            "sigma_red_out",
            "sigma_L_ov",
            "sigma_I_ov",
        ),
        factor,
    )
    _scale_attrs(tm_cfg, ("train_cv_flow", "train_cv_current", "train_cv_level"), cv_factor)
    _scale_attrs(
        flo_cfg,
        (
            "sigma_NT_I",
            "sigma_NT_rho",
            "sigma_pH",
            "sigma_u_lv",
            "sigma_h_froth",
            "sigma_Q_air",
            "sigma_Q_air_sp",
            "sigma_bv",
            "sigma_I_FXJ",
            "sigma_drug_f",
            "sigma_drug_I",
            "sigma_T_tk",
            "sigma_TV",
            "sigma_f_pump_flo",
            "sigma_I_pool",
            "sigma_L_pool_flo",
            "sigma_blower",
            "sigma_P_AH",
            "sigma_Q_ft",
            "sigma_L_k6",
            "sigma_lab",
        ),
        factor,
    )
    _scale_attrs(
        lab_cfg,
        (
            "sigma_tfe_pct",
            "sigma_f325_pct",
            "sigma_conc_pct",
            "sigma_yield_pct",
            "sigma_recovery_pct",
        ),
        factor,
    )
    _scale_attrs(flo_cfg, ("p_fault_froth",), fault_factor)
    _scale_attrs(tm_cfg, ("p_fault_bearing", "p_fault_stator"), fault_factor)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="东鞍山选矿DCS仿真系统")
    parser.add_argument(
        "--engine", choices=["legacy", "v5"], default="legacy",
        help="仿真后端（默认：legacy；v5 使用 V5 规格引擎）",
    )
    parser.add_argument(
        "--steps", type=int, default=None,
        help="仿真步数（默认：SimConfig.n_steps = 43200；v5 引擎默认 43200）",
    )
    parser.add_argument(
        "--output", type=str, default="output/simulation.parquet",
        help="输出文件路径（默认：output/simulation.parquet）",
    )
    parser.add_argument(
        "--format", choices=["parquet", "csv"], default="parquet",
        help="输出格式（默认：parquet）",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="全局随机种子（默认：42）",
    )
    parser.add_argument(
        "--no-warmup", action="store_true",
        help="跳过预热阶段（仅 legacy 引擎）",
    )
    parser.add_argument(
        "--open-loop", action="store_true",
        help="开环激励模式（PRBS 加药 + 扩大扰动方差；仅 legacy 引擎）",
    )
    parser.add_argument(
        "--assay-interval-min", type=int, default=None,
        help="minimum sample interval in simulation steps; overrides FlotationConfig.assay_interval_min",
    )
    parser.add_argument(
        "--assay-interval-max", type=int, default=None,
        help="maximum sample interval in simulation steps; overrides FlotationConfig.assay_interval_max",
    )
    parser.add_argument(
        "--process-lab-interval-min", type=int, default=None,
        help="minimum upstream process-lab interval in simulation steps",
    )
    parser.add_argument(
        "--process-lab-interval-max", type=int, default=None,
        help="maximum upstream process-lab interval in simulation steps",
    )
    parser.add_argument(
        "--dcs-coupling",
        choices=DCS_COUPLING_PRESETS,
        default="baseline",
        help="parameter preset for DCS-to-state and dynamic coupling",
    )
    parser.add_argument(
        "--data-quality",
        choices=DATA_QUALITY_PRESETS,
        default="normal",
        help="parameter preset for sensor/lab/fault noise quality",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # -----------------------------------------------------------------------
    # V5 engine backend
    # -----------------------------------------------------------------------
    if args.engine == "v5":
        from sim.v5.v5_runner import V5Runner

        n_steps = args.steps if args.steps is not None else 43200
        if n_steps <= 0:
            raise ValueError(f"--steps 必须是正整数，得到 {n_steps!r}")

        print(f"[仿真 V5] 开始仿真 {n_steps} 步 ...", flush=True)
        t0 = time.perf_counter()

        runner = V5Runner(
            output_path=args.output,
            fmt=args.format,
            n_steps=n_steps,
            seed=args.seed,
        )
        runner.run()

        elapsed = time.perf_counter() - t0
        print(f"[仿真 V5] 完成！耗时 {elapsed:.2f}s，输出 → {args.output}")
        return

    # -----------------------------------------------------------------------
    # Legacy engine backend (default)
    # -----------------------------------------------------------------------
    sim_cfg = SimConfig(seed=args.seed, open_loop=args.open_loop)
    dist_cfg = DisturbanceConfig()
    ball_cfg = BallMillConfig()
    mag_cfg = MagSepConfig()
    tm_cfg = TowerMillConfig()
    flo_cfg = FlotationConfig()
    lab_cfg = ProcessLabConfig()
    boundary_cfg = BoundaryConfig.from_legacy(dist_cfg, ball_cfg, dt=sim_cfg.dt)
    apply_dcs_coupling_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, args.dcs_coupling)
    apply_data_quality_preset(boundary_cfg, mag_cfg, tm_cfg, flo_cfg, lab_cfg, args.data_quality)
    if args.assay_interval_min is not None:
        flo_cfg.assay_interval_min = args.assay_interval_min
    if args.assay_interval_max is not None:
        flo_cfg.assay_interval_max = args.assay_interval_max
    if flo_cfg.assay_interval_min <= 0 or flo_cfg.assay_interval_max < flo_cfg.assay_interval_min:
        raise ValueError("assay interval must satisfy 0 < min <= max")
    if args.process_lab_interval_min is not None:
        lab_cfg.interval_min_steps = args.process_lab_interval_min
    if args.process_lab_interval_max is not None:
        lab_cfg.interval_max_steps = args.process_lab_interval_max
    if lab_cfg.interval_min_steps <= 0 or lab_cfg.interval_max_steps < lab_cfg.interval_min_steps:
        raise ValueError("process lab interval must satisfy 0 < min <= max")

    sim = Simulator(
        sim_cfg=sim_cfg,
        dist_cfg=dist_cfg,
        ball_cfg=ball_cfg,
        mag_cfg=mag_cfg,
        boundary_cfg=boundary_cfg,
        tm_cfg=tm_cfg,
        flo_cfg=flo_cfg,
        lab_cfg=lab_cfg,
        output_path=args.output,
        fmt=args.format,
    )

    if not args.no_warmup:
        print(f"[仿真] 预热 {sim_cfg.warm_up_steps} 步 ...", flush=True)
        sim.warm_up()

    n_steps = args.steps if args.steps is not None else sim_cfg.n_steps
    if n_steps <= 0:
        raise ValueError(f"--steps 必须是正整数，得到 {n_steps!r}")
    print(f"[仿真] 开始仿真 {n_steps} 步 ...", flush=True)
    t0 = time.perf_counter()

    sim.run_steps(n_steps)

    elapsed = time.perf_counter() - t0
    print(f"[仿真] 完成！耗时 {elapsed:.2f}s，输出 → {args.output}")


if __name__ == "__main__":
    main()
