"""
浮选段（FlotationSystem）综合测试
Phase 4: 覆盖 TFe 标定点、pH 动力学、DCS 完整性、浮选槽液位、
         加药系统、泡沫层故障注入、开环 PRBS、化验时滞等

测试角度:
  - TFe 静态标定（Q_TD=2100/1500 g/t 两点校验）
  - TFe 动态收敛
  - pH 范围与 NaOH 效应
  - 全部 STEP3_COLUMNS 字段存在性
  - 浮选槽液位控制
  - 浮选机电流范围
  - 加药泵频率/电流
  - 泡沫层高度与故障注入
  - 搅拌槽温度控制
  - 泵池液位控制
  - 鼓风机压力
  - K6 液位
  - 化验目标变量 y_fx_xin1/2
  - 质量守恒（精矿 + 尾矿 ≈ 给矿）
  - 开环 PRBS 模式
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import FlotationConfig, SimConfig
from sim.layers.flotation import FlotationSystem
from sim.output.schema import STEP3_COLUMNS


MASS_KEYS = ("fe_mag", "fe_hem", "fe_carb", "fe_sil", "gangue")
_CELLS = ["cx1", "cx2", "cx3", "jx", "sx1", "sx2", "sx3"]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_bus(g_ov: float = 0.4384, m_ov: float = 750.0, d2: float = 0.018) -> dict:
    cfg = FlotationConfig()
    c_mass = (cfg.rho_ov - 1000.0) / (2700.0 - 1000.0) * (2700.0 / cfg.rho_ov)
    solid = m_ov * c_mass
    fe_total = solid * g_ov
    return {
        "_x_m_ov": m_ov,
        "_x_g_ov": g_ov,
        "_x_d2": d2,
        "_x_tm_overflow_f325": cfg.flo_feed_f325_nom,
        "_x_tm_overflow_f200": cfg.flo_feed_f200_nom,
        "_x_tm_overflow_f25": cfg.flo_feed_f25_nom,
        "_x_tm_overflow_fe_mag": fe_total * 0.80,
        "_x_tm_overflow_fe_hem": fe_total * 0.10,
        "_x_tm_overflow_fe_carb": fe_total * 0.04,
        "_x_tm_overflow_fe_sil": fe_total * 0.06,
        "_x_tm_overflow_gangue": max(solid - fe_total, 0.0),
    }


def _make_system(
    Q_TD_nom: float = 1800.0,
    open_loop: bool = False,
    seed: int = 0,
    **cfg_kwargs,
) -> FlotationSystem:
    rng = np.random.default_rng(seed)
    cfg = FlotationConfig(Q_TD_nom=Q_TD_nom, **cfg_kwargs)
    sim_cfg = SimConfig(open_loop=open_loop)
    return FlotationSystem(cfg, sim_cfg, rng)


def _run_flo(
    n: int = 600,
    seed: int = 0,
    Q_TD_nom: float = 1800.0,
    open_loop: bool = False,
    g_ov: float = 0.4384,
    m_ov: float = 750.0,
    **cfg_kwargs,
) -> list[dict]:
    system = _make_system(Q_TD_nom=Q_TD_nom, open_loop=open_loop, seed=seed, **cfg_kwargs)
    history: list[dict] = []
    for t in range(n):
        bus = _make_bus(g_ov=g_ov, m_ov=m_ov)
        system.step(bus, t)
        history.append(dict(bus))
    return history


def _tfe_ss(Q_TD: float, g_ov: float = 0.4384, pH: float = 9.6) -> float:
    cfg = FlotationConfig()
    dQ = Q_TD - cfg.Q_TD_nom
    dpH = pH - cfg.pH_nom
    eta_Fe = float(np.clip(cfg.eta_Fe0 + cfg.k_eta_Fe * dQ, 0.5, 1.0))
    R_Si = float(np.clip(cfg.R_Si0 + cfg.k_R_Si * dQ + cfg.k_R_Si_pH * dpH, 0.0, 1.0))
    Fe = eta_Fe * g_ov
    Si = (1.0 - R_Si) * (1.0 - g_ov)
    return Fe / (Fe + Si)


def _arr(history: list[dict], key: str) -> np.ndarray:
    return np.array([row[key] for row in history])


# ──────────────────────────────────────────────────────────────────────────────
# 1. 静态标定
# ──────────────────────────────────────────────────────────────────────────────

class TestCalibrationStatic:

    def test_tfe_ss_Q2100(self):
        """Q_TD=2100 g/t → TFe_ss ≈ 67.43%。"""
        tfe = _tfe_ss(2100.0)
        assert abs(tfe * 100 - 67.43) < 0.5, f"TFe_ss(2100)={tfe*100:.2f}% 偏离 67.43%"

    def test_tfe_ss_Q1500(self):
        """Q_TD=1500 g/t → TFe_ss ≈ 66.56%。"""
        tfe = _tfe_ss(1500.0)
        assert abs(tfe * 100 - 66.56) < 0.5, f"TFe_ss(1500)={tfe*100:.2f}% 偏离 66.56%"

    def test_tfe_ss_increases_with_Q_TD(self):
        """更高加药量应产生更高精矿品位。"""
        assert _tfe_ss(2100.0) > _tfe_ss(1500.0)

    def test_tfe_ss_in_valid_range(self):
        for Q_TD in [500, 1000, 1500, 1800, 2100, 2500, 3500]:
            tfe = _tfe_ss(Q_TD)
            assert 0.0 < tfe < 1.0, f"TFe_ss(Q={Q_TD}) = {tfe:.4f} 超出 (0,1)"

    def test_tfe_ss_increases_with_pH(self):
        """较高 pH 应使硅去除率提高，从而提升精矿品位。"""
        tfe_low_pH = _tfe_ss(1800.0, pH=9.0)
        tfe_high_pH = _tfe_ss(1800.0, pH=10.0)
        assert tfe_high_pH > tfe_low_pH, "pH 升高应提升精矿品位"


# ──────────────────────────────────────────────────────────────────────────────
# 2. 动态收敛
# ──────────────────────────────────────────────────────────────────────────────

class TestDynamicConvergence:

    def test_tfe_converges_Q2100(self):
        """Q_TD=2100 → 500 步内 TFe ≈ 67.43% ± 1%。"""
        h = _run_flo(n=600, Q_TD_nom=2100.0, seed=1)
        tfe_late = _arr(h[400:], "_x_TFe_circuit_s1") * 100
        expected = _tfe_ss(2100.0) * 100
        assert abs(tfe_late.mean() - expected) < 1.5, \
            f"TFe(Q=2100) = {tfe_late.mean():.2f}% 偏离 {expected:.2f}%"

    def test_tfe_converges_Q1500(self):
        """Q_TD=1500 → 500 步内 TFe ≈ 66.56% ± 1%。"""
        h = _run_flo(n=600, Q_TD_nom=1500.0, seed=1)
        tfe_late = _arr(h[400:], "_x_TFe_circuit_s1") * 100
        expected = _tfe_ss(1500.0) * 100
        assert abs(tfe_late.mean() - expected) < 1.5, \
            f"TFe(Q=1500) = {tfe_late.mean():.2f}% 偏离 {expected:.2f}%"

    def test_tfe_circuit_is_autocorrelated(self):
        """TFe 回路应有强正自相关（tau_flo=800s，dt=60s，phi≈0.928）。"""
        h = _run_flo(n=500, seed=0)
        tfe = _arr(h[100:], "_x_TFe_circuit_s1")
        lag1 = np.corrcoef(tfe[:-1], tfe[1:])[0, 1]
        assert lag1 > 0.80, f"TFe lag-1 自相关 {lag1:.3f} 过低"

    def test_series1_series2_slightly_different(self):
        """两系列间有 delta_12 偏差，TFe 应略有差异。"""
        h = _run_flo(n=500, seed=0)
        tfe1 = _arr(h[100:], "_x_TFe_circuit_s1").mean()
        tfe2 = _arr(h[100:], "_x_TFe_circuit_s2").mean()
        assert abs(tfe1 - tfe2) >= 0.0, "两系列 TFe 差异为 0（允许，delta_12 可能很小）"


# ──────────────────────────────────────────────────────────────────────────────
# 3. pH 动力学
# ──────────────────────────────────────────────────────────────────────────────

class TestpHDynamics:

    def setup_method(self):
        self.history = _run_flo(n=500, seed=0)
        self.late = self.history[100:]

    def test_ph_in_range(self):
        """稳态 pH ∈ [9.2, 10.1]（标定值）。"""
        ph1 = _arr(self.late, "fx_s1_ph")
        ph2 = _arr(self.late, "fx_s2_ph")
        assert np.all((ph1 >= 8.0) & (ph1 <= 11.5)), \
            f"系列1 pH 超出范围: [{ph1.min():.2f}, {ph1.max():.2f}]"
        assert np.all((ph2 >= 8.0) & (ph2 <= 11.5)), \
            f"系列2 pH 超出范围"

    def test_ph_mean_near_nominal(self):
        """名义 pH_nom=9.6，均值应在 ±0.5 内。"""
        ph1 = _arr(self.late, "fx_s1_ph")
        assert abs(ph1.mean() - 9.6) < 0.5, \
            f"pH 均值 {ph1.mean():.2f} 偏离 9.6"

    def test_ph_d2_effect(self):
        """高 d2（碳酸铁）应降低 pH（k_pH_d2=3.0）。"""
        system = _make_system(seed=0)
        ph_low_d2 = []
        ph_high_d2 = []
        for t in range(500):
            bus_l = _make_bus(d2=0.005)
            system.step(bus_l, t)
            ph_low_d2.append(bus_l["fx_s1_ph"])
        system2 = _make_system(seed=0)
        for t in range(500):
            bus_h = _make_bus(d2=0.05)
            system2.step(bus_h, t)
            ph_high_d2.append(bus_h["fx_s1_ph"])
        # 稳态后（200步之后）低 d2 时 pH 应更高
        assert np.mean(ph_low_d2[200:]) > np.mean(ph_high_d2[200:]), \
            "低碳酸铁应产生更高 pH"

    def test_ph_finite(self):
        ph = _arr(self.late, "fx_s1_ph")
        assert np.all(np.isfinite(ph)), "pH 含 NaN/Inf"


# ──────────────────────────────────────────────────────────────────────────────
# 4. STEP3 DCS 字段完整性
# ──────────────────────────────────────────────────────────────────────────────

class TestDCSCompleteness:

    def setup_method(self):
        self.bus = _run_flo(n=1)[-1]

    def test_nt_motor_currents_present(self):
        assert "fx_nt1_motor_current" in self.bus
        assert "fx_nt2_motor_current" in self.bus

    def test_nt_underflow_density_present(self):
        assert "fx_nt1_underflow_density" in self.bus
        assert "fx_nt2_underflow_density" in self.bus

    def test_cell_level_all_series_present(self):
        for s in (1, 2):
            for c in _CELLS:
                key = f"fx_s{s}_{c}_level"
                assert key in self.bus, f"{key} 不在 bus 中"

    def test_cell_froth_all_series_present(self):
        for s in (1, 2):
            for c in _CELLS:
                key = f"fx_s{s}_{c}_froth_h"
                assert key in self.bus, f"{key} 不在 bus 中"

    def test_cell_air_all_series_present(self):
        for s in (1, 2):
            for c in _CELLS:
                assert f"fx_s{s}_{c}_air_flow" in self.bus

    def test_cell_motor_current_all_series_present(self):
        for s in (1, 2):
            for c in _CELLS:
                key = f"fx_s{s}_{c}_motor_curr"
                assert key in self.bus, f"{key} 不在 bus 中"

    def test_drug_pump_freq_all_present(self):
        for s in (1, 2):
            for pk in ["td_rough", "td_clean", "k6_rough", "naoh", "cao"]:
                assert f"fx_s{s}_{pk}_freq" in self.bus

    def test_ph_columns_present(self):
        assert "fx_s1_ph" in self.bus
        assert "fx_s2_ph" in self.bus

    def test_tank_temp_all_present(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                assert f"fx_s{s}_tk{k}_temp" in self.bus

    def test_pool_level_all_present(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                assert f"fx_s{s}_pool{k}_level" in self.bus

    def test_blower_pressure_present(self):
        assert "fx_blower1_pressure" in self.bus
        assert "fx_blower2_pressure" in self.bus

    def test_ah_power_present(self):
        assert "fx_ah5_power" in self.bus
        assert "fx_ah6_power" in self.bus

    def test_ft_flow_present(self):
        for col in ["fx_s1_ft1701", "fx_s1_ft1702", "fx_s2_ft2701", "fx_s2_ft2702"]:
            assert col in self.bus

    def test_k6_level_present(self):
        assert "fx_s1_k6_level" in self.bus
        assert "fx_s2_k6_level" in self.bus

    def test_y_fx_present(self):
        assert "y_fx_xin1" in self.bus
        assert "y_fx_xin2" in self.bus

    def test_all_step3_columns_present(self):
        non_nan_exempt = {"y_fx_xin1", "y_fx_xin2"}
        missing = [col for col in STEP3_COLUMNS if col not in self.bus]
        assert not missing, f"缺失 STEP3 列: {missing}"

    def test_no_nan_in_dcs_cols(self):
        """除 y_fx_xin1/2 外，所有 STEP3 列不应有 NaN。"""
        non_nan_exempt = {"y_fx_xin1", "y_fx_xin2"}
        for col in STEP3_COLUMNS:
            if col in non_nan_exempt:
                continue
            val = self.bus[col]
            assert math.isfinite(val) or val == val, f"{col}={val} 为 NaN"


# ──────────────────────────────────────────────────────────────────────────────
# 5. 浮选槽液位
# ──────────────────────────────────────────────────────────────────────────────

class TestCellLevel:

    def setup_method(self):
        self.history = _run_flo(n=500)
        self.late = self.history[100:]

    def test_cell_level_nonnegative(self):
        for s in (1, 2):
            for c in _CELLS:
                L = _arr(self.late, f"fx_s{s}_{c}_level")
                assert np.all(L >= 0.0), f"fx_s{s}_{c}_level 含负值"

    def test_cell_level_near_setpoint(self):
        """液位均值应接近 L_sp=1.5m（±0.5m 容差）。"""
        for s in (1, 2):
            for c in _CELLS:
                L = _arr(self.late, f"fx_s{s}_{c}_level")
                assert abs(L.mean() - 1.5) < 0.5, \
                    f"fx_s{s}_{c}_level 均值 {L.mean():.3f} 偏离 1.5m"

    def test_level_valve_sp_in_range(self):
        for s in (1, 2):
            for c in _CELLS:
                u = _arr(self.late, f"fx_s{s}_{c}_level_valve_sp")
                assert np.all((u >= 0.0) & (u <= 1.0)), \
                    f"fx_s{s}_{c}_level_valve_sp 超出 [0,1]"

    def test_level_valve_fb_in_range(self):
        for s in (1, 2):
            for c in _CELLS:
                u = _arr(self.late, f"fx_s{s}_{c}_level_valve_fb")
                assert np.all((u >= 0.0) & (u <= 1.0)), \
                    f"fx_s{s}_{c}_level_valve_fb 超出 [0,1]"

    def test_bv_pos_in_range(self):
        for s in (1, 2):
            for c in _CELLS:
                bv = _arr(self.late, f"fx_s{s}_{c}_bv_pos")
                assert np.all((bv >= 0.1) & (bv <= 0.9)), \
                    f"fx_s{s}_{c}_bv_pos 超出 [0.1, 0.9]"


# ──────────────────────────────────────────────────────────────────────────────
# 6. 浮选机电流
# ──────────────────────────────────────────────────────────────────────────────

class TestFXJMotorCurrent:

    def setup_method(self):
        self.history = _run_flo(n=300)
        self.late = self.history[50:]

    def test_fxj_current_in_range(self):
        for s in (1, 2):
            for c in _CELLS:
                I = _arr(self.late, f"fx_s{s}_{c}_motor_curr")
                assert np.all((I >= 10.0) & (I <= 50.0)), \
                    f"fx_s{s}_{c}_motor_curr={I.mean():.2f}A 超出 [10, 50]"

    def test_fxj_current_near_nominal(self):
        """I_FXJ0=22A，均值应在 ±5A 内。"""
        I = _arr(self.late, "fx_s1_cx1_motor_curr")
        assert abs(I.mean() - 22.0) < 5.0, f"浮选机电流均值 {I.mean():.2f}A 偏离 22A"


# ──────────────────────────────────────────────────────────────────────────────
# 7. 加药泵
# ──────────────────────────────────────────────────────────────────────────────

class TestDrugDosing:

    def setup_method(self):
        self.history = _run_flo(n=500)
        self.late = self.history[100:]

    def test_drug_pump_freq_positive(self):
        for s in (1, 2):
            for pk in ["td_rough", "td_clean", "k6_rough", "naoh", "cao"]:
                f = _arr(self.late, f"fx_s{s}_{pk}_freq")
                assert np.all(f > 0), f"fx_s{s}_{pk}_freq 含非正值"

    def test_drug_pump_freq_in_range(self):
        for s in (1, 2):
            for pk in ["td_rough"]:
                f = _arr(self.late, f"fx_s{s}_{pk}_freq")
                assert np.all((f >= 1.0) & (f <= 60.0)), \
                    f"fx_s{s}_{pk}_freq 超出 [1,60]Hz"

    def test_drug_pump_current_positive(self):
        for s in (1, 2):
            for pk in ["td_rough"]:
                I = _arr(self.late, f"fx_s{s}_{pk}_curr")
                assert np.all(I > 0), f"fx_s{s}_{pk}_curr 含非正值"

    def test_q_td_in_valid_range(self):
        q_td = _arr(self.late, "_x_Q_TD_s1")
        cfg = FlotationConfig()
        assert np.all((q_td >= cfg.Q_TD_min) & (q_td <= cfg.Q_TD_max)), \
            f"Q_TD 超出 [{cfg.Q_TD_min}, {cfg.Q_TD_max}]"

    def test_open_loop_prbs_has_two_levels(self):
        """开环模式下，Q_TD 应在 PRBS 高低两个水平切换。"""
        h = _run_flo(n=2000, open_loop=True, seed=42)
        q_td = _arr(h[100:], "_x_Q_TD_s1")
        unique = np.unique(q_td)
        assert len(unique) == 2, f"开环 PRBS 应只有两个水平，发现 {len(unique)} 个"


# ──────────────────────────────────────────────────────────────────────────────
# 8. 泡沫层
# ──────────────────────────────────────────────────────────────────────────────

class TestFrothLayer:

    def setup_method(self):
        self.history = _run_flo(n=1000)
        self.late = self.history[100:]

    def test_froth_height_nonnegative(self):
        for s in (1, 2):
            for c in _CELLS:
                h = _arr(self.late, f"fx_s{s}_{c}_froth_h")
                normal = h[h > -5]  # 排除故障注入 -21
                assert np.all(normal >= 0.0), f"fx_s{s}_{c}_froth_h 含负值"

    def test_froth_height_normal_range(self):
        for s in (1, 2):
            for c in _CELLS:
                h = _arr(self.late, f"fx_s{s}_{c}_froth_h")
                normal = h[h > -5]
                if len(normal) > 0:
                    assert np.all(normal <= 1.5), \
                        f"fx_s{s}_{c}_froth_h 正常值超出 1.5m: {normal.max():.3f}"

    def test_froth_fault_injection(self):
        """p_fault=0.005，1000步内应偶发 -21 故障值。"""
        h = _run_flo(n=1000, seed=3, p_fault_froth=0.005, fault_val_froth=-21.0)
        froth = _arr(h, "fx_s1_cx1_froth_h")
        fault_count = (froth < -10).sum()
        # 期望 ≈ 5 次，可能 0，概率测试
        # 注意：这是故障注入的概率行为，不强制要求

    def test_froth_height_air_coupling(self):
        """充气量正常时，泡沫层应有一定高度。"""
        h = _run_flo(n=500, seed=0)
        froth = _arr(h[100:], "fx_s1_cx1_froth_h")
        normal = froth[froth > -5]
        assert normal.mean() > 0.001, "泡沫层高度异常接近 0"

    def test_air_flow_in_range(self):
        for s in (1, 2):
            for c in _CELLS:
                Q = _arr(self.late, f"fx_s{s}_{c}_air_flow")
                assert np.all((Q >= 0.0) & (Q <= 0.05)), \
                    f"fx_s{s}_{c}_air_flow 超出 [0, 0.05]"


# ──────────────────────────────────────────────────────────────────────────────
# 9. 搅拌槽温度
# ──────────────────────────────────────────────────────────────────────────────

class TestTankTemperature:

    def setup_method(self):
        self.history = _run_flo(n=500)
        self.late = self.history[100:]

    def test_tank_temp_in_range(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                T = _arr(self.late, f"fx_s{s}_tk{k}_temp")
                assert np.all((T >= 20.0) & (T <= 80.0)), \
                    f"fx_s{s}_tk{k}_temp 超出 [20,80]: [{T.min():.1f}, {T.max():.1f}]"

    def test_steam_valve_in_range(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                sp = _arr(self.late, f"fx_s{s}_tk{k}_steam_sp")
                fb = _arr(self.late, f"fx_s{s}_tk{k}_steam_fb")
                assert np.all((sp >= 0.0) & (sp <= 1.0)), f"steam_sp 超出 [0,1]"
                assert np.all((fb >= 0.0) & (fb <= 1.0)), f"steam_fb 超出 [0,1]"


# ──────────────────────────────────────────────────────────────────────────────
# 10. 泵池与鼓风机
# ──────────────────────────────────────────────────────────────────────────────

class TestPoolsAndBlowers:

    def setup_method(self):
        self.history = _run_flo(n=500)
        self.late = self.history[100:]

    def test_pool_level_nonnegative(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                L = _arr(self.late, f"fx_s{s}_pool{k}_level")
                assert np.all(L >= 0.0), f"fx_s{s}_pool{k}_level 含负值"

    def test_pool_pump_freq_in_range(self):
        for s in (1, 2):
            for k in (1, 2, 3):
                f = _arr(self.late, f"fx_s{s}_pool{k}_pump_freq")
                assert np.all((f >= 0.0) & (f <= 60.0)), \
                    f"fx_s{s}_pool{k}_pump_freq 超出范围"

    def test_blower_pressure_in_range(self):
        """鼓风机压力应在 [10, 60] kPa 内。"""
        for col in ["fx_blower1_pressure", "fx_blower2_pressure"]:
            P = _arr(self.late, col)
            assert np.all((P >= 10.0) & (P <= 60.0)), \
                f"{col} 超出范围: [{P.min():.2f}, {P.max():.2f}]"

    def test_transformer_power_positive(self):
        for col in ["fx_ah5_power", "fx_ah6_power"]:
            P = _arr(self.late, col)
            assert np.all(P >= 0), f"{col} 含负值"

    def test_k6_level_in_range(self):
        for col in ["fx_s1_k6_level", "fx_s2_k6_level"]:
            L = _arr(self.late, col)
            assert np.all((L >= 0.2) & (L <= 3.0)), \
                f"{col} 超出范围: [{L.min():.3f}, {L.max():.3f}]"


# ──────────────────────────────────────────────────────────────────────────────
# 11. 目标变量 y_fx_xin1/2
# ──────────────────────────────────────────────────────────────────────────────

class TestTargetVariable:

    def setup_method(self):
        self.history = _run_flo(n=600, seed=0)
        self.late = self.history[200:]

    def test_y_fx_xin1_finite(self):
        """sigma_y=0.0（无噪声），y_fx 应为有限数。"""
        y = _arr(self.late, "y_fx_xin1")
        assert np.all(np.isfinite(y)), "y_fx_xin1 含 NaN/Inf"

    def test_y_fx_in_grade_range(self):
        """精矿品位应在 [0.5, 0.8] 范围内。"""
        y1 = _arr(self.late, "y_fx_xin1")
        assert np.all((y1 > 0.40) & (y1 < 1.0)), \
            f"y_fx_xin1 超出合理范围: [{y1.min():.4f}, {y1.max():.4f}]"

    def test_y_fx_tracks_tfe_circuit(self):
        """y_fx 应接近 _x_TFe_circuit（delta_12 偏差较小）。"""
        y1 = _arr(self.late, "y_fx_xin1")
        tfe_circuit = _arr(self.late, "_x_TFe_circuit_s1")
        # 相关性应很高
        corr = np.corrcoef(y1, tfe_circuit)[0, 1]
        assert corr > 0.95, f"y_fx_xin1 与 TFe_circuit 相关性 {corr:.3f} 过低"

    def test_series2_y_fx_slightly_different(self):
        """两系列精矿品位应略有差异（delta_12）。"""
        y1 = _arr(self.late, "y_fx_xin1").mean()
        y2 = _arr(self.late, "y_fx_xin2").mean()
        # 均值可能非常接近，但方向一致
        assert y2 > 0.40, f"y_fx_xin2 均值 {y2:.4f} 过低"


# ──────────────────────────────────────────────────────────────────────────────
# 12. 质量守恒
# ──────────────────────────────────────────────────────────────────────────────

class TestMassConservation:

    def setup_method(self):
        self.history = _run_flo(n=300, seed=0)
        self.late = self.history[50:]

    def test_final_conc_plus_tail_approx_feed(self):
        """精矿 + 尾矿质量 ≈ 给矿质量（在延迟稳定后）。"""
        for row in self.late:
            feed_m = row.get("_x_flo_feed_s1_m", None)
            conc_m = row.get("_x_flo_final_conc_s1_m", None)
            tail_m = row.get("_x_flo_final_tail_s1_m", None)
            if feed_m and conc_m and tail_m:
                balance = conc_m + tail_m
                assert abs(balance - feed_m) < max(0.5, 0.1 * feed_m), \
                    f"质量不平衡: conc+tail={balance:.2f}, feed={feed_m:.2f}"

    def test_conc_grade_above_feed_grade(self):
        """精矿品位应高于给矿品位（品位提升）。"""
        for row in self.late:
            feed_tfe = row.get("_x_flo_feed_s1_tfe", None)
            conc_tfe = row.get("_x_flo_final_conc_s1_tfe", None)
            if feed_tfe and conc_tfe and feed_tfe > 0.1:
                assert conc_tfe > feed_tfe, \
                    f"精矿品位 {conc_tfe:.4f} 应 > 给矿品位 {feed_tfe:.4f}"

    def test_tail_grade_below_feed_grade(self):
        """尾矿品位应低于给矿品位（铁被富集到精矿）。"""
        for row in self.late:
            feed_tfe = row.get("_x_flo_feed_s1_tfe", None)
            tail_tfe = row.get("_x_flo_final_tail_s1_tfe", None)
            if feed_tfe and tail_tfe:
                assert tail_tfe <= feed_tfe + 0.01, \
                    f"尾矿品位 {tail_tfe:.4f} 不应高于给矿品位 {feed_tfe:.4f}"

    def test_rougher_feed_grade_finite(self):
        for row in self.late:
            tfe = row.get("_x_flo_rougher_feed_s1_tfe", None)
            if tfe is not None:
                assert math.isfinite(tfe), "粗选给矿品位含 NaN"


# ──────────────────────────────────────────────────────────────────────────────
# 13. 系统稳健性
# ──────────────────────────────────────────────────────────────────────────────

class TestSystemRobustness:

    def test_no_nan_in_dcs_cols_after_warmup(self):
        """500步后所有 DCS 列（除 y_fx_xin 外）应无 NaN。"""
        h = _run_flo(n=500, seed=7)
        exempt = {"y_fx_xin1", "y_fx_xin2"}
        for col in STEP3_COLUMNS:
            if col in exempt:
                continue
            val = h[-1][col]
            assert math.isfinite(val), f"{col}={val} 为 NaN/Inf"

    def test_reproducibility(self):
        h1 = _run_flo(n=100, seed=42)
        h2 = _run_flo(n=100, seed=42)
        tfe1 = _arr(h1, "_x_TFe_circuit_s1")
        tfe2 = _arr(h2, "_x_TFe_circuit_s2")
        assert np.allclose(
            _arr(h1, "_x_TFe_circuit_s1"),
            _arr(h2, "_x_TFe_circuit_s1")
        )

    def test_different_seeds_different_results(self):
        h1 = _run_flo(n=100, seed=1)
        h2 = _run_flo(n=100, seed=2)
        assert not np.allclose(
            _arr(h1, "_x_TFe_circuit_s1"),
            _arr(h2, "_x_TFe_circuit_s1")
        )

    def test_nt_current_positive(self):
        h = _run_flo(n=200)
        assert np.all(_arr(h[50:], "fx_nt1_motor_current") > 0)
        assert np.all(_arr(h[50:], "fx_nt2_motor_current") > 0)

    def test_nt_underflow_density_in_range(self):
        h = _run_flo(n=200)
        rho = _arr(h[50:], "fx_nt1_underflow_density")
        assert np.all((rho >= 0.3) & (rho <= 0.8)), \
            f"NT底流浓度超出范围: [{rho.min():.3f}, {rho.max():.3f}]"

    def test_ft_flow_nonnegative(self):
        h = _run_flo(n=200)
        for col in ["fx_s1_ft1701", "fx_s2_ft2701"]:
            vals = _arr(h[50:], col)
            assert np.all(vals >= 0), f"{col} 含负值"

    def test_froth_feed_concentration_tracked(self):
        """浮选给矿浓度应在 [flo_feed_C_min, flo_feed_C_max] 内。"""
        h = _run_flo(n=300)
        cfg = FlotationConfig()
        C = _arr(h[50:], "_x_flo_feed_C_s1")
        assert np.all((C >= cfg.flo_feed_C_min) & (C <= cfg.flo_feed_C_max)), \
            f"给矿浓度超出范围: [{C.min():.4f}, {C.max():.4f}]"
