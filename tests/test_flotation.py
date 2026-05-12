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
) -> FlotationSystem:
    rng = np.random.default_rng(seed)
    cfg = FlotationConfig(Q_TD_nom=Q_TD_nom)
    sim_cfg = SimConfig(open_loop=open_loop)
    return FlotationSystem(cfg, sim_cfg, rng)


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
            if not (0.0 <= abs(v) < 1e12):  # also catches NaN since NaN < 1e12 is False
                bad.append((col, v))
            elif v != v:  # explicit NaN check
                bad.append((col, v))
        assert not bad, f"异常值：{bad[:5]}"

    def test_step3_columns_count(self) -> None:
        """STEP3_COLUMNS 应恰好含 172 列（170 DCS + 2 目标）。"""
        assert len(STEP3_COLUMNS) == 172, f"实际列数：{len(STEP3_COLUMNS)}"


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
