"""
浮选段单元测试。

验收标准：
  - 静态标定点：Q_TD=2100 → TFe ≈ 67.43 % (±0.5 %)；
                Q_TD=1500 → TFe ≈ 66.56 % (±0.5 %)
  - 动态收敛：稳态 TFe 在 500 步内与静态预期一致
  - 稳态 pH ∈ [9.2, 10.1]
  - 所有 STEP3_COLUMNS 均存在于 bus，且无 NaN/Inf（y_fx_xin1/2 除外）
  - 泡沫层故障注入：1000 步内出现 -21 异常值
"""

from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import FlotationConfig, SimConfig
from sim.layers.flotation import FlotationSystem
from sim.output.schema import STEP3_COLUMNS

MASS_COMPONENTS = ("fe_mag", "fe_hem", "fe_carb", "fe_sil", "gangue")


# ── 辅助函数：创建最小化 bus ────────────────────────────────────────────
def _make_bus(g_ov: float = 0.4384, m_ov: float = 750.0, d2: float = 0.018) -> dict:
    return {
        "_x_m_ov": m_ov,
        "_x_g_ov": g_ov,
        "_x_d2": d2,
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


def _make_tm_component_bus(g_ov: float = 0.4384, m_ov: float = 750.0) -> dict:
    cfg = FlotationConfig()
    c_mass_nom = (cfg.rho_ov - 1000.0) / (2700.0 - 1000.0) * (2700.0 / cfg.rho_ov)
    solid = m_ov * c_mass_nom
    fe_total = solid * g_ov
    bus = _make_bus(g_ov=g_ov, m_ov=m_ov)
    bus.update({
        "_x_tm_overflow_f325": cfg.flo_feed_f325_nom,
        "_x_tm_overflow_f200": cfg.flo_feed_f200_nom,
        "_x_tm_overflow_f25": cfg.flo_feed_f25_nom,
        "_x_tm_overflow_fe_mag": fe_total * 0.80,
        "_x_tm_overflow_fe_hem": fe_total * 0.10,
        "_x_tm_overflow_fe_carb": fe_total * 0.04,
        "_x_tm_overflow_fe_sil": fe_total * 0.06,
        "_x_tm_overflow_gangue": solid - fe_total,
    })
    return bus


# ── 1. 静态标定点（纯公式，无噪声）─────────────────────────────────────

class TestCalibrationStatic:
    """TFe_ss 公式标定：两点验证。"""

    def _tfe(self, Q_TD: float, g_ov: float = 0.4384, pH: float = 9.6) -> float:
        cfg = FlotationConfig()
        dQ = Q_TD - cfg.Q_TD_nom
        dpH = pH - cfg.pH_nom
        eta_Fe = float(np.clip(cfg.eta_Fe0 + cfg.k_eta_Fe * dQ, 0.5, 1.0))
        R_Si = float(np.clip(cfg.R_Si0 + cfg.k_R_Si * dQ + cfg.k_R_Si_pH * dpH, 0.0, 1.0))
        Fe = eta_Fe * g_ov
        Si = (1.0 - R_Si) * (1.0 - g_ov)
        return Fe / (Fe + Si)

    def test_Q_TD_2100(self) -> None:
        tfe = self._tfe(2100.0)
        assert abs(tfe * 100 - 67.43) < 0.5, f"TFe@Q_TD=2100: {tfe*100:.3f}%"

    def test_Q_TD_1500(self) -> None:
        tfe = self._tfe(1500.0)
        assert abs(tfe * 100 - 66.56) < 0.5, f"TFe@Q_TD=1500: {tfe*100:.3f}%"

    def test_tail_Q_TD_2100(self) -> None:
        """尾矿品位验证（约 12.86 %）。"""
        cfg = FlotationConfig()
        Q_TD = 2100.0
        g_ov = 0.4384
        dQ = Q_TD - cfg.Q_TD_nom
        eta_Fe = float(np.clip(cfg.eta_Fe0 + cfg.k_eta_Fe * dQ, 0.5, 1.0))
        R_Si = float(np.clip(cfg.R_Si0 + cfg.k_R_Si * dQ, 0.0, 1.0))
        Fe_tail = (1.0 - eta_Fe) * g_ov
        Si_tail = R_Si * (1.0 - g_ov)
        tail = Fe_tail / (Fe_tail + Si_tail)
        assert abs(tail * 100 - 12.86) < 1.5, f"尾矿@Q_TD=2100: {tail*100:.3f}%"


# ── 2. 动态收敛测试 ──────────────────────────────────────────────────────

def _run_steps(
    flo: FlotationSystem,
    n: int,
    g_ov: float = 0.4384,
    m_ov: float = 750.0,
    d2: float = 0.018,
) -> None:
    for t in range(n):
        bus = _make_bus(g_ov=g_ov, m_ov=m_ov, d2=d2)
        flo.step(bus, t)


class TestDynamicConvergence:

    def test_tfe_convergence_Q_TD_2100(self) -> None:
        """Q_TD_nom=2100，600 步后 TFe 应收敛至 67.43 % ± 1 %。"""
        flo = _make_system(Q_TD_nom=2100.0, seed=7)
        _run_steps(flo, 600)
        bus = _make_bus()
        flo.step(bus, 600)
        tfe_s1 = bus["_x_TFe_circuit_s1"] * 100
        assert abs(tfe_s1 - 67.43) < 1.0, f"TFe_s1@600步={tfe_s1:.3f}%"

    def test_tfe_convergence_Q_TD_1500(self) -> None:
        """Q_TD_nom=1500，600 步后 TFe 应收敛至 66.56 % ± 1 %。"""
        flo = _make_system(Q_TD_nom=1500.0, seed=8)
        _run_steps(flo, 600)
        bus = _make_bus()
        flo.step(bus, 600)
        tfe_s1 = bus["_x_TFe_circuit_s1"] * 100
        assert abs(tfe_s1 - 66.56) < 1.0, f"TFe_s1@600步={tfe_s1:.3f}%"

    def test_pH_steady_state(self) -> None:
        """稳态 pH 应在 [9.2, 10.1] 范围内。"""
        flo = _make_system(seed=9)
        _run_steps(flo, 300)
        bus = _make_bus()
        flo.step(bus, 300)
        ph = bus["fx_s1_ph"]
        assert 9.2 <= ph <= 10.1, f"稳态 pH = {ph:.3f}"


# ── 3. 输出列完整性 & 有效性 ─────────────────────────────────────────────

class TestComponentFlotation:

    def test_final_product_component_balance(self) -> None:
        flo = _make_system(seed=31, delay_steps_tm=0)
        for t in range(650):
            bus = _make_tm_component_bus()
            flo.step(bus, t)

        for prefix in ["_x_flo_feed_s1", "_x_flo_final_conc_s1", "_x_flo_final_tail_s1"]:
            for key in ["m", "tfe", *MASS_COMPONENTS]:
                assert f"{prefix}_{key}" in bus

        feed_m = bus["_x_flo_feed_s1_m"]
        product_m = bus["_x_flo_final_conc_s1_m"] + bus["_x_flo_final_tail_s1_m"]
        assert np.isclose(product_m, feed_m, rtol=0, atol=1e-6)

        feed_fe = sum(
            bus[f"_x_flo_feed_s1_{key}"] for key in MASS_COMPONENTS if key != "gangue"
        )
        product_fe = sum(
            bus[f"_x_flo_final_conc_s1_{key}"] + bus[f"_x_flo_final_tail_s1_{key}"]
            for key in MASS_COMPONENTS
            if key != "gangue"
        )
        assert np.isclose(product_fe, feed_fe, rtol=0, atol=1e-6)

    def test_final_grade_and_tail_grade_anchors(self) -> None:
        flo = _make_system(seed=32, delay_steps_tm=0)
        for t in range(650):
            bus = _make_tm_component_bus()
            flo.step(bus, t)

        assert 0.65 <= bus["_x_flo_final_conc_s1_tfe"] <= 0.69
        assert 0.17 <= bus["_x_flo_final_tail_s1_tfe"] <= 0.30
        assert np.isfinite(bus["y_fx_xin1"])
        assert np.isclose(bus["y_fx_xin1"], bus["_x_TFe_circuit_s1"], atol=1e-12)

    def test_tm_component_grade_changes_final_label(self) -> None:
        flo = _make_system(
            seed=33,
            delay_steps_tm=0,
            tau_flo_pre_thickener=60.0,
        )
        for t in range(120):
            bus = _make_tm_component_bus(g_ov=0.40)
            flo.step(bus, t)
        low_label = bus["_x_TFe_circuit_s1"]

        for t in range(120, 320):
            bus = _make_tm_component_bus(g_ov=0.48)
            flo.step(bus, t)
        high_label = bus["_x_TFe_circuit_s1"]

        assert high_label > low_label + 0.02


class TestOutputColumns:

    def test_all_step3_columns_present(self) -> None:
        """所有 STEP3_COLUMNS 键应存在于 bus。"""
        flo = _make_system(seed=1)
        _run_steps(flo, 50)
        bus = _make_bus()
        flo.step(bus, 50)
        missing = [c for c in STEP3_COLUMNS if c not in bus]
        assert not missing, f"缺失列：{missing}"

    def test_no_nan_inf_except_targets(self) -> None:
        """除 y_fx_xin1/2 外，所有 STEP3_COLUMNS 应无 NaN/Inf。"""
        flo = _make_system(seed=2)
        _run_steps(flo, 100)
        bus = _make_bus()
        flo.step(bus, 100)
        target_keys = {"y_fx_xin1", "y_fx_xin2"}
        bad = []
        for col in STEP3_COLUMNS:
            if col in target_keys:
                continue
            v = bus.get(col, float("nan"))
            if not isinstance(v, float):
                v = float(v)
            if not np.isfinite(v):
                bad.append((col, v))
        assert not bad, f"异常值：{bad[:5]}"

    def test_step3_columns_count(self) -> None:
        """STEP3_COLUMNS 应恰好含 186 列（184 DCS + 2 目标）。"""
        assert len(STEP3_COLUMNS) == 186, f"实际列数：{len(STEP3_COLUMNS)}"

    def test_level_column_is_in_meters(self) -> None:
        """fx_s*_*_level 应为液位（m），典型值应在 [0, 5] m 范围内。"""
        flo = _make_system(seed=3)
        _run_steps(flo, 100)
        bus = _make_bus()
        flo.step(bus, 100)
        level = bus["fx_s1_cx1_level"]
        assert 0.0 <= level <= 5.0, f"fx_s1_cx1_level={level:.3f}，应为液位（m）"

    def test_level_valve_sp_fb_range(self) -> None:
        """valve_sp/fb 应在 [0, 1] 范围（阀门开度）。"""
        flo = _make_system(seed=4)
        _run_steps(flo, 100)
        bus = _make_bus()
        flo.step(bus, 100)
        sp = bus["fx_s1_cx1_level_valve_sp"]
        fb = bus["fx_s1_cx1_level_valve_fb"]
        assert 0.0 <= sp <= 1.0, f"level_valve_sp={sp:.3f}，应在 [0,1]"
        assert 0.0 <= fb <= 1.0, f"level_valve_fb={fb:.3f}，应在 [0,1]"


# ── 4. 泡沫层故障注入 ────────────────────────────────────────────────────

class TestFaultInjection:

    def test_froth_fault_occurs(self) -> None:
        """1000 步内泡沫层应出现 -21 故障值。"""
        flo = _make_system(seed=99)
        fault_seen = False
        for t in range(1000):
            bus = _make_bus()
            flo.step(bus, t)
            for c in ["cx1", "cx2", "cx3", "jx", "sx1", "sx2", "sx3"]:
                if bus.get(f"fx_s1_{c}_froth_h") == -21.0:
                    fault_seen = True
                    break
            if fault_seen:
                break
        assert fault_seen, "1000 步内未观测到泡沫层 -21 故障值"


# ── 5. 开环激励模式 ──────────────────────────────────────────────────────

class TestOpenLoop:

    def test_prbs_switch_occurs(self) -> None:
        """开环模式下 Q_TD 应在 1000 步内切换至少一次。"""
        flo = _make_system(open_loop=True, seed=5)
        Q_states = set()
        for t in range(1000):
            bus = _make_bus()
            flo.step(bus, t)
            Q_states.add(round(bus["_x_Q_TD_s1"], 0))
            if len(Q_states) > 1:
                break
        assert len(Q_states) > 1, f"Q_TD 未切换：{Q_states}"

# ── 6. 信号质量（方差 & 范围）────────────────────────────────────────────

_CELLS_TEST = ["cx1", "cx2", "cx3", "jx", "sx1", "sx2", "sx3"]


class TestSignalQuality:
    """验证之前发现的零方差/钳位 Bug 已修复。"""

    def test_transformer_power_not_clamped(self) -> None:
        """fx_ah5/ah6_power 不应始终钳位在 100 kW（零方差）。"""
        flo = _make_system(seed=20)
        _run_steps(flo, 100)
        powers = []
        for t in range(100, 200):
            bus = _make_bus()
            flo.step(bus, t)
            powers.append(bus["fx_ah5_power"])
        arr = np.array(powers)
        assert arr.mean() > 100.0, f"P_AH 均值 {arr.mean():.1f} kW 应 > 100 kW"
        assert arr.std() > 0.1, f"P_AH 标准差 {arr.std():.2f} kW 应 > 0"

    def test_air_sp_has_variance(self) -> None:
        """air_sp 列应随时间缓慢变化（非零方差），模拟操作员调节。"""
        flo = _make_system(seed=21)
        _run_steps(flo, 200)
        air_sps = []
        for t in range(200, 600):
            bus = _make_bus()
            flo.step(bus, t)
            air_sps.append(bus["fx_s1_cx1_air_sp"])
        arr = np.array(air_sps)
        assert arr.std() > 1e-6, f"air_sp 标准差 {arr.std():.2e} 应 > 0"

    def test_pool_level_responds_to_feed_change(self) -> None:
        """泵池液位应响应给矿量阶跃变化（不再固定不变）。"""
        flo = _make_system(seed=22)
        _run_steps(flo, 200, m_ov=750.0)
        lvl_before = []
        for t in range(200, 250):
            bus = _make_bus(m_ov=750.0)
            flo.step(bus, t)
            lvl_before.append(bus["fx_s1_pool1_level"])
        _run_steps(flo, 200, m_ov=1200.0)
        lvl_after = []
        for t in range(450, 500):
            bus = _make_bus(m_ov=1200.0)
            flo.step(bus, t)
            lvl_after.append(bus["fx_s1_pool1_level"])
        mean_before = float(np.mean(lvl_before))
        mean_after = float(np.mean(lvl_after))
        assert mean_after > mean_before + 0.01, (
            f"泵池液位未响应给矿量增加：{mean_before:.3f}→{mean_after:.3f} m"
        )

    def test_cells_have_different_levels(self) -> None:
        """串联级联后，各槽液位应各自独立（不完全相同）。"""
        flo = _make_system(seed=23)
        for t in range(500):
            bus = _make_bus()
            flo.step(bus, t)
        bus = _make_bus()
        flo.step(bus, 500)
        levels = [bus[f"fx_s1_{c}_level"] for c in _CELLS_TEST]
        level_range = max(levels) - min(levels)
        assert level_range > 0.001, (
            f"所有槽液位完全相同（range={level_range:.6f}），未体现级联差异"
        )
