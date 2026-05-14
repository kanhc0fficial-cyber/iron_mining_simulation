"""Process-lab sampler for confirmed non-DCS sample points.

The sampler reads hidden `_x_*` process states and writes `lab_*` outputs at
sample times. It is intentionally downstream-only: no lab value is fed back
into process mechanisms.
"""

from __future__ import annotations

import math

import numpy as np

from sim.config import ProcessLabConfig, SimConfig

_FE_KEYS = ("fe_mag", "fe_hem", "fe_carb", "fe_sil")
_MASS_KEYS = (*_FE_KEYS, "gangue")

MAG_LAB_COLUMNS: list[str] = [
    "lab_mag_wm_conc_tfe",
    "lab_mag_wm_tail_tfe",
    "lab_mag_hm_conc_tfe",
    "lab_mag_hm_tail_tfe",
    "lab_mag_sw_conc_tfe",
    "lab_mag_sw_tail_tfe",
    "lab_mag_mixed_conc_tfe",
    "lab_mag_tube_conc_tfe",
    "lab_mag_tube_yield",
]

TM_LAB_COLUMNS: list[str] = [
    "lab_tm_feed_f325",
    "lab_tm_discharge_f325",
    "lab_tm_overflow_f325",
    "lab_tm_overflow_tfe",
    "lab_tm_overflow_conc",
    "lab_tm_sand_f325",
]

FLO_STAGE_LAB_BASES: list[str] = [
    "feed_tfe",
    "feed_f325",
    "conc_tfe",
    "tail_tfe",
    "rough_conc_tfe",
    "rough_tail_tfe",
    "clean_tail_tfe",
    "scav1_conc_tfe",
    "scav1_tail_tfe",
    "scav2_conc_tfe",
    "scav2_tail_tfe",
    "scav3_conc_tfe",
    "final_conc_yield",
    "final_conc_recovery",
]

FLO_LAB_COLUMNS: list[str] = [
    f"lab_flo_{base}_s{series}"
    for series in (1, 2)
    for base in FLO_STAGE_LAB_BASES
]

INTERNAL_PROCESS_LAB_COLUMNS: list[str] = [
    *MAG_LAB_COLUMNS,
    *TM_LAB_COLUMNS,
    *FLO_LAB_COLUMNS,
]


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _finite(value: float) -> bool:
    return bool(np.isfinite(value))


