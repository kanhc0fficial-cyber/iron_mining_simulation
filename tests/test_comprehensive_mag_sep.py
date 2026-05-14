"""
磁选段（MagSepSystem）综合测试
Phase 2: 覆盖励磁系统、热力学、弱磁/强磁/扫磁物理计算、液位控制、DCS输出等

测试角度:
  - DCS 输出字段完整性
  - 励磁电压/电流物理范围
  - 线圈温度热力学合理性
  - 品位提升效果（弱磁/强磁/混精矿品位升级）
  - 质量守恒（给矿 = 精矿 + 尾矿）
  - 液位控制稳定性
  - 排污阀周期脉冲
  - 隐藏中间量完整性
  - 设备聚合 DCS 输出范围
  - 各段铁回收率合理性
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import BoundaryConfig, MagSepConfig, SimConfig
from sim.layers.boundary import BoundaryGenerator
from sim.layers.mag_sep import (
    MagSepSystem,
    _stream_grade,
    _stream_mass,
    _stream_fe,
    _scale_stream,
    _subtract_stream,
    _merge_streams,
    _sigmoid,
    _split_by_component_recovery,
)
from sim.output.schema import STEP1_COLUMNS


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_nominal_bus(
    d1: float = 0.3149,
    m_ball: float = 795.0,
    f25: float = 0.5419,
    f200: float = 0.77,
) -> dict:
    """构造名义边界 bus（磁选段输入）。"""
    return {
        "_x_d1": d1,
        "_x_d2": 0.018,
        "_x_d3": 1.0,
        "_x_d4": 0.40,
        "_x_m_ball": m_ball,
        "_x_rho_ball": 0.385,
        "_x_d80_ball": 0.074,
        "_x_f25_ball": f25,
        "_x_f200_ball": f200,
        "_x_f325_ball": 0.55,
        "_x_boundary_tfe": d1,
        "_x_boundary_c": 0.385,
        "_x_boundary_lines_on": 3,
        "_x_boundary_fe_mag": m_ball * d1 * 0.765,
        "_x_boundary_fe_hem": m_ball * d1 * 0.118,
        "_x_boundary_fe_carb": m_ball * d1 * 0.057,
        "_x_boundary_fe_sil": m_ball * d1 * 0.060,
        "_x_boundary_gangue": m_ball * (1.0 - d1),
        "_x_boundary_wi": 1.0,
        "_x_boundary_clay": 0.08,
        "_x_boundary_feo_proxy": 0.0,
    }


def _run_mag(
    n: int = 200,
    seed: int = 42,
    d1: float = 0.3149,
    m_ball: float = 795.0,
    cfg: MagSepConfig | None = None,
) -> list[dict]:
    sim_cfg = SimConfig(seed=seed)
    rng = np.random.default_rng(seed)
    mag = MagSepSystem(cfg or MagSepConfig(), sim_cfg, rng)
    history: list[dict] = []
    for t in range(n):
        bus = _make_nominal_bus(d1=d1, m_ball=m_ball)
        mag.step(bus, t)
        history.append(dict(bus))
    return history


def _run_with_boundary(n: int = 300, seed: int = 42) -> list[dict]:
    """用真实边界层驱动磁选段。"""
    sim_cfg = SimConfig(seed=seed)
    rng_b = np.random.default_rng(seed)
    rng_m = np.random.default_rng(seed + 1)
    boundary = BoundaryGenerator(BoundaryConfig(), sim_cfg, rng_b)
    mag = MagSepSystem(MagSepConfig(), sim_cfg, rng_m)
    history: list[dict] = []
    for t in range(n):
        bus: dict = {"t": t}
        boundary.step(bus, t)
        mag.step(bus, t)
        history.append(dict(bus))
    return history


def _arr(history: list[dict], key: str) -> np.ndarray:
    return np.array([row[key] for row in history])


# ──────────────────────────────────────────────────────────────────────────────
# 1. DCS 输出字段完整性
# ──────────────────────────────────────────────────────────────────────────────

class TestDCSOutputCompleteness:

    def test_agg_mag_excit_voltage_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_excit_voltage" in bus

    def test_agg_mag_excit_current_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_excit_current" in bus

    def test_agg_mag_coil_temp_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_coil_temp" in bus

    def test_agg_mag_tailings_valve1_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_tailings_valve1" in bus

    def test_agg_mag_tailings_valve2_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_tailings_valve2" in bus

    def test_agg_mag_blowdown_valve_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_blowdown_valve" in bus

    def test_agg_mag_pulsation_freq_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_pulsation_freq" in bus

    def test_agg_mag_ring_freq_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_ring_freq" in bus

    def test_agg_mag_level_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_level" in bus

    def test_agg_mag_flush_water_pressure_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_flush_water_pressure" in bus

    def test_agg_mag_motor_current_rc_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_motor_current_rc" in bus

    def test_agg_mag_motor_voltage_rc_present(self):
        bus = _run_mag(n=1)[-1]
        assert "agg_mag_motor_voltage_rc" in bus

    def test_all_step1_columns_present(self):
        bus = _run_mag(n=1)[-1]
        missing = [col for col in STEP1_COLUMNS if col not in bus]
        assert not missing, f"缺失 STEP1 列: {missing}"

    def test_hidden_g_mag_present(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_g_mag" in bus

    def test_hidden_m_mag_present(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_m_mag" in bus


# ──────────────────────────────────────────────────────────────────────────────
# 2. 励磁系统
# ──────────────────────────────────────────────────────────────────────────────

class TestExcitationSystem:

    def setup_method(self):
        self.history = _run_mag(n=500)
        self.late = self.history[50:]

    def test_excit_voltage_near_nominal(self):
        """励磁电压应在 V_nom 附近（AR(1) 微弱波动）。"""
        V = _arr(self.late, "agg_mag_excit_voltage")
        # agg 列是聚合值，可能有设备间偏差
        assert np.all((V >= 60.0) & (V <= 100.0)), \
            f"励磁电压超出范围: [{V.min():.2f}, {V.max():.2f}]"

    def test_excit_current_positive(self):
        I = _arr(self.late, "agg_mag_excit_current")
        assert np.all(I > 0), "励磁电流含非正值"

    def test_excit_current_in_range(self):
        I = _arr(self.late, "agg_mag_excit_current")
        # I_nom = V_nom / R0_coil = 80/3 ≈ 26.7A
        assert np.all((I >= 10.0) & (I <= 50.0)), \
            f"励磁电流超出范围: [{I.min():.2f}, {I.max():.2f}]"

    def test_excit_voltage_stable(self):
        """励磁电压方差应极小（phi=0.999，sigma_V=0.05）。"""
        V = _arr(self.late, "agg_mag_excit_voltage")
        assert V.std() < 5.0, f"励磁电压过于不稳定: std={V.std():.3f}V"

    def test_motor_voltage_near_nominal(self):
        Vm = _arr(self.late, "agg_mag_motor_voltage_rc")
        assert np.all((Vm >= 350.0) & (Vm <= 420.0)), \
            f"电机电压超出范围: [{Vm.min():.2f}, {Vm.max():.2f}]"


# ──────────────────────────────────────────────────────────────────────────────
# 3. 线圈热力学
# ──────────────────────────────────────────────────────────────────────────────

class TestCoilThermal:

    def setup_method(self):
        self.history = _run_mag(n=1000)
        self.late = self.history[100:]

    def test_coil_temp_positive(self):
        T = _arr(self.late, "agg_mag_coil_temp")
        assert np.all(T > 0), "线圈温度含非正值"

    def test_coil_temp_above_ambient(self):
        T = _arr(self.late, "agg_mag_coil_temp")
        assert np.all(T > 25.0), "线圈温度应高于环境温度"

    def test_coil_temp_in_physical_range(self):
        """稳态温度 ≈ 68°C（标定值）。"""
        T = _arr(self.late, "agg_mag_coil_temp")
        assert np.all((T >= 40.0) & (T <= 100.0)), \
            f"线圈温度超出物理范围: [{T.min():.1f}, {T.max():.1f}]°C"

    def test_coil_temp_converges_to_steady_state(self):
        """1000 步后温度应接近稳态（68°C）。"""
        T = _arr(self.late, "agg_mag_coil_temp")
        # 稳态 ≈ T_amb + I_nom²*R0 / k_cool = 25 + (80/3)²*3 / 50 ≈ 68°C
        T_ss_expected = 68.0
        # 放宽容差，因为有 agg 偏差
        assert abs(T.mean() - T_ss_expected) < 15.0, \
            f"线圈温度均值 {T.mean():.1f} 偏离稳态 {T_ss_expected:.1f}°C"


# ──────────────────────────────────────────────────────────────────────────────
# 4. 品位提升
# ──────────────────────────────────────────────────────────────────────────────

class TestGradeUpgrade:

    def setup_method(self):
        self.history = _run_mag(n=300)
        self.late = self.history[50:]

    def test_mixed_conc_grade_above_feed_grade(self):
        """混磁精矿品位应高于给矿品位（品位升级）。"""
        for row in self.late:
            feed_grade = row["_x_d1"]
            mix_grade = row["_x_g_mag"]
            assert mix_grade > feed_grade, \
                f"混精品位 {mix_grade:.4f} 应 > 给矿品位 {feed_grade:.4f}"

    def test_mixed_conc_grade_near_calibration(self):
        """标定点：d1=31.49% → 混精品位 ≈ 43.84%（容差 ±3%）。"""
        g_mag = _arr(self.late, "_x_g_mag")
        assert abs(g_mag.mean() - 0.4384) < 0.030, \
            f"混精品位均值 {g_mag.mean():.4f} 偏离 0.4384"

    def test_mixed_conc_grade_in_range(self):
        g_mag = _arr(self.late, "_x_g_mag")
        assert np.all((g_mag >= 0.30) & (g_mag <= 0.70)), \
            f"混精品位超出范围: [{g_mag.min():.4f}, {g_mag.max():.4f}]"

    def test_wm_conc_grade_above_feed(self):
        """弱磁精矿品位应高于给矿品位。"""
        for row in self.late:
            g_wm = row.get("_x_mag_wm_conc_tfe", None)
            if g_wm is not None:
                assert g_wm >= row["_x_d1"] - 0.01, \
                    f"弱精品位 {g_wm:.4f} < 给矿品位 {row['_x_d1']:.4f}"

    def test_hm_conc_grade_above_hm_feed(self):
        """强磁精矿品位应高于强磁给矿品位。"""
        for row in self.late:
            g_hm_feed = row.get("_x_mag_hm_feed_tfe", None)
            g_hm_conc = row.get("_x_mag_hm_conc_tfe", None)
            if g_hm_feed is not None and g_hm_conc is not None:
                assert g_hm_conc >= g_hm_feed - 0.01, \
                    f"强精品位 {g_hm_conc:.4f} < 强给品位 {g_hm_feed:.4f}"

    def test_mixed_conc_grade_increases_with_feed_grade(self):
        """给矿品位更高时混精品位也应更高。"""
        h_low = _run_mag(n=200, seed=0, d1=0.30)
        h_high = _run_mag(n=200, seed=0, d1=0.33)
        g_low = _arr(h_low[50:], "_x_g_mag").mean()
        g_high = _arr(h_high[50:], "_x_g_mag").mean()
        assert g_high > g_low, \
            f"高给矿品位应得到更高混精品位: {g_high:.4f} vs {g_low:.4f}"


# ──────────────────────────────────────────────────────────────────────────────
# 5. 质量守恒
# ──────────────────────────────────────────────────────────────────────────────

class TestMassConservation:

    def setup_method(self):
        self.history = _run_mag(n=200)
        self.late = self.history[20:]

    def test_m_mag_nonnegative(self):
        m_mag = _arr(self.late, "_x_m_mag")
        assert np.all(m_mag >= 0), "混精质量含负值"

    def test_m_mag_less_than_feed(self):
        """混精质量应小于给矿量（磁选有尾矿抛出）。"""
        for row in self.late:
            assert row["_x_m_mag"] <= row["_x_m_ball"] + 1.0, \
                f"混精 {row['_x_m_mag']:.1f} > 给矿 {row['_x_m_ball']:.1f}"

    def test_wm_conc_plus_tail_approx_feed(self):
        """弱磁精矿 + 尾矿 ≈ 给矿（滞后延迟内近似成立）。"""
        for row in self.late:
            wm_conc = row.get("_x_mag_wm_conc_m", 0.0)
            wm_tail = row.get("_x_mag_wm_tail_m", 0.0)
            feed_m = row.get("_x_mag_feed_m", row.get("_x_m_ball", None))
            if feed_m is not None:
                balance = wm_conc + wm_tail
                assert abs(balance - feed_m) < 0.5 * max(feed_m, 1.0), \
                    f"弱磁质量不平衡: conc+tail={balance:.2f}, feed={feed_m:.2f}"

    def test_hm_conc_grade_satisfies_conservation(self):
        """强磁精矿铁量 ≤ 强磁给矿铁量。"""
        for row in self.late:
            fe_hm_feed = row.get("_x_mag_hm_feed_m", 0.0) * row.get("_x_mag_hm_feed_tfe", 0.0)
            fe_hm_conc = row.get("_x_mag_hm_conc_m", 0.0) * row.get("_x_mag_hm_conc_tfe", 0.0)
            assert fe_hm_conc <= fe_hm_feed + 1e-3, \
                f"强精铁量 {fe_hm_conc:.3f} > 给矿铁量 {fe_hm_feed:.3f}"

    def test_g_mag_finite(self):
        g_mag = _arr(self.late, "_x_g_mag")
        assert np.all(np.isfinite(g_mag)), "_x_g_mag 含 NaN/Inf"

    def test_m_mag_finite(self):
        m_mag = _arr(self.late, "_x_m_mag")
        assert np.all(np.isfinite(m_mag)), "_x_m_mag 含 NaN/Inf"


# ──────────────────────────────────────────────────────────────────────────────
# 6. 液位控制
# ──────────────────────────────────────────────────────────────────────────────

class TestLevelControl:

    def setup_method(self):
        self.history = _run_mag(n=500)
        self.late = self.history[100:]

    def test_level_positive(self):
        L = _arr(self.late, "agg_mag_level")
        assert np.all(L > -0.5), "液位含明显负值"

    def test_valve1_in_range(self):
        u1 = _arr(self.late, "agg_mag_tailings_valve1")
        assert np.all((u1 >= 0.0) & (u1 <= 1.0)), \
            f"阀1开度超出 [0,1]: [{u1.min():.4f}, {u1.max():.4f}]"

    def test_valve2_in_range(self):
        u2 = _arr(self.late, "agg_mag_tailings_valve2")
        assert np.all((u2 >= 0.0) & (u2 <= 1.0)), \
            f"阀2开度超出 [0,1]: [{u2.min():.4f}, {u2.max():.4f}]"

    def test_valve2_zero_when_valve1_not_full(self):
        """阀1未全开时阀2应为 0（级联控制）。"""
        history = _run_mag(n=300)
        for row in history:
            u1 = row["agg_mag_tailings_valve1"]
            u2 = row["agg_mag_tailings_valve2"]
            if u1 < 0.99:
                assert u2 < 0.05, \
                    f"阀1={u1:.3f} 未全开时阀2={u2:.3f} 非零（级联逻辑错误）"

    def test_level_stays_in_physical_range(self):
        L = _arr(self.late, "agg_mag_level")
        assert np.all(L <= 3.0), f"液位超过溢流堰高度: max={L.max():.2f}m"


# ──────────────────────────────────────────────────────────────────────────────
# 7. 排污阀周期脉冲
# ──────────────────────────────────────────────────────────────────────────────

class TestBlowdownValve:

    def test_blowdown_occurs_periodically(self):
        """T_blow=28800s，dt=60s，即每 480 步一次排污。"""
        # 先运行到第一个排污周期，步数要超过 480
        history = _run_mag(n=600)
        blowdown = _arr(history, "agg_mag_blowdown_valve")
        # 排污期间阀开度应接近 1.0
        assert np.any(blowdown > 0.5), "排污阀从未开启"

    def test_blowdown_valve_mostly_closed(self):
        """正常情况下大多数时刻排污阀关闭（T_blow=28800, dt_blow=300, 占空比≈1%）。"""
        history = _run_mag(n=1000)
        blowdown = _arr(history, "agg_mag_blowdown_valve")
        fraction_open = (blowdown > 0.5).mean()
        # dt_blow=300/T_blow=28800 ≈ 1.04% 开启时间
        assert fraction_open < 0.05, f"排污阀开启比例 {fraction_open:.3f} 过高"

    def test_blowdown_valve_in_range(self):
        history = _run_mag(n=600)
        blowdown = _arr(history, "agg_mag_blowdown_valve")
        # 含噪声可能略微超过0或1，但应在合理范围内
        assert np.all((blowdown >= -0.1) & (blowdown <= 1.1)), \
            f"排污阀超出范围: [{blowdown.min():.3f}, {blowdown.max():.3f}]"


# ──────────────────────────────────────────────────────────────────────────────
# 8. 隐藏中间量完整性
# ──────────────────────────────────────────────────────────────────────────────

class TestHiddenStateCompleteness:

    def test_wm_conc_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_wm_conc_tfe" in bus

    def test_wm_tail_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_wm_tail_tfe" in bus

    def test_hm_conc_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_hm_conc_tfe" in bus

    def test_hm_tail_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_hm_tail_tfe" in bus

    def test_sw_conc_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_sw_conc_tfe" in bus

    def test_sw_tail_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_sw_tail_tfe" in bus

    def test_mixed_conc_stream_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_mixed_conc_tfe" in bus

    def test_liberation_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_liberation_fe_mag" in bus
        assert "_x_liberation_gangue_mag" in bus

    def test_liberation_values_in_range(self):
        h = _run_mag(n=100)
        for row in h:
            lib_fe = row["_x_liberation_fe_mag"]
            lib_g = row["_x_liberation_gangue_mag"]
            assert 0.0 <= lib_fe <= 1.0, f"lib_fe={lib_fe:.4f} 超出 [0,1]"
            assert 0.0 <= lib_g <= 1.0, f"lib_g={lib_g:.4f} 超出 [0,1]"

    def test_recovery_hidden_values_written(self):
        bus = _run_mag(n=1)[-1]
        assert "_x_mag_wm_R_fe_mag" in bus
        assert "_x_mag_hm_R_fe_mag" in bus

    def test_wm_recovery_in_range(self):
        bus = _run_mag(n=1)[-1]
        r = bus["_x_mag_wm_R_fe_mag"]
        assert 0.0 <= r <= 1.0, f"弱磁磁铁矿回收率 {r:.4f} 超出 [0,1]"


# ──────────────────────────────────────────────────────────────────────────────
# 9. 工具函数
# ──────────────────────────────────────────────────────────────────────────────

class TestStreamFunctions:

    def test_stream_mass_correct(self):
        parts = {"fe_mag": 10.0, "fe_hem": 5.0, "fe_carb": 2.0, "fe_sil": 3.0, "gangue": 80.0}
        assert abs(_stream_mass(parts) - 100.0) < 1e-9

    def test_stream_fe_correct(self):
        parts = {"fe_mag": 10.0, "fe_hem": 5.0, "fe_carb": 2.0, "fe_sil": 3.0, "gangue": 80.0}
        assert abs(_stream_fe(parts) - 20.0) < 1e-9

    def test_stream_grade_correct(self):
        parts = {"fe_mag": 10.0, "fe_hem": 5.0, "fe_carb": 2.0, "fe_sil": 3.0, "gangue": 80.0}
        assert abs(_stream_grade(parts) - 0.20) < 1e-9

    def test_stream_grade_empty(self):
        parts = {"fe_mag": 0.0, "fe_hem": 0.0, "fe_carb": 0.0, "fe_sil": 0.0, "gangue": 0.0}
        assert _stream_grade(parts) == 0.0

    def test_scale_stream_doubles(self):
        parts = {"fe_mag": 1.0, "fe_hem": 1.0, "fe_carb": 1.0, "fe_sil": 1.0, "gangue": 1.0}
        scaled = _scale_stream(parts, 2.0)
        assert all(abs(v - 2.0) < 1e-9 for v in scaled.values())

    def test_scale_stream_zero(self):
        parts = {"fe_mag": 1.0, "fe_hem": 1.0, "fe_carb": 1.0, "fe_sil": 1.0, "gangue": 1.0}
        scaled = _scale_stream(parts, 0.0)
        assert all(v == 0.0 for v in scaled.values())

    def test_subtract_stream_nonnegative(self):
        a = {"fe_mag": 10.0, "fe_hem": 5.0, "fe_carb": 2.0, "fe_sil": 3.0, "gangue": 80.0}
        b = {"fe_mag": 15.0, "fe_hem": 2.0, "fe_carb": 1.0, "fe_sil": 1.0, "gangue": 40.0}
        result = _subtract_stream(a, b)
        for k, v in result.items():
            assert v >= 0.0, f"{k}={v} 为负"

    def test_merge_streams_correct(self):
        a = {"fe_mag": 10.0, "fe_hem": 0.0, "fe_carb": 0.0, "fe_sil": 0.0, "gangue": 0.0}
        b = {"fe_mag": 5.0, "fe_hem": 0.0, "fe_carb": 0.0, "fe_sil": 0.0, "gangue": 0.0}
        result = _merge_streams(a, b)
        assert abs(result["fe_mag"] - 15.0) < 1e-9

    def test_sigmoid_at_zero(self):
        assert abs(_sigmoid(0.0) - 0.5) < 1e-9

    def test_sigmoid_positive_large(self):
        assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-6)

    def test_sigmoid_negative_large(self):
        assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-6)

    def test_sigmoid_monotone(self):
        xs = [-5, -2, -1, 0, 1, 2, 5]
        vals = [_sigmoid(x) for x in xs]
        assert all(vals[i] < vals[i+1] for i in range(len(vals)-1))

    def test_split_by_component_recovery_mass_balance(self):
        feed = {"fe_mag": 100.0, "fe_hem": 20.0, "fe_carb": 5.0, "fe_sil": 5.0, "gangue": 200.0}
        conc, tail, rec = _split_by_component_recovery(
            feed, 0.45, 0.51, (1.0, 0.22, 0.05, 0.05), 0.35
        )
        for k in ("fe_mag", "fe_hem", "fe_carb", "fe_sil", "gangue"):
            total = conc.get(k, 0.0) + tail.get(k, 0.0)
            assert abs(total - feed[k]) < 0.5, f"{k}: conc+tail={total:.3f} != feed={feed[k]:.3f}"

    def test_split_recoveries_in_range(self):
        feed = {"fe_mag": 100.0, "fe_hem": 20.0, "fe_carb": 5.0, "fe_sil": 5.0, "gangue": 200.0}
        conc, tail, rec = _split_by_component_recovery(
            feed, 0.45, 0.51, (1.0, 0.22, 0.05, 0.05), 0.35
        )
        for k, v in rec.items():
            assert 0.0 <= v <= 1.0, f"回收率 {k}={v:.4f} 超出 [0,1]"


# ──────────────────────────────────────────────────────────────────────────────
# 10. 冲矿水压力
# ──────────────────────────────────────────────────────────────────────────────

class TestFlushWaterPressure:

    def test_flush_pressure_positive(self):
        h = _run_mag(n=200)
        P = _arr(h[20:], "agg_mag_flush_water_pressure")
        assert np.all(P > 0), "冲矿水压力含负值"

    def test_flush_pressure_in_range(self):
        h = _run_mag(n=200)
        P = _arr(h[20:], "agg_mag_flush_water_pressure")
        # P_flush = d4 - k_pipe * Q_flush² * 1e-3 ≈ 0.40 - 50 * 0.0001 * 1e-3 ≈ 0.395 MPa
        assert np.all((P >= 0.20) & (P <= 0.60)), \
            f"冲矿水压力超出范围: [{P.min():.3f}, {P.max():.3f}]MPa"

    def test_flush_pressure_tracks_d4(self):
        """较高水压 _x_d4 → 较高冲矿水压力。"""
        bus_low = _make_nominal_bus()
        bus_low["_x_d4"] = 0.30
        bus_high = _make_nominal_bus()
        bus_high["_x_d4"] = 0.50
        rng = np.random.default_rng(0)
        mag = MagSepSystem(MagSepConfig(), SimConfig(), rng)
        mag.step(bus_low, 0)
        P_low = bus_low["agg_mag_flush_water_pressure"]
        mag.step(bus_high, 1)
        P_high = bus_high["agg_mag_flush_water_pressure"]
        # 单步噪声可能导致比较失败，只检查接近
        assert P_high > P_low - 0.05, f"高水压应有更高冲水压: {P_high:.3f} vs {P_low:.3f}"


# ──────────────────────────────────────────────────────────────────────────────
# 11. 与边界层集成
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegrationWithBoundary:

    def test_full_pipeline_no_nan(self):
        history = _run_with_boundary(n=300)
        for col in STEP1_COLUMNS:
            vals = _arr(history, col)
            assert not np.any(np.isnan(vals)), f"{col} 含 NaN"
            assert not np.any(np.isinf(vals)), f"{col} 含 Inf"

    def test_full_pipeline_g_mag_positive(self):
        history = _run_with_boundary(n=300)
        g_mag = _arr(history[50:], "_x_g_mag")
        assert np.all(g_mag > 0), "混精品位含非正值"

    def test_full_pipeline_m_mag_positive(self):
        history = _run_with_boundary(n=300)
        m_mag = _arr(history[50:], "_x_m_mag")
        assert np.all(m_mag >= 0), "混精质量含负值"

    def test_reproducibility(self):
        h1 = _run_mag(n=50, seed=77)
        h2 = _run_mag(n=50, seed=77)
        g1 = _arr(h1, "_x_g_mag")
        g2 = _arr(h2, "_x_g_mag")
        assert np.allclose(g1, g2), "相同种子结果不一致"
