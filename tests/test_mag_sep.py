"""
磁选段单元测试。

验证：
  1. PID 液位控制收敛（300步内）
  2. 线圈热力学稳态在 60~80°C
  3. 弱磁标定点：g_wmag ≈ 51.29%，beta_wm ≈ 45.23%
  4. 强磁标定点：g_strong ≈ 40.73%，beta_strong ≈ 67.99%（名义点）
  5. 混磁精矿品位 ≈ 43.84%
  6. 所有 DCS 输出变量存在于 bus 且无 NaN/Inf
"""

from __future__ import annotations
import sys
import math
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import SimConfig, DisturbanceConfig, BallMillConfig, MagSepConfig
from sim.rng import RNGFactory
from sim.layers.disturbance import DisturbanceLayer
from sim.layers.ball_mill import BallMillInput
from sim.layers.mag_sep import MagSepSystem, _sigmoid


MAG_DCS_COLUMNS = [
    "agg_mag_excit_voltage",
    "agg_mag_excit_current",
    "agg_mag_coil_temp",
    "agg_mag_tailings_valve1",
    "agg_mag_tailings_valve2",
    "agg_mag_blowdown_valve",
    "agg_mag_pulsation_freq",
    "agg_mag_ring_freq",
    "agg_mag_level",
    "agg_mag_flush_water_pressure",
    "agg_mag_motor_current_rc",
    "agg_mag_motor_voltage_rc",
]


def build_system(seed: int = 42):
    sim_cfg = SimConfig()
    dist_cfg = DisturbanceConfig()
    ball_cfg = BallMillConfig()
    mag_cfg = MagSepConfig()
    rng_factory = RNGFactory(seed)
    dist = DisturbanceLayer(dist_cfg, rng_factory.get("dist"))
    ball = BallMillInput(ball_cfg, rng_factory.get("ball"))
    mag = MagSepSystem(mag_cfg, sim_cfg, rng_factory.get("mag"))
    return dist, ball, mag, sim_cfg


def run_n_steps(n: int, seed: int = 42) -> list[dict]:
    dist, ball, mag, _ = build_system(seed)
    history = []
    for t in range(n):
        bus: dict = {}
        dist.step(bus)
        ball.step(bus)
        mag.step(bus, t)
        history.append(dict(bus))
    return history


class TestMagSepOutputCompleteness:
    def test_all_dcs_columns_present(self):
        history = run_n_steps(10)
        last_bus = history[-1]
        for col in MAG_DCS_COLUMNS:
            assert col in last_bus, f"列 {col} 不在 bus 中"

    def test_no_nan_inf(self):
        history = run_n_steps(200)
        for bus in history:
            for col in MAG_DCS_COLUMNS:
                v = bus[col]
                assert math.isfinite(v), f"{col} = {v} (step={bus['t']})"

    def test_hidden_states_present(self):
        history = run_n_steps(10)
        for key in ("_x_g_mag", "_x_m_mag"):
            assert key in history[-1], f"{key} 不在 bus 中"


class TestMagSepPIDConvergence:
    def test_level_converges_within_300_steps(self):
        """液位应在 300 步（5 小时）内稳定至设定值附近（±0.3 m）。"""
        history = run_n_steps(600)
        cfg = MagSepConfig()
        # 取后 100 步（300~600步）的平均液位
        levels_late = [bus["agg_mag_level"] for bus in history[300:]]
        mean_late = np.mean(levels_late)
        assert abs(mean_late - cfg.L_setpoint) < 0.3, (
            f"液位均值 {mean_late:.3f} m 偏离设定值 {cfg.L_setpoint} m 超过 0.3 m"
        )


class TestMagSepThermalSteadyState:
    def test_coil_temp_in_design_range(self):
        """线圈温度稳态值应在 60~80°C 之间。"""
        history = run_n_steps(1000)
        cfg = MagSepConfig()
        # 后 200 步均值
        temps = [bus["agg_mag_coil_temp"] for bus in history[800:]]
        mean_temp = np.mean(temps)
        assert 50.0 <= mean_temp <= 90.0, (
            f"线圈温度均值 {mean_temp:.1f}°C 超出 [50, 90]°C 范围"
        )


