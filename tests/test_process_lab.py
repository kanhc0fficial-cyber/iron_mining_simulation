from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import (
    BallMillConfig,
    DisturbanceConfig,
    FlotationConfig,
    MagSepConfig,
    ProcessLabConfig,
    SimConfig,
    TowerMillConfig,
)
from sim.layers.process_lab import INTERNAL_PROCESS_LAB_COLUMNS, ProcessLabSampler
from sim.output.schema import PROCESS_LAB_COLUMNS
from sim.simulator import Simulator


def _complete_hidden_bus() -> dict:
    bus: dict = {}
    for prefix, tfe, mass in [
        ("_x_mag_wm_conc", 0.51, 100.0),
        ("_x_mag_wm_tail", 0.24, 100.0),
        ("_x_mag_hm_conc", 0.40, 100.0),
        ("_x_mag_hm_tail", 0.15, 100.0),
        ("_x_mag_sw_conc", 0.31, 100.0),
        ("_x_mag_sw_tail", 0.075, 100.0),
        ("_x_mag_mixed_conc", 0.438, 100.0),
    ]:
        bus[f"{prefix}_tfe"] = tfe
        bus[f"{prefix}_m"] = mass
    bus.update({
        "_x_boundary_fe_mag": 45.0,
        "_x_boundary_fe_hem": 7.0,
        "_x_boundary_fe_carb": 3.0,
        "_x_boundary_fe_sil": 3.0,
        "_x_boundary_gangue": 126.0,
        "_x_tm_cyclone_feed_f325": 0.55,
        "_x_tm_discharge_f325": 0.70,
        "_x_tm_overflow_f325": 0.925,
        "_x_tm_overflow_tfe": 0.438,
        "_x_tm_overflow_m": 128.0,
        "_x_tm_overflow_conc": 0.17,
        "_x_m_ov": 750.0,
        "_x_tm_cyclone_sand_f325": 0.55,
    })
    for series in (1, 2):
        s = f"s{series}"
        bus[f"_x_flo_feed_{s}_tfe"] = 0.438
        bus[f"_x_flo_feed_f325_{s}"] = 0.925
        bus[f"_x_flo_final_conc_{s}_tfe"] = 0.67
        bus[f"_x_flo_final_tail_{s}_tfe"] = 0.207
        for name, tfe in {
            "rougher_conc": 0.58,
            "rougher_tail": 0.20,
            "cleaner_tail": 0.15,
            "scav1_conc": 0.30,
            "scav1_tail": 0.18,
            "scav2_conc": 0.25,
            "scav2_tail": 0.16,
            "scav3_conc": 0.22,
        }.items():
            bus[f"_x_flo_{name}_{s}_tfe"] = tfe
        bus[f"_x_flo_feed_{s}_m"] = 128.0
        bus[f"_x_flo_final_conc_{s}_m"] = 62.0
        for key, value in {
            "fe_mag": 45.0,
            "fe_hem": 6.0,
            "fe_carb": 2.0,
            "fe_sil": 3.0,
        }.items():
            bus[f"_x_flo_feed_{s}_{key}"] = value
            bus[f"_x_flo_final_conc_{s}_{key}"] = value * 0.75
    return bus


def test_sampler_writes_confirmed_lab_columns_from_hidden_states() -> None:
    cfg = ProcessLabConfig(
        interval_min_steps=1,
        interval_max_steps=1,
        sigma_tfe_pct=0.0,
        sigma_f325_pct=0.0,
        sigma_conc_pct=0.0,
        sigma_yield_pct=0.0,
        sigma_recovery_pct=0.0,
    )
    sampler = ProcessLabSampler(cfg, SimConfig(), np.random.default_rng(1))
    bus = _complete_hidden_bus()
    sampler.step(bus, 0)

    for col in INTERNAL_PROCESS_LAB_COLUMNS:
        assert col in bus, f"{col} missing"
        assert math.isfinite(bus[col]), f"{col} should be finite at sample time"

    assert bus["lab_mag_mixed_conc_tfe"] == 43.8
    assert bus["lab_tm_overflow_tfe"] == 43.8
    assert bus["lab_tm_overflow_conc"] == 17.0
    assert bus["lab_flo_conc_tfe_s1"] == 67.0
    assert bus["lab_flo_tail_tfe_s1"] == 20.7


def test_sampler_non_sample_time_is_nan() -> None:
    sampler = ProcessLabSampler(
        ProcessLabConfig(interval_min_steps=3, interval_max_steps=3),
        SimConfig(),
        np.random.default_rng(2),
    )
    bus = _complete_hidden_bus()
    sampler.step(bus, 0)
    bus = _complete_hidden_bus()
    sampler.step(bus, 1)

    assert all(math.isnan(bus[col]) for col in INTERNAL_PROCESS_LAB_COLUMNS)


def test_process_lab_columns_are_in_output_schema_and_written(tmp_path: Path) -> None:
    output_path = tmp_path / "process_lab.parquet"
    sim = Simulator(
        sim_cfg=SimConfig(n_steps=10, seed=11),
        dist_cfg=DisturbanceConfig(),
        ball_cfg=BallMillConfig(),
        mag_cfg=MagSepConfig(),
        tm_cfg=TowerMillConfig(),
        flo_cfg=FlotationConfig(),
        lab_cfg=ProcessLabConfig(
            interval_min_steps=1,
            interval_max_steps=1,
            sigma_tfe_pct=0.0,
            sigma_f325_pct=0.0,
            sigma_conc_pct=0.0,
            sigma_yield_pct=0.0,
            sigma_recovery_pct=0.0,
        ),
        output_path=output_path,
        fmt="parquet",
    )
    sim.run_steps(10)
    df = pd.read_parquet(output_path)

    for col in INTERNAL_PROCESS_LAB_COLUMNS:
        assert col in PROCESS_LAB_COLUMNS
        assert col in df.columns
        assert df[col].notna().all(), f"{col} should be sampled every step"
