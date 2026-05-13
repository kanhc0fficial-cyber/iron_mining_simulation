"""
浮选段仿真（第五章）。

物理流程：
  塔磨溢流（延迟 30 min）
  → 浮选前浓缩机（NT-30，2台）
  → 两系列浮选回路（各 7 个槽：CX1/2/3 粗选、JX 精选、SX1/2/3 扫选）
  → 加药网络（TD-II/K6-1/NaOH/CaO）→ pH 动力学 → TFe 精矿品位
  → 泵池 → LabAssayer（时滞 120~240 步）→ y_fx_xin1/2

输出 ~170 个 DCS 变量及 2 个目标变量（y_fx_xin1/2）。

TFe 动力学模型（经考查报告两点标定）：
  eta_Fe(Q_TD) = eta_Fe0 + k_eta_Fe * (Q_TD - Q_TD_nom)
  R_Si(Q_TD, pH) = R_Si0 + k_R_Si * (Q_TD - Q_TD_nom) + k_R_Si_pH * (pH - pH_nom)
  TFe_ss = eta_Fe * g_ov / (eta_Fe * g_ov + (1-R_Si) * (1-g_ov))
  TFe(t+dt) = TFe_ss + (TFe(t) - TFe_ss) * exp(-dt/tau_flo)   [ZOH]
"""

from __future__ import annotations
import math

import numpy as np

from sim.config import FlotationConfig, SimConfig
from sim.utils.buffer import RingBuffer
from sim.utils.sensor import add_noise, inject_fault

_N_CELLS = 7    # 每系列浮选槽数
_N_SERIES = 2   # 系列数
_N_TANKS = 3    # 每系列搅拌槽数
_N_POOLS = 3    # 每系列泵池数
_CELLS = ["cx1", "cx2", "cx3", "jx", "sx1", "sx2", "sx3"]


def _zoh_scalar(x: float, x_ss: float, tau: float, dt: float) -> float:
    """ZOH 精确离散化（标量）。"""
    return x_ss + (x - x_ss) * math.exp(-dt / max(tau, 1e-6))


def _zoh_arr(x: np.ndarray, x_ss: np.ndarray, tau: float, dt: float) -> np.ndarray:
    """ZOH 精确离散化（数组）。"""
    phi = math.exp(-dt / max(tau, 1e-6))
    return x_ss + (x - x_ss) * phi