class ProcessLabSampler:
    """Write confirmed process-lab columns at sampling instants."""

    def __init__(
        self,
        cfg: ProcessLabConfig,
        sim_cfg: SimConfig,
        rng: np.random.Generator,
    ) -> None:
        self._cfg = cfg
        self._rng = rng
        self._next_sample = 0
        self._step_idx = 0
        if cfg.interval_min_steps <= 0 or cfg.interval_max_steps < cfg.interval_min_steps:
            raise ValueError("process lab interval must satisfy 0 < min <= max")

    def step(self, bus: dict, t: int | None = None) -> None:
        if t is None:
            t = self._step_idx
        self._step_idx = t + 1

        for col in INTERNAL_PROCESS_LAB_COLUMNS:
            bus[col] = float("nan")

        if t < self._next_sample:
            return

        self._sample_magnetic(bus)
        self._sample_tower_mill(bus)
        self._sample_flotation(bus)
        self._next_sample = int(t + self._rng.integers(
            self._cfg.interval_min_steps,
            self._cfg.interval_max_steps + 1,
        ))

    def _pct_from_fraction(self, bus: dict, key: str, sigma_pct: float) -> float:
        value = float(bus.get(key, float("nan")))
        if not _finite(value):
            return float("nan")
        return float(100.0 * value + self._rng.normal(0.0, sigma_pct))

    def _sample_magnetic(self, bus: dict) -> None:
        cfg = self._cfg
        mapping = {
            "lab_mag_wm_conc_tfe": "_x_mag_wm_conc_tfe",
            "lab_mag_wm_tail_tfe": "_x_mag_wm_tail_tfe",
            "lab_mag_hm_conc_tfe": "_x_mag_hm_conc_tfe",
            "lab_mag_hm_tail_tfe": "_x_mag_hm_tail_tfe",
            "lab_mag_sw_conc_tfe": "_x_mag_sw_conc_tfe",
            "lab_mag_sw_tail_tfe": "_x_mag_sw_tail_tfe",
            "lab_mag_mixed_conc_tfe": "_x_mag_mixed_conc_tfe",
        }
        for lab_col, hidden_key in mapping.items():
            bus[lab_col] = self._pct_from_fraction(bus, hidden_key, cfg.sigma_tfe_pct)

        feed_fe = sum(float(bus.get(f"_x_boundary_{key}", 0.0)) for key in _FE_KEYS)
        feed_mass = feed_fe + float(bus.get("_x_boundary_gangue", 0.0))
        if feed_mass <= 1e-9 or feed_fe <= 1e-9:
            return
        r_mag = float(bus.get("_x_boundary_fe_mag", 0.0)) / feed_fe
        r_carb = float(bus.get("_x_boundary_fe_carb", 0.0)) / feed_fe
        r_sil = float(bus.get("_x_boundary_fe_sil", 0.0)) / feed_fe
        feed_tfe = feed_fe / feed_mass
        gangue_frac = max(1.0 - feed_tfe, 0.0)
        r_tube = _sigmoid(1.0 + 3.0 * r_mag - 2.0 * r_carb - 1.6 * r_sil)
        tube_yield = float(np.clip(
            cfg.tube_yield_base + cfg.tube_yield_gain * r_tube,
            0.20,
            0.70,
        ))
        tube_conc = float(np.clip(
            100.0 * feed_tfe
            + cfg.tube_conc_gain_pct * r_tube
            - cfg.tube_gangue_penalty_pct * gangue_frac
            + self._rng.normal(0.0, cfg.sigma_tfe_pct),
            0.0,
            100.0,
        ))
        bus["lab_mag_tube_yield"] = float(100.0 * tube_yield + self._rng.normal(0.0, cfg.sigma_yield_pct))
        bus["lab_mag_tube_conc_tfe"] = tube_conc

    def _sample_tower_mill(self, bus: dict) -> None:
        cfg = self._cfg
        bus["lab_tm_feed_f325"] = self._pct_from_fraction(
            bus, "_x_tm_cyclone_feed_f325", cfg.sigma_f325_pct
        )
        bus["lab_tm_discharge_f325"] = self._pct_from_fraction(
            bus, "_x_tm_discharge_f325", cfg.sigma_f325_pct
        )
        bus["lab_tm_overflow_f325"] = self._pct_from_fraction(
            bus, "_x_tm_overflow_f325", cfg.sigma_f325_pct
        )
        bus["lab_tm_overflow_tfe"] = self._pct_from_fraction(
            bus, "_x_tm_overflow_tfe", cfg.sigma_tfe_pct
        )
        bus["lab_tm_sand_f325"] = self._pct_from_fraction(
            bus, "_x_tm_cyclone_sand_f325", cfg.sigma_f325_pct
        )
        conc = float(bus.get("_x_tm_overflow_conc", float("nan")))
        if _finite(conc):
            bus["lab_tm_overflow_conc"] = float(
                100.0 * conc + self._rng.normal(0.0, cfg.sigma_conc_pct)
            )

    def _sample_flotation(self, bus: dict) -> None:
        cfg = self._cfg
        for series in (1, 2):
            s = f"s{series}"
            bus[f"lab_flo_feed_tfe_{s}"] = self._pct_from_fraction(
                bus, f"_x_flo_feed_{s}_tfe", cfg.sigma_tfe_pct
            )
            bus[f"lab_flo_feed_f325_{s}"] = self._pct_from_fraction(
                bus, f"_x_flo_feed_f325_{s}", cfg.sigma_f325_pct
            )
            bus[f"lab_flo_conc_tfe_{s}"] = self._pct_from_fraction(
                bus, f"_x_flo_final_conc_{s}_tfe", cfg.sigma_tfe_pct
            )
            bus[f"lab_flo_tail_tfe_{s}"] = self._pct_from_fraction(
                bus, f"_x_flo_final_tail_{s}_tfe", cfg.sigma_tfe_pct
            )
            stage_map = {
                "rough_conc_tfe": "rougher_conc",
                "rough_tail_tfe": "rougher_tail",
                "clean_tail_tfe": "cleaner_tail",
                "scav1_conc_tfe": "scav1_conc",
                "scav1_tail_tfe": "scav1_tail",
                "scav2_conc_tfe": "scav2_conc",
                "scav2_tail_tfe": "scav2_tail",
                "scav3_conc_tfe": "scav3_conc",
            }
            for lab_base, hidden_base in stage_map.items():
                bus[f"lab_flo_{lab_base}_{s}"] = self._pct_from_fraction(
                    bus, f"_x_flo_{hidden_base}_{s}_tfe", cfg.sigma_tfe_pct
                )
            feed_m = float(bus.get(f"_x_flo_feed_{s}_m", float("nan")))
            conc_m = float(bus.get(f"_x_flo_final_conc_{s}_m", float("nan")))
            if _finite(feed_m) and _finite(conc_m) and feed_m > 1e-9:
                bus[f"lab_flo_final_conc_yield_{s}"] = float(
                    100.0 * conc_m / feed_m + self._rng.normal(0.0, cfg.sigma_yield_pct)
                )
            feed_fe = sum(float(bus.get(f"_x_flo_feed_{s}_{key}", 0.0)) for key in _FE_KEYS)
            conc_fe = sum(float(bus.get(f"_x_flo_final_conc_{s}_{key}", 0.0)) for key in _FE_KEYS)
            if feed_fe > 1e-9:
                bus[f"lab_flo_final_conc_recovery_{s}"] = float(
                    100.0 * conc_fe / feed_fe + self._rng.normal(0.0, cfg.sigma_recovery_pct)
                )