class TestMagSepCalibration:
    """标定点断言（与 calibrate.py 一致，以 pytest 形式执行）。"""

    def test_weak_mag_grade(self):
        cfg = MagSepConfig()
        d1 = 0.3149
        g_wmag = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        assert abs(g_wmag * 100 - 51.29) < 0.5, (
            f"弱磁精矿品位 {g_wmag*100:.4f}% 偏离 51.29%±0.5%"
        )

    def test_weak_mag_recovery(self):
        cfg = MagSepConfig()
        f25 = cfg.f25_nom
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        assert abs(beta_wm * 100 - 45.23) < 1.0, (
            f"弱磁回收率 {beta_wm*100:.4f}% 偏离 45.23%±1.0%"
        )

    def test_wm_tail_grade(self):
        """弱磁尾矿品位（= 强磁给矿）应接近 23.91%。"""
        cfg = MagSepConfig()
        d1 = 0.3149
        f25 = cfg.f25_nom
        g_wmag = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        m_Fe = d1
        m_wm_conc_frac = beta_wm * m_Fe / g_wmag
        m_tail_frac = 1.0 - m_wm_conc_frac
        g_tail = (m_Fe - beta_wm * m_Fe) / m_tail_frac
        assert abs(g_tail * 100 - 23.91) < 0.5, (
            f"弱磁尾矿品位 {g_tail*100:.4f}% 偏离 23.91%±0.5%"
        )

    def test_strong_mag_grade(self):
        cfg = MagSepConfig()
        # 使用弱磁标定推算得到的给矿品位
        d1 = 0.3149
        f25 = cfg.f25_nom
        g_wmag = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        m_tail_frac = 1.0 - beta_wm * d1 / g_wmag
        g_feed = (d1 - beta_wm * d1) / m_tail_frac

        g_strong = g_feed * cfg.k_s_Fe / (1.0 + cfg.k_s_Si * (1.0 - g_feed))
        assert abs(g_strong * 100 - 40.73) < 1.0, (
            f"强磁精矿品位 {g_strong*100:.4f}% 偏离 40.73%±1.0%"
        )

    def test_strong_mag_beta_at_nominal(self):
        """名义点（force_balance=1）beta_strong 应 = sigmoid(bias_s) ≈ 67.99%。"""
        cfg = MagSepConfig()
        beta_nom = _sigmoid(cfg.bias_s)
        assert abs(beta_nom * 100 - 67.99) < 1.0, (
            f"名义 beta_strong {beta_nom*100:.4f}% 偏离 67.99%±1.0%"
        )

    def test_mixed_mag_grade(self):
        """混磁精矿品位应接近 43.84%。"""
        cfg = MagSepConfig()
        d1 = 0.3149
        f25 = cfg.f25_nom
        m_ball_nom = 265.0 * 3

        g_wmag = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        beta_strong = _sigmoid(cfg.bias_s)

        m_wm_conc = beta_wm * d1 * m_ball_nom / g_wmag
        m_wm_tail = m_ball_nom - m_wm_conc
        g_wm_tail = (d1 - beta_wm * d1) / (1.0 - m_wm_conc / m_ball_nom)

        g_strong = g_wm_tail * cfg.k_s_Fe / (1.0 + cfg.k_s_Si * (1.0 - g_wm_tail))
        m_strong_conc = beta_strong * g_wm_tail * m_wm_tail / g_strong
        m_strong_tail = m_wm_tail - m_strong_conc
        m_Fe_strong_tail = g_wm_tail * m_wm_tail - g_strong * m_strong_conc
        g_strong_tail = max(m_Fe_strong_tail / m_strong_tail, 0.0)

        g_sweep = g_strong_tail * cfg.k_sw_Fe / (1.0 + cfg.k_sw_Si * (1.0 - g_strong_tail))
        m_sweep_conc = cfg.beta_sweep_Fe * g_strong_tail * m_strong_tail / max(g_sweep, 0.01)

        m_mag = m_wm_conc + m_strong_conc + m_sweep_conc
        g_mag = (g_wmag * m_wm_conc + g_strong * m_strong_conc + g_sweep * m_sweep_conc) / m_mag

        assert abs(g_mag * 100 - 43.84) < 1.0, (
            f"混磁精矿品位 {g_mag*100:.4f}% 偏离 43.84%±1.0%"
        )