class FlotationSystem:
    """
    浮选段全部物理计算。

    读取 bus：
      _x_m_ov, _x_g_ov   （塔磨溢流，经 RingBuffer 延迟后使用）
      _x_d2               （碳酸铁含量，影响 pH）

    写入 bus（DCS 可观测量，~170 个）及目标变量（y_fx_xin1/2）。
    """

    def __init__(
        self,
        cfg: FlotationConfig,
        sim_cfg: SimConfig,
        rng: np.random.Generator,
    ) -> None:
        self._cfg = cfg
        self._dt = sim_cfg.dt
        self._rng = rng
        self._open_loop = sim_cfg.open_loop

        dt = sim_cfg.dt

        # ── 段间时滞缓冲区（塔磨溢流 → 浮选，capacity ≥ delay + 1）──────
        cap = cfg.delay_steps_tm + 1
        self._buf_m_ov = RingBuffer(capacity=cap, default=cfg.m_ov_nom)
        self._buf_g_ov = RingBuffer(capacity=cap, default=cfg.g_ov_nom)

        # ── 浮选前浓缩机底流浓度（标量，两系列共用近似值）────────────────
        self._rho_NT = np.full(_N_SERIES, cfg.rho_NT_target, dtype=float)

        # ── 浮选槽液位 & 阀门（shape: (_N_SERIES, _N_CELLS)）──────────────
        self._L_cells = np.full((_N_SERIES, _N_CELLS), cfg.L_init)
        self._u_lv_fb = np.full((_N_SERIES, _N_CELLS), 0.5)
        self._h_froth = np.full((_N_SERIES, _N_CELLS), cfg.h_froth_init)
        self._u_bv = np.full((_N_SERIES, _N_CELLS), 0.5)     # 蝶阀开度（AR(1)）

        # 名义液位阀开度（由稳态流量平衡预计算，使用全流量而非 1/7）
        # 串联回路中每槽均通过总流量 Q_total_s
        Q_in_cell_nom = cfg.m_ov_nom * 1000.0 / cfg.rho_ov / 3600.0
        self._u_lv_nom = float(np.clip(
            Q_in_cell_nom / (cfg.C_v_lv * math.sqrt(max(cfg.L_sp, 0.01))),
            0.05, 0.95,
        ))

        # ── TFe 浮选回路状态（每系列一个）──────────────────────────────
        # 初始化为名义值
        self._TFe_circuit = np.full(_N_SERIES, self._tfe_ss_np(
            np.full(_N_SERIES, cfg.Q_TD_nom),
            np.full(_N_SERIES, cfg.pH_nom),
            np.full(_N_SERIES, cfg.g_ov_nom),
        ))
        self._phi_flo = math.exp(-dt / max(cfg.tau_flo, 1.0))

        # ── 加药量状态（每系列，g/t）──────────────────────────────────
        self._Q_TD = np.full(_N_SERIES, cfg.Q_TD_nom)
        self._prbs_state = np.zeros(_N_SERIES, dtype=int)  # 0=低, 1=高

        # 加药泵频率 AR(1)（每系列 5 种泵，shape (_N_SERIES, 5)）
        _f_noms = np.array([
            cfg.f_td_rough_nom, cfg.f_td_clean_nom, cfg.f_k6_rough_nom,
            cfg.f_naoh_nom, cfg.f_cao_nom,
        ])
        self._f_drug = np.tile(_f_noms, (_N_SERIES, 1))   # shape (2, 5)

        # ── pH 状态（每系列）──────────────────────────────────────────
        self._pH = np.full(_N_SERIES, cfg.pH_init)
        self._phi_pH = math.exp(-dt / max(cfg.tau_pH, 1.0))

        # ── 搅拌槽温度（shape: (_N_SERIES, _N_TANKS)）──────────────────
        self._T_tanks = np.full((_N_SERIES, _N_TANKS), cfg.T_tk_init)
        self._u_TV_fb = np.full((_N_SERIES, _N_TANKS), cfg.u_TV_nom)
        self._phi_tk = math.exp(-dt / max(cfg.tau_tk, 1.0))
        self._phi_TV = math.exp(-dt / max(cfg.tau_TV, 1.0))

        # ── 泵池（shape: (_N_SERIES, _N_POOLS)）──────────────────────
        self._L_pools = np.full((_N_SERIES, _N_POOLS), cfg.L_pool_flo_init)
        self._f_pumps = np.full((_N_SERIES, _N_POOLS), cfg.f_pump_flo_nom)

        # ── 充气量设定值（慢变 AR(1)，每系列每槽独立）──────────────
        self._Q_air_sp = np.full((_N_SERIES, _N_CELLS), cfg.Q_air_nom)

        # ── 鼓风机压力（2 台）────────────────────────────────────────
        self._P_blower = np.full(2, cfg.P_blower_nom)

        # ── K6 贮药箱液位（每系列）───────────────────────────────────
        self._L_k6 = np.full(_N_SERIES, cfg.L_k6_init)

        # ── 化验时滞（RingBuffer + 调度器）──────────────────────────
        self._lab_buf = [
            RingBuffer(capacity=cfg.lab_buf_capacity, default=cfg.g_ov_nom * 0.95),
            RingBuffer(capacity=cfg.lab_buf_capacity, default=(cfg.g_ov_nom + cfg.delta_12) * 0.95),
        ]
        # 化验偏置（两系列微小差异）
        self._delta_12 = np.array([0.0, cfg.delta_12])
        # 下次化验倒计时（步）和当前化验时滞
        self._steps_to_assay = np.array([
            rng.integers(cfg.assay_interval_min, cfg.assay_interval_max + 1),
            rng.integers(cfg.assay_interval_min, cfg.assay_interval_max + 1),
        ], dtype=int)
        self._tau_lab = np.array([
            rng.integers(cfg.tau_lab_min, cfg.tau_lab_max + 1),
            rng.integers(cfg.tau_lab_min, cfg.tau_lab_max + 1),
        ], dtype=int)
        self._y_fx = np.full(_N_SERIES, float("nan"))

    # ─────────────────────────────────────────────────────────────────────
    # 主步进函数
    # ─────────────────────────────────────────────────────────────────────

    def step(self, bus: dict, t: int) -> None:  # noqa: C901
        """推进一步：读取 bus 上游量 → 物理计算 → 写入所有浮选 DCS 变量。"""
        cfg = self._cfg
        dt = self._dt
        rng = self._rng

        # ── 1. 段间时滞：推入当前塔磨溢流，读取延迟值 ──────────────────
        self._buf_m_ov.push(bus["_x_m_ov"])
        self._buf_g_ov.push(bus["_x_g_ov"])
        m_ov_del = self._buf_m_ov.peek(cfg.delay_steps_tm)   # t/h
        g_ov_del = self._buf_g_ov.peek(cfg.delay_steps_tm)   # TFe 品位

        d2 = bus["_x_d2"]   # 碳酸铁含量（影响 pH）

        # 每系列名义总体积流量 m³/s
        Q_total_s = m_ov_del * 1000.0 / cfg.rho_ov / 3600.0  # m³/s

        # ── 2. 浮选前浓缩机 ─────────────────────────────────────────
        # ZOH：底流浓度向目标值收敛
        phi_NT = math.exp(-dt / max(cfg.tau_NT, 1.0))
        self._rho_NT = cfg.rho_NT_target + (self._rho_NT - cfg.rho_NT_target) * phi_NT
        # 固体质量流量（t/h）用于估算电机电流
        c_mass_nom = (cfg.rho_ov - 1000.0) / (2700.0 - 1000.0) * (2700.0 / cfg.rho_ov)
        m_solid_s = m_ov_del * c_mass_nom   # t/h 固体

        I_NT = np.array([
            cfg.I_NT0 + cfg.k_NT_I * m_solid_s + rng.normal(0, cfg.sigma_NT_I),
            cfg.I_NT0 + cfg.k_NT_I * m_solid_s + rng.normal(0, cfg.sigma_NT_I),
        ])
        rho_NT_dcs = self._rho_NT + rng.normal(0, cfg.sigma_NT_rho, _N_SERIES)

        # ── 3. 加药量 & PRBS（每系列）───────────────────────────────
        f_noms = np.array([
            cfg.f_td_rough_nom, cfg.f_td_clean_nom, cfg.f_k6_rough_nom,
            cfg.f_naoh_nom, cfg.f_cao_nom,
        ])

        for s in range(_N_SERIES):
            if self._open_loop:
                # PRBS 切换
                if rng.random() < cfg.p_prbs_switch:
                    self._prbs_state[s] = 1 - self._prbs_state[s]
                self._Q_TD[s] = (
                    cfg.Q_TD_prbs_high if self._prbs_state[s] else cfg.Q_TD_prbs_low
                )
            else:
                # AR(1) 围绕名义值小幅波动
                eta = rng.normal(0, cfg.sigma_drug_f * 5.0)
                self._Q_TD[s] = (
                    cfg.Q_TD_nom
                    + cfg.phi_drug * (self._Q_TD[s] - cfg.Q_TD_nom)
                    + eta
                )
                self._Q_TD[s] = float(np.clip(
                    self._Q_TD[s], cfg.Q_TD_min, cfg.Q_TD_max
                ))

        # 各泵频率 AR(1)（与 Q_TD 成比例 + 独立噪声）
        Q_TD_ratio = self._Q_TD[:, None] / cfg.Q_TD_nom  # shape (2,1)
        f_target = f_noms[None, :] * Q_TD_ratio           # shape (2,5)
        noise_f = rng.normal(0, cfg.sigma_drug_f, (_N_SERIES, 5))
        self._f_drug = (
            cfg.phi_drug * self._f_drug
            + (1.0 - cfg.phi_drug) * f_target
            + noise_f
        )
        self._f_drug = np.clip(self._f_drug, 1.0, 60.0)

        # 泵电流
        I_drug = cfg.I_drug0 + cfg.k_drug_If * self._f_drug  # shape (2,5)
        I_drug += rng.normal(0, cfg.sigma_drug_I, (_N_SERIES, 5))
        I_drug = np.clip(I_drug, 0.5, 20.0)

        # ── 4. pH 动力学 ─────────────────────────────────────────────
        # pH_ss = pH_nom + NaOH效果 - d2抑制
        # NaOH 泵频率偏差→ pH 偏差
        f_naoh_s = self._f_drug[:, 3]   # NaOH 泵频率（索引 3）
        pH_ss = cfg.pH_nom + 0.5 * (f_naoh_s / cfg.f_naoh_nom - 1.0) - cfg.k_pH_d2 * (d2 - 0.018)
        pH_ss = np.clip(pH_ss, 8.0, 11.5)
        noise_pH = rng.normal(0, cfg.sigma_pH, _N_SERIES)
        self._pH = (
            pH_ss + (self._pH - pH_ss) * self._phi_pH + noise_pH
        )
        self._pH = np.clip(self._pH, 8.0, 11.5)

        # ── 5. TFe 浮选回路动力学（关键：品位计算）──────────────────
        TFe_ss = self._tfe_ss_np(self._Q_TD, self._pH, np.full(_N_SERIES, g_ov_del))
        self._TFe_circuit = TFe_ss + (self._TFe_circuit - TFe_ss) * self._phi_flo

        # ── 6. 浮选槽液位 & 泡沫层高度 ──────────────────────────────
        # 串联级联：矿浆全量流过每个槽，首槽入流 = Q_total_s，
        # 后续槽入流 = 前槽出流（保持质量守恒，不均分）。

        # 液位阀控制
        u_lv_sp = np.clip(
            self._u_lv_nom + cfg.Kp_lv * (cfg.L_sp - self._L_cells),
            0.0, 1.0,
        )  # shape (2, 7)
        # 执行机构一阶跟踪
        tau_act = max(cfg.tau_act_lv, dt)
        self._u_lv_fb += (dt / tau_act) * (u_lv_sp - self._u_lv_fb)
        self._u_lv_fb = np.clip(self._u_lv_fb, 0.0, 1.0)
        # 阀门 DCS 读数（含噪声）
        u_lv_dcs = self._u_lv_fb + rng.normal(0, cfg.sigma_u_lv, (_N_SERIES, _N_CELLS))
        u_lv_dcs = np.clip(u_lv_dcs, 0.0, 1.0)

        # 出流（下流矿浆）
        Q_out_pulp = cfg.C_v_lv * self._u_lv_fb * np.sqrt(
            np.maximum(self._L_cells, 0.0)
        )

        # 串联级联入流：slot 0 = Q_total_s；slot c = Q_out[c-1]
        Q_in_cell = np.empty((_N_SERIES, _N_CELLS))
        Q_in_cell[:, 0] = Q_total_s
        Q_in_cell[:, 1:] = Q_out_pulp[:, :-1]

        # 液位 ODE（前向欧拉）
        dL = (Q_in_cell - Q_out_pulp) / cfg.A_cell
        self._L_cells += dL * dt
        self._L_cells = np.clip(self._L_cells, 0.0, 5.0)
        L_dcs = self._L_cells + rng.normal(0, cfg.sigma_u_lv, (_N_SERIES, _N_CELLS))
        L_dcs = np.clip(L_dcs, 0.0, 5.0)

        # 蝶阀开度（慢速 AR(1)）
        self._u_bv += rng.normal(0, cfg.sigma_bv, (_N_SERIES, _N_CELLS))
        self._u_bv = np.clip(self._u_bv * 0.995 + 0.5 * 0.005, 0.1, 0.9)
        u_bv_dcs = np.clip(self._u_bv + rng.normal(0, cfg.sigma_bv, (_N_SERIES, _N_CELLS)), 0.1, 0.9)

        # 充气量（每槽）
        Q_air = self._Q_air_sp + rng.normal(0, cfg.sigma_Q_air, (_N_SERIES, _N_CELLS))
        Q_air = np.clip(Q_air, 0.0, 0.05)
        # 充气量设定值：慢速 AR(1) 围绕名义值漂移（模拟操作员调节）
        # 合法范围限制在名义值的 [50%, 200%]
        Q_air_sp_lo = cfg.Q_air_nom * 0.5
        Q_air_sp_hi = cfg.Q_air_nom * 2.0
        self._Q_air_sp = np.clip(
            cfg.Q_air_nom + cfg.phi_Q_air_sp * (self._Q_air_sp - cfg.Q_air_nom)
            + rng.normal(0, cfg.sigma_Q_air_sp, (_N_SERIES, _N_CELLS)),
            Q_air_sp_lo, Q_air_sp_hi,
        )
        Q_air_sp = np.clip(
            self._Q_air_sp + rng.normal(0, cfg.sigma_Q_air * 0.5, (_N_SERIES, _N_CELLS)),
            Q_air_sp_lo, Q_air_sp_hi,
        )

        # 泡沫层高度 ZOH
        C_Si_approx = np.clip(1.0 - self._TFe_circuit, 0.1, 0.9)[:, None]  # (2,1)
        tau_froth_local = 1.0 / max(cfg.k_col_froth + cfg.k_scrape * cfg.omega_scraper, 1e-6)
        h_ss = (cfg.k_gen_froth * Q_air * C_Si_approx
                / max(cfg.k_col_froth + cfg.k_scrape * cfg.omega_scraper, 1e-9))
        h_ss = np.clip(h_ss, 0.0, 1.5)
        self._h_froth = _zoh_arr(self._h_froth, h_ss, tau_froth_local, dt)
        self._h_froth = np.clip(self._h_froth, 0.0, 1.5)
        # 泡沫层 DCS（含噪声与故障注入）
        h_froth_dcs = np.empty((_N_SERIES, _N_CELLS))
        for s in range(_N_SERIES):
            for c in range(_N_CELLS):
                h_raw = self._h_froth[s, c] + rng.normal(0, cfg.sigma_h_froth)
                h_froth_dcs[s, c] = inject_fault(
                    h_raw, cfg.p_fault_froth, cfg.fault_val_froth, rng
                )

        # 浮选机电机电流（与矿浆密度弱耦合）
        # I = I_FXJ0 + k_FXJ*(rho_slurry - rho_nom) + noise
        # rho_slurry 用上游延迟溢流流量估算（给矿量偏高时矿浆更密）
        rho_slurry_est = cfg.rho_ov + (m_ov_del - cfg.m_ov_nom) * 0.05  # kg/m³ approx
        rho_deviation = rho_slurry_est - cfg.rho_ov
        I_FXJ = (
            cfg.I_FXJ0
            + cfg.k_FXJ * rho_deviation
            + rng.normal(0, cfg.sigma_I_FXJ, (_N_SERIES, _N_CELLS))
        )
        I_FXJ = np.clip(I_FXJ, 10.0, 50.0)

        # ── 7. 搅拌槽温度 ─────────────────────────────────────────────
        u_TV_sp = np.clip(
            cfg.u_TV_nom + cfg.Kp_TV * (cfg.T_tk_sp - self._T_tanks),
            0.0, 1.0,
        )
        self._u_TV_fb = (
            u_TV_sp + (self._u_TV_fb - u_TV_sp) * self._phi_TV
        )
        self._u_TV_fb = np.clip(self._u_TV_fb, 0.0, 1.0)
        self._T_tanks = _zoh_arr(self._T_tanks, np.full((_N_SERIES, _N_TANKS), cfg.T_tk_sp), cfg.tau_tk, dt)
        self._T_tanks += rng.normal(0, cfg.sigma_T_tk, (_N_SERIES, _N_TANKS))
        self._T_tanks = np.clip(self._T_tanks, 20.0, 80.0)
        T_tanks_dcs = self._T_tanks + rng.normal(0, cfg.sigma_T_tk, (_N_SERIES, _N_TANKS))
        T_tanks_dcs = np.clip(T_tanks_dcs, 20.0, 80.0)
        u_TV_sp_dcs = np.clip(u_TV_sp + rng.normal(0, cfg.sigma_TV, (_N_SERIES, _N_TANKS)), 0.0, 1.0)
        u_TV_fb_dcs = np.clip(self._u_TV_fb + rng.normal(0, cfg.sigma_TV, (_N_SERIES, _N_TANKS)), 0.0, 1.0)

        # ── 8. 泵池液位 & 泵频率 ──────────────────────────────────────
        # 入流使用实时延迟溢流流量（而非固定名义值），从而响应给矿量变化
        # Q_total_s 是标量，在 ODE 中自动广播到 (_N_SERIES, _N_POOLS)
        Q_in_pool = Q_total_s / _N_POOLS
        Q_pump_pool = (cfg.k_pump_flo * self._f_pumps
                       * np.sqrt(np.maximum(self._L_pools, 0.0)))
        dL_pool = (Q_in_pool - Q_pump_pool) / cfg.A_pool_flo
        self._L_pools += dL_pool * dt
        self._L_pools = np.clip(self._L_pools, 0.0, 5.0)
        # 变频控制：液位偏差→频率调整
        f_target_pool = np.clip(
            cfg.f_pump_flo_nom + cfg.Kp_pool_flo * (self._L_pools - cfg.L_pool_flo_sp),
            cfg.f_pump_flo_min, cfg.f_pump_flo_max,
        )
        self._f_pumps += (dt / 30.0) * (f_target_pool - self._f_pumps)
        self._f_pumps += rng.normal(0, cfg.sigma_f_pump_flo, (_N_SERIES, _N_POOLS))
        self._f_pumps = np.clip(self._f_pumps, cfg.f_pump_flo_min, cfg.f_pump_flo_max)
        I_pool = cfg.I_pump_flo0 + cfg.k_pump_flo_I * self._f_pumps ** 2
        I_pool += rng.normal(0, cfg.sigma_I_pool, (_N_SERIES, _N_POOLS))
        I_pool = np.clip(I_pool, 1.0, 60.0)
        L_pool_dcs = np.clip(
            self._L_pools + rng.normal(0, cfg.sigma_L_pool_flo, (_N_SERIES, _N_POOLS)),
            0.0, 5.0,
        )
        f_pool_dcs = np.clip(
            self._f_pumps + rng.normal(0, cfg.sigma_f_pump_flo, (_N_SERIES, _N_POOLS)),
            cfg.f_pump_flo_min, cfg.f_pump_flo_max,
        )

        # ── 9. 鼓风机压力 ─────────────────────────────────────────────
        self._P_blower = (
            cfg.P_blower_nom
            + cfg.phi_blower * (self._P_blower - cfg.P_blower_nom)
            + rng.normal(0, cfg.sigma_blower, 2)
        )
        self._P_blower = np.clip(self._P_blower, 10.0, 60.0)

        # ── 10. K6 贮药箱液位 ─────────────────────────────────────────
        # 缓慢 AR(1) 漂移，模拟消耗 + 补充
        self._L_k6 = (
            cfg.L_k6_init
            + cfg.phi_k6 * (self._L_k6 - cfg.L_k6_init)
            + rng.normal(0, cfg.sigma_L_k6, _N_SERIES)
        )
        self._L_k6 = np.clip(self._L_k6, 0.2, 3.0)
        L_k6_dcs = np.clip(
            self._L_k6 + rng.normal(0, cfg.sigma_L_k6, _N_SERIES),
            0.2, 3.0,
        )

        # ── 11. 入矿流量传感器 ────────────────────────────────────────
        Q_ft_nom = Q_total_s  # m³/s
        Q_ft = np.array([
            max(Q_ft_nom + rng.normal(0, cfg.sigma_Q_ft), 0.0),
            max(Q_ft_nom + rng.normal(0, cfg.sigma_Q_ft), 0.0),
            max(Q_ft_nom + rng.normal(0, cfg.sigma_Q_ft), 0.0),
            max(Q_ft_nom + rng.normal(0, cfg.sigma_Q_ft), 0.0),
        ])  # [s1_ft1, s1_ft2, s2_ft1, s2_ft2]

        # ── 12. 变压器有功功率 ───────────────────────────────────────
        P_FXJ_total = np.sum(I_FXJ, axis=1) * 380.0 * math.sqrt(3) * 0.85 / 1000.0  # kW
        P_pump_total = np.sum(I_pool, axis=1) * 380.0 * math.sqrt(3) * 0.85 / 1000.0
        P_AH = np.array([
            P_FXJ_total[0] + P_pump_total[0] + rng.normal(0, cfg.sigma_P_AH),
            P_FXJ_total[1] + P_pump_total[1] + rng.normal(0, cfg.sigma_P_AH),
        ])
        P_AH = np.clip(P_AH, 100.0, 5000.0)

        # 13. Sample-aligned assay labels.
        #
        # y_fx_xin1/2 are supervised-learning targets, so they are written at
        # the sample collection time. The lab delay still describes when the
        # value would be available in an online system, but storing the target
        # at report time misaligns y with the process features that generated it.
        for s in range(_N_SERIES):
            self._lab_buf[s].push(self._TFe_circuit[s] + self._delta_12[s])
            self._steps_to_assay[s] -= 1
            if self._steps_to_assay[s] <= 0:
                self._y_fx[s] = (
                    self._TFe_circuit[s]
                    + self._delta_12[s]
                    + rng.normal(0, cfg.sigma_lab)
                )
                self._steps_to_assay[s] = int(rng.integers(
                    cfg.assay_interval_min, cfg.assay_interval_max + 1
                ))
                self._tau_lab[s] = int(rng.integers(
                    cfg.tau_lab_min, cfg.tau_lab_max + 1
                ))
            else:
                self._y_fx[s] = float("nan")

        # 14. Write bus values in STEP3 column order.
        bus["fx_nt1_motor_current"] = float(I_NT[0])
        bus["fx_nt2_motor_current"] = float(I_NT[1])
        bus["fx_nt1_underflow_density"] = float(rho_NT_dcs[0])
        bus["fx_nt2_underflow_density"] = float(rho_NT_dcs[1])

        # 浮选槽（每系列 7 槽，7 变量/槽）
        for s in range(_N_SERIES):
            sn = s + 1
            for c in range(_N_CELLS):
                cn = _CELLS[c]
                bus[f"fx_s{sn}_{cn}_froth_h"]        = float(h_froth_dcs[s, c])
                bus[f"fx_s{sn}_{cn}_level"]           = float(L_dcs[s, c])
                bus[f"fx_s{sn}_{cn}_level_valve_sp"]  = float(u_lv_sp[s, c])
                bus[f"fx_s{sn}_{cn}_level_valve_fb"]  = float(u_lv_dcs[s, c])
                bus[f"fx_s{sn}_{cn}_air_flow"]        = float(Q_air[s, c])
                bus[f"fx_s{sn}_{cn}_air_sp"]          = float(Q_air_sp[s, c])
                bus[f"fx_s{sn}_{cn}_bv_pos"]          = float(u_bv_dcs[s, c])

        # 浮选机电机电流
        for s in range(_N_SERIES):
            sn = s + 1
            for c in range(_N_CELLS):
                cn = _CELLS[c]
                bus[f"fx_s{sn}_{cn}_motor_curr"] = float(I_FXJ[s, c])

        # 加药泵
        _pump_keys = ["td_rough", "td_clean", "k6_rough", "naoh", "cao"]
        for s in range(_N_SERIES):
            sn = s + 1
            for pi, pk in enumerate(_pump_keys):
                bus[f"fx_s{sn}_{pk}_freq"] = float(self._f_drug[s, pi])
                bus[f"fx_s{sn}_{pk}_curr"] = float(I_drug[s, pi])

        # pH
        bus["fx_s1_ph"] = float(add_noise(self._pH[0], 0.02, rng))
        bus["fx_s2_ph"] = float(add_noise(self._pH[1], 0.02, rng))

        # 搅拌槽温度
        for s in range(_N_SERIES):
            sn = s + 1
            for k in range(_N_TANKS):
                kn = k + 1
                bus[f"fx_s{sn}_tk{kn}_temp"]     = float(T_tanks_dcs[s, k])
                bus[f"fx_s{sn}_tk{kn}_steam_sp"]  = float(u_TV_sp_dcs[s, k])
                bus[f"fx_s{sn}_tk{kn}_steam_fb"]  = float(u_TV_fb_dcs[s, k])

        # 泵池
        for s in range(_N_SERIES):
            sn = s + 1
            for k in range(_N_POOLS):
                kn = k + 1
                bus[f"fx_s{sn}_pool{kn}_level"]     = float(L_pool_dcs[s, k])
                bus[f"fx_s{sn}_pool{kn}_pump_freq"]  = float(f_pool_dcs[s, k])
                bus[f"fx_s{sn}_pool{kn}_pump_curr"]  = float(I_pool[s, k])

        # 鼓风机
        bus["fx_blower1_pressure"] = float(self._P_blower[0])
        bus["fx_blower2_pressure"] = float(self._P_blower[1])

        # 变压器有功
        bus["fx_ah5_power"] = float(P_AH[0])
        bus["fx_ah6_power"] = float(P_AH[1])

        # 入矿流量
        bus["fx_s1_ft1701"] = float(Q_ft[0])
        bus["fx_s1_ft1702"] = float(Q_ft[1])
        bus["fx_s2_ft2701"] = float(Q_ft[2])
        bus["fx_s2_ft2702"] = float(Q_ft[3])

        # K6 液位
        bus["fx_s1_k6_level"] = float(L_k6_dcs[0])
        bus["fx_s2_k6_level"] = float(L_k6_dcs[1])

        # 目标变量（NaN 表示化验尚未出结果）
        bus["y_fx_xin1"] = float(self._y_fx[0])
        bus["y_fx_xin2"] = float(self._y_fx[1])

        # 隐藏中间量（供测试用）
        bus["_x_TFe_circuit_s1"] = float(self._TFe_circuit[0])
        bus["_x_TFe_circuit_s2"] = float(self._TFe_circuit[1])
        bus["_x_Q_TD_s1"] = float(self._Q_TD[0])
        bus["_x_Q_TD_s2"] = float(self._Q_TD[1])
        bus["_x_g_ov_del"] = float(g_ov_del)

    # ─────────────────────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────────────────────

    def _tfe_ss_np(
        self,
        Q_TD: np.ndarray,
        pH: np.ndarray,
        g_ov: np.ndarray,
    ) -> np.ndarray:
        """计算浮选精矿稳态 TFe 品位（向量化）。

        参数
        ----
        Q_TD : 加药量数组 (g/t)，shape (N_SERIES,)
        pH   : pH 数组，shape (N_SERIES,)
        g_ov : 溢流 TFe 品位数组，shape (N_SERIES,)

        返回
        ----
        TFe_conc : 精矿 TFe 品位（小数），shape (N_SERIES,)
        """
        cfg = self._cfg
        dQ = Q_TD - cfg.Q_TD_nom
        dpH = pH - cfg.pH_nom

        eta_Fe = np.clip(cfg.eta_Fe0 + cfg.k_eta_Fe * dQ, 0.50, 1.0)
        R_Si = np.clip(cfg.R_Si0 + cfg.k_R_Si * dQ + cfg.k_R_Si_pH * dpH, 0.0, 1.0)

        g = np.clip(g_ov, 0.01, 0.99)
        Fe_conc = eta_Fe * g
        Si_conc = (1.0 - R_Si) * (1.0 - g)
        denom = np.where(Fe_conc + Si_conc > 1e-9, Fe_conc + Si_conc, 1e-9)
        return Fe_conc / denom
