"""
入口边界发生器（阶段 1）。

本层把旧 `DisturbanceLayer + BallMillInput` 的职责收敛为一个入口边界：
三路线二溢/弱磁给矿等价结果、慢变矿石性质、公用水压和入口过程化验。

下游模块当前仍按旧隐藏字段读取，因此本层同时写出兼容键：
`_x_d1/_x_d2/_x_d3/_x_d4/_x_m_ball/_x_rho_ball/_x_d80_ball/_x_f25_ball`。
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from sim.config import BoundaryConfig, SimConfig


_EPS = 1e-9
_LINE_IDS = (1, 2, 3)
_X200_M = 75e-6
_X325_M = 45e-6
_X25_M = 25e-6


@dataclass
class _LineStream:
    m_solid_tph: float
    concentration: float
    tfe: float
    f200: float
    f325: float
    f25: float
    d80_mm: float
    fe_mag_tph: float
    fe_hem_tph: float
    fe_carb_tph: float
    fe_sil_tph: float
    gangue_tph: float
    feo_proxy_tph: float


def _normalize(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 1e-4, None)
    return clipped / max(float(np.sum(clipped)), _EPS)


def _rosin_passing(x_m: float, d80_m: float, n_rr: float) -> float:
    base = max(d80_m, 1e-7)
    return float(np.clip(1.0 - math.exp(-((x_m / base) ** n_rr)), 0.0, 1.0))


def _d80_from_f200(f200: float, n_rr: float) -> float:
    f200 = float(np.clip(f200, 1e-4, 0.999))
    return _X200_M / max((-math.log(1.0 - f200)) ** (1.0 / n_rr), 1e-6)


def _weighted_average(streams: list[_LineStream], field: str) -> float:
    total = sum(s.m_solid_tph for s in streams)
    if total <= _EPS:
        return float("nan")
    return sum(s.m_solid_tph * getattr(s, field) for s in streams) / total


class BoundaryGenerator:
    """生成入口边界 Stream、兼容隐藏量和三路线入口化验。"""

    def __init__(
        self,
        cfg: BoundaryConfig,
        sim_cfg: SimConfig,
        rng: np.random.Generator,
        open_loop: bool = False,
    ) -> None:
        self._cfg = cfg
        self._dt = sim_cfg.dt
        self._rng = rng
        self._open_loop = open_loop
        self._step_idx = 0

        self._ore = np.array([
            cfg.tfe_mean,
            cfg.r_mag_mean,
            cfg.r_hem_mean,
            cfg.r_carb_mean,
            cfg.r_sil_mean,
            cfg.wi_mean,
            cfg.clay_mean,
        ], dtype=float)
        self._target = self._ore.copy()

        n = cfg.n_lines
        self._flow_common_xi = 0.0
        self._flow_xi = np.zeros(n, dtype=float)
        self._conc_xi = np.zeros(n, dtype=float)
        self._f200_xi = np.zeros(n, dtype=float)
        self._grade_xi = np.zeros(n, dtype=float)
        self._water_xi = 0.0
        self._availability = np.ones(n, dtype=bool)
        self._next_lab = np.zeros(n, dtype=int)

    def step(self, bus: dict, t: int | None = None) -> None:
        """推进一步，写入入口边界隐藏量、三路线状态和入口化验。"""
        cfg = self._cfg
        if t is None:
            t = self._step_idx
        self._step_idx = t + 1

        self._update_ore_state()
        self._update_line_schedule()
        self._update_line_residuals()

        water_pressure = self._update_water_pressure()
        tfe_base, r_mag, r_hem, r_carb, r_sil, wi, clay = self._ore
        ratios = _normalize(np.array([r_mag, r_hem, r_carb, r_sil], dtype=float))
        streams: list[_LineStream] = []

        for idx in range(cfg.n_lines):
            stream = self._make_line_stream(idx, tfe_base, ratios, wi, clay)
            streams.append(stream)
            self._write_line_hidden(bus, idx + 1, stream, self._availability[idx])
            self._write_line_labs(bus, idx + 1, t, stream)

        active_streams = [s for s, on in zip(streams, self._availability) if on]
        if not active_streams:
            active_streams = streams

        m_total = sum(s.m_solid_tph for s in active_streams)
        if m_total <= _EPS:
            mixed_tfe = cfg.tfe_mean
            mixed_c = cfg.line_conc_mean
            mixed_f200 = cfg.f200_mean
            mixed_f325 = _rosin_passing(_X325_M, _d80_from_f200(mixed_f200, cfg.rr_n), cfg.rr_n)
            mixed_f25 = _rosin_passing(_X25_M, _d80_from_f200(mixed_f200, cfg.rr_n), cfg.rr_n)
            mixed_d80_mm = _d80_from_f200(mixed_f200, cfg.rr_n) * 1000.0
            fe_carb_abs = cfg.tfe_mean * cfg.r_carb_mean
        else:
            mixed_tfe = _weighted_average(active_streams, "tfe")
            mixed_c = _weighted_average(active_streams, "concentration")
            mixed_f200 = _weighted_average(active_streams, "f200")
            mixed_f325 = _weighted_average(active_streams, "f325")
            mixed_f25 = _weighted_average(active_streams, "f25")
            mixed_d80_mm = _weighted_average(active_streams, "d80_mm")
            fe_carb_abs = sum(s.fe_carb_tph for s in active_streams) / m_total

        bus["_x_d1"] = float(mixed_tfe)
        bus["_x_d2"] = float(fe_carb_abs)
        bus["_x_d3"] = float(np.clip(wi, cfg.wi_min, cfg.wi_max))
        bus["_x_d4"] = float(water_pressure)
        bus["_x_m_ball"] = float(m_total)
        bus["_x_rho_ball"] = float(mixed_c)
        bus["_x_d80_ball"] = float(mixed_d80_mm)
        bus["_x_f25_ball"] = float(mixed_f25)
        bus["_x_f200_ball"] = float(mixed_f200)
        bus["_x_f325_ball"] = float(mixed_f325)
        bus["_x_boundary_lines_on"] = int(np.count_nonzero(self._availability))
        bus["_x_boundary_tfe"] = float(mixed_tfe)
        bus["_x_boundary_c"] = float(mixed_c)

    def _update_ore_state(self) -> None:
        cfg = self._cfg
        if self._rng.random() < cfg.p_block_switch:
            self._target = np.array([
                np.clip(
                    cfg.tfe_mean + self._rng.normal(0.0, cfg.tfe_block_sigma),
                    cfg.tfe_min,
                    cfg.tfe_max,
                ),
                cfg.r_mag_mean + self._rng.normal(0.0, cfg.r_component_sigma),
                cfg.r_hem_mean + self._rng.normal(0.0, cfg.r_component_sigma),
                cfg.r_carb_mean + self._rng.normal(0.0, cfg.r_component_sigma),
                cfg.r_sil_mean + self._rng.normal(0.0, cfg.r_component_sigma),
                np.clip(
                    cfg.wi_mean + self._rng.normal(0.0, cfg.wi_block_sigma),
                    cfg.wi_min,
                    cfg.wi_max,
                ),
                np.clip(
                    cfg.clay_mean + self._rng.normal(0.0, 0.025),
                    cfg.clay_min,
                    cfg.clay_max,
                ),
            ], dtype=float)

        phi = math.exp(-self._dt / max(cfg.tau_blend_s, 1.0))
        grade_sigma = cfg.tfe_sigma * (cfg.tfe_open_sigma_factor if self._open_loop else 1.0)
        noise = np.array([
            self._rng.normal(0.0, grade_sigma),
            *self._rng.normal(0.0, cfg.r_component_sigma * 0.12, 4),
            self._rng.normal(0.0, cfg.wi_sigma),
            self._rng.normal(0.0, cfg.clay_sigma),
        ], dtype=float)
        self._ore = self._target + (self._ore - self._target) * phi + noise
        self._ore[0] = np.clip(self._ore[0], cfg.tfe_min, cfg.tfe_max)
        self._ore[1:5] = _normalize(self._ore[1:5])
        self._ore[5] = np.clip(self._ore[5], cfg.wi_min, cfg.wi_max)
        self._ore[6] = np.clip(self._ore[6], cfg.clay_min, cfg.clay_max)

    def _update_line_schedule(self) -> None:
        cfg = self._cfg
        if self._rng.random() >= cfg.p_line_schedule_switch:
            return
        u = self._rng.random()
        if u < cfg.p_lines_on_1:
            n_on = 1
        elif u < cfg.p_lines_on_1 + cfg.p_lines_on_2:
            n_on = 2
        else:
            n_on = cfg.n_lines
        active_idx = self._rng.choice(cfg.n_lines, size=n_on, replace=False)
        self._availability[:] = False
        self._availability[active_idx] = True

    def _update_line_residuals(self) -> None:
        cfg = self._cfg
        self._flow_common_xi = (
            cfg.line_flow_phi * self._flow_common_xi
            + self._rng.normal(0.0, cfg.line_flow_common_sigma)
        )
        self._flow_xi = (
            cfg.line_flow_phi * self._flow_xi
            + self._rng.normal(0.0, cfg.line_flow_ind_sigma, cfg.n_lines)
        )
        self._conc_xi = (
            cfg.line_conc_phi * self._conc_xi
            + self._rng.normal(0.0, cfg.line_conc_sigma, cfg.n_lines)
        )
        self._f200_xi = (
            cfg.f200_phi * self._f200_xi
            + self._rng.normal(0.0, cfg.f200_sigma, cfg.n_lines)
        )
        self._grade_xi = (
            0.98 * self._grade_xi
            + self._rng.normal(0.0, cfg.tfe_sigma * 0.8, cfg.n_lines)
        )

    def _update_water_pressure(self) -> float:
        cfg = self._cfg
        self._water_xi = (
            cfg.water_pressure_phi * self._water_xi
            + self._rng.normal(0.0, cfg.water_pressure_sigma)
        )
        return float(np.clip(
            cfg.water_pressure_mean + self._water_xi,
            cfg.water_pressure_min,
            cfg.water_pressure_max,
        ))

    def _make_line_stream(
        self,
        idx: int,
        tfe_base: float,
        ratios: np.ndarray,
        wi: float,
        clay: float,
    ) -> _LineStream:
        cfg = self._cfg
        if self._availability[idx]:
            m_solid = float(np.clip(
                cfg.line_solid_nom_tph + self._flow_common_xi + self._flow_xi[idx],
                cfg.line_solid_min_tph,
                cfg.line_solid_max_tph,
            ))
        else:
            m_solid = 0.0

        load_frac = 0.0
        if cfg.line_solid_nom_tph > _EPS and self._availability[idx]:
            load_frac = (m_solid - cfg.line_solid_nom_tph) / cfg.line_solid_nom_tph

        concentration = float(np.clip(
            cfg.line_conc_mean + self._conc_xi[idx] + cfg.conc_load_coeff * load_frac,
            cfg.line_conc_min,
            cfg.line_conc_max,
        ))
        tfe = float(np.clip(tfe_base + self._grade_xi[idx], cfg.tfe_min, cfg.tfe_max))
        f200 = float(np.clip(
            cfg.f200_mean
            + self._f200_xi[idx]
            - cfg.f200_wi_coeff * (wi - cfg.wi_mean)
            - cfg.f200_load_coeff * load_frac
            - cfg.f200_clay_coeff * (clay - cfg.clay_mean),
            cfg.f200_min,
            cfg.f200_max,
        ))
        d80_m = _d80_from_f200(f200, cfg.rr_n)
        f325 = _rosin_passing(_X325_M, d80_m, cfg.rr_n)
        f25 = _rosin_passing(_X25_M, d80_m, cfg.rr_n)

        fe_total = m_solid * tfe
        fe_mag = fe_total * ratios[0]
        fe_hem = fe_total * ratios[1]
        fe_carb = fe_total * ratios[2]
        fe_sil = fe_total * ratios[3]
        gangue = max(m_solid - fe_total, 0.0)
        feo_proxy = (
            cfg.k_feo_mag * fe_mag
            + cfg.k_feo_carb * fe_carb
            + cfg.k_feo_hem * fe_hem
            + cfg.k_feo_sil * fe_sil
        )
        return _LineStream(
            m_solid_tph=m_solid,
            concentration=concentration,
            tfe=tfe,
            f200=f200,
            f325=f325,
            f25=f25,
            d80_mm=d80_m * 1000.0,
            fe_mag_tph=fe_mag,
            fe_hem_tph=fe_hem,
            fe_carb_tph=fe_carb,
            fe_sil_tph=fe_sil,
            gangue_tph=gangue,
            feo_proxy_tph=feo_proxy,
        )

    def _write_line_hidden(
        self,
        bus: dict,
        line_id: int,
        stream: _LineStream,
        is_on: bool,
    ) -> None:
        prefix = f"_x_eryi_line{line_id}"
        bus[f"{prefix}_on"] = int(is_on)
        bus[f"{prefix}_m_solid"] = stream.m_solid_tph
        bus[f"{prefix}_c"] = stream.concentration
        bus[f"{prefix}_tfe"] = stream.tfe
        bus[f"{prefix}_f200"] = stream.f200
        bus[f"{prefix}_f325"] = stream.f325
        bus[f"{prefix}_f25"] = stream.f25
        bus[f"{prefix}_d80"] = stream.d80_mm
        bus[f"{prefix}_fe_mag"] = stream.fe_mag_tph
        bus[f"{prefix}_fe_hem"] = stream.fe_hem_tph
        bus[f"{prefix}_fe_carb"] = stream.fe_carb_tph
        bus[f"{prefix}_fe_sil"] = stream.fe_sil_tph
        bus[f"{prefix}_gangue"] = stream.gangue_tph
        bus[f"{prefix}_feo_proxy"] = stream.feo_proxy_tph

    def _write_line_labs(self, bus: dict, line_id: int, t: int, stream: _LineStream) -> None:
        cfg = self._cfg
        idx = line_id - 1
        tfe_col = f"lab_{line_id}_eryi_tfe"
        f200_col = f"lab_{line_id}_eryi_f200"
        if t >= self._next_lab[idx] and self._availability[idx]:
            bus[tfe_col] = float(100.0 * stream.tfe + self._rng.normal(0.0, cfg.lab_sigma_tfe_pct))
            bus[f200_col] = float(100.0 * stream.f200 + self._rng.normal(0.0, cfg.lab_sigma_f200_pct))
            self._next_lab[idx] = int(t + self._rng.integers(
                cfg.lab_interval_min_steps,
                cfg.lab_interval_max_steps + 1,
            ))
        else:
            bus[tfe_col] = float("nan")
            bus[f200_col] = float("nan")


BOUNDARY_LAB_COLUMNS: list[str] = [
    f"lab_{line_id}_eryi_{name}"
    for line_id in _LINE_IDS
    for name in ("f200", "tfe")
]
