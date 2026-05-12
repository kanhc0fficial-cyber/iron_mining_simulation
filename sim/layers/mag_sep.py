"""
磁选段仿真（第3章）。

物理流程：
  弱磁选（准静态代数）
  → 强磁前浓缩（一阶滞后）
  → 强磁 + 扫强磁（归一化力竞争 sigmoid）
  → 混磁精矿（加权平均）

输出 12 个 DCS 变量（直接写入 bus，无 _x_ 前缀）及两个隐藏中间量：
  _x_g_mag  : 混磁精矿 TFe 品位
  _x_m_mag  : 混磁精矿质量流量（t/h）
"""

from __future__ import annotations
import numpy as np

from sim.config import MagSepConfig, SimConfig
from sim.utils.pid import PIDController
from sim.utils.thermal import FirstOrderThermal
from sim.utils.sensor import add_noise, add_drift


def _sigmoid(x: float) -> float:
    """数值稳定的 sigmoid。"""
    if x >= 0:
        return 1.0 / (1.0 + np.exp(-x))
    ex = np.exp(x)
    return ex / (1.0 + ex)


class MagSepSystem:
    """
    磁选段全部物理计算。

    读取 bus：
      _x_d1, _x_d4, _x_m_ball, _x_rho_ball, _x_d80_ball, _x_f25_ball

    写入 bus（DCS 可观测量）：
      agg_mag_excit_voltage, agg_mag_excit_current, agg_mag_coil_temp,
      agg_mag_tailings_valve1, agg_mag_tailings_valve2,
      agg_mag_blowdown_valve, agg_mag_pulsation_freq, agg_mag_ring_freq,
      agg_mag_level, agg_mag_flush_water_pressure,
      agg_mag_motor_current_rc, agg_mag_motor_voltage_rc

    写入 bus（隐藏中间量）：
      _x_g_mag, _x_m_mag
    """

    def __init__(
        self,
        cfg: MagSepConfig,
        sim_cfg: SimConfig,
        rng: np.random.Generator,
    ) -> None:
        self._cfg = cfg
        self._dt = sim_cfg.dt
        self._rng = rng

        # ── 名义稳态计算（供后续初始化使用）────────────────────────────
        d1_nom = 0.3149
        g_wmag_nom = d1_nom * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1_nom))
        beta_wm_nom = cfg.beta_wm0
        m_ball_nom = 265.0 * 3          # t/h，三线额定
        m_wm_conc_nom = beta_wm_nom * d1_nom * m_ball_nom / max(g_wmag_nom, 0.01)
        m_tail_nom = m_ball_nom - m_wm_conc_nom
        Q_in_nom = m_tail_nom * 1000.0 / 3600.0 / cfg.rho_conc_kg_m3

        # ── 励磁电压 AR(1) 残差 ──────────────────────────────────────────
        self._xi_V_exc: float = 0.0

        # ── 线圈热力学 ──────────────────────────────────────────────────
        # 初始温度设为热稳态（加速预热）
        I_nom = cfg.V_nom / cfg.R0_coil
        T_init = cfg.T_amb + (I_nom ** 2 * cfg.R0_coil) / cfg.k_cool_coil
        self._coil_thermal = FirstOrderThermal(
            tau=cfg.tau_thermal_coil,
            k_cool=cfg.k_cool_coil,
            T_init=T_init,
        )

        # ── 强磁前浓缩（一阶滞后）──────────────────────────────────────
        # 初始化为名义稳态，避免冷启动时液位震荡
        self._m_conc_out: float = m_tail_nom

        # ── 液位控制 ────────────────────────────────────────────────────
        self._L: float = cfg.L_init          # 真实液位（m）
        self._b_L: float = 0.0               # 液位传感器漂移偏置
        self._level_pid = PIDController(
            Kp=cfg.Kp_L,
            Ki=cfg.Ki_L,
            Kd=cfg.Kd_L,
            dt=sim_cfg.dt,
            u_min=0.0,
            u_max=2.0,    # 两阀合计最大 2.0（每阀 0~1）
        )
        # 用名义前向补偿初始化 PID 积分项，避免启动时液位冲高
        u_ff = Q_in_nom / (cfg.C_v_mag * max(cfg.L_setpoint ** 0.5, 0.01))
        self._level_pid.reset(integral=float(np.clip(u_ff, 0.0, 2.0)))

        # ── 操作员设定量 AR(1) 残差 ─────────────────────────────────────
        self._xi_f_pul: float = 0.0
        self._xi_f_ring: float = 0.0

        # ── 电网波动 AR(1) 残差 ─────────────────────────────────────────
        self._xi_Vgrid: float = 0.0

        # ── 预计算名义 B 和 dp（用于力竞争归一化）──────────────────────
        I_nom_steady = cfg.V_nom / (cfg.R0_coil * (
            1.0 + cfg.alpha_Cu * (T_init - cfg.T0_coil)
        ))
        self._B_nom: float = cfg.mu0_N_over_l * I_nom_steady
        self._dp_nom: float = cfg.dp_ref * np.sqrt(max(1.0 - cfg.f25_nom, 0.01))

    # ────────────────────────────────────────────────────────────────────
    # 主步进函数
    # ────────────────────────────────────────────────────────────────────

    def step(self, bus: dict, t: int) -> None:
        """推进一步，读取 bus 并写入所有磁选 DCS 变量及隐藏中间量。"""
        cfg = self._cfg
        dt = self._dt

        # ── 读取上游量 ───────────────────────────────────────────────────
        d1 = bus["_x_d1"]
        d4 = bus["_x_d4"]              # MPa，公共管网水压
        m_ball = bus["_x_m_ball"]      # t/h，三线合计
        f25 = bus["_x_f25_ball"]       # 超细粒含量

        # ── 1. 励磁电压（极稳定 AR(1)）──────────────────────────────────
        self._xi_V_exc = cfg.phi_V_exc * self._xi_V_exc + self._rng.normal(0.0, cfg.sigma_V_exc)
        V_exc = cfg.V_nom + self._xi_V_exc
        V_exc_dcs = add_noise(V_exc, cfg.sigma_V_exc * 0.5, self._rng)

        # ── 2. 线圈热力学 ODE ────────────────────────────────────────────
        R_coil = cfg.R0_coil * (1.0 + cfg.alpha_Cu * (self._coil_thermal.T - cfg.T0_coil))
        I_exc = V_exc / R_coil
        I_exc_dcs = add_noise(I_exc, cfg.sigma_I_exc, self._rng)
        Q_joule = I_exc ** 2 * R_coil                      # W
        T_coil = self._coil_thermal.step(
            Q_heat=Q_joule,
            T_amb=cfg.T_amb,
            dt=dt,
            noise=self._rng.normal(0.0, cfg.sigma_T_coil),
        )
        T_coil_dcs = add_noise(T_coil, cfg.sigma_T_coil, self._rng)

        # ── 3. 弱磁选（准静态代数）──────────────────────────────────────
        g_wmag = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        g_wmag = float(np.clip(g_wmag, 0.0, 1.0))
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        beta_wm = float(np.clip(beta_wm, 0.01, 0.99))

        # 弱磁精矿质量（铁回收率 × 给矿铁量 / 精矿品位）
        m_Fe_ball = d1 * m_ball
        if g_wmag > 0.01:
            m_wm_conc = beta_wm * m_Fe_ball / g_wmag
        else:
            m_wm_conc = 0.0
        m_wm_conc = max(0.0, min(m_wm_conc, m_ball))
        m_wm_tail = m_ball - m_wm_conc

        # 弱磁尾矿品位（= 强磁给矿品位）
        if m_wm_tail > 0.01:
            g_wm_tail = (m_Fe_ball - beta_wm * m_Fe_ball) / m_wm_tail
        else:
            g_wm_tail = 0.0
        g_wm_tail = float(np.clip(g_wm_tail, 0.0, 1.0))

        # ── 4. 强磁前浓缩（一阶滞后）────────────────────────────────────
        self._m_conc_out += (dt / cfg.tau_conc) * (m_wm_tail - self._m_conc_out)
        m_conc_out = max(self._m_conc_out, 0.0)

        # ── 5. 操作员设定量：转环频率、脉动频率 ─────────────────────────
        self._xi_f_ring = cfg.phi_ring * self._xi_f_ring + self._rng.normal(0.0, cfg.sigma_ring)
        f_ring = cfg.f_ring_mean + self._xi_f_ring

        self._xi_f_pul = cfg.phi_pul * self._xi_f_pul + self._rng.normal(0.0, cfg.sigma_pul)
        f_pul = cfg.f_pul_mean + self._xi_f_pul

        # ── 6. 强磁回收率（归一化力竞争 sigmoid）────────────────────────
        # B 随励磁电流变化
        B = cfg.mu0_N_over_l * I_exc
        # 粒径：越细 f25 越大 → dp 越小
        dp = cfg.dp_ref * np.sqrt(max(1.0 - f25, 0.01))
        # 矿浆流速（受转环频率修正）
        m_conc_kg_s = m_conc_out * 1000.0 / 3600.0   # t/h → kg/s
        v_denom = cfg.rho_conc_kg_m3 * cfg.A_cross * (1.0 - cfg.f_matrix)
        v_base = m_conc_kg_s / v_denom if v_denom > 0 else cfg.v_nom
        ring_factor = 1.0 + cfg.k_ring_v * (f_ring - cfg.f_ring_mean) / max(cfg.f_ring_mean, 0.01)
        v_slurry = max(v_base * ring_factor, 1e-6)

        # 归一化力竞争参数（对数形式，保证数值稳定）
        force_balance = (
            (B / self._B_nom) ** 2
            / ((v_slurry / cfg.v_nom) * (dp / self._dp_nom) ** 2)
        )
        force_balance = max(force_balance, 1e-9)
        beta_strong = _sigmoid(cfg.lambda_s * np.log(force_balance) + cfg.bias_s)

        # ── 7. 强磁精矿品位与质量流 ────────────────────────────────────
        g_strong = (g_wm_tail * cfg.k_s_Fe
                    / (1.0 + cfg.k_s_Si * (1.0 - g_wm_tail)))
        g_strong = float(np.clip(g_strong, g_wm_tail, 1.0))

        if g_strong > 0.01 and m_conc_out > 0.01:
            m_strong_conc = beta_strong * g_wm_tail * m_conc_out / g_strong
        else:
            m_strong_conc = 0.0
        m_strong_conc = float(np.clip(m_strong_conc, 0.0, m_conc_out))
        m_strong_tail = m_conc_out - m_strong_conc

        if m_strong_tail > 0.01:
            m_Fe_tail_strong = g_wm_tail * m_conc_out - g_strong * m_strong_conc
            g_strong_tail = max(m_Fe_tail_strong / m_strong_tail, 0.0)
        else:
            g_strong_tail = 0.0

        # ── 8. 扫强磁精矿品位与质量流 ──────────────────────────────────
        g_sweep = (g_strong_tail * cfg.k_sw_Fe
                   / (1.0 + cfg.k_sw_Si * (1.0 - g_strong_tail)))
        g_sweep = float(np.clip(g_sweep, g_strong_tail, 1.0))

        if g_sweep > 0.01 and m_strong_tail > 0.01:
            m_sweep_conc = cfg.beta_sweep_Fe * g_strong_tail * m_strong_tail / g_sweep
        else:
            m_sweep_conc = 0.0
        m_sweep_conc = float(np.clip(m_sweep_conc, 0.0, m_strong_tail))

        # ── 9. 混磁精矿 ─────────────────────────────────────────────────
        m_mag = m_wm_conc + m_strong_conc + m_sweep_conc
        if m_mag > 0.01:
            g_mag = (
                g_wmag * m_wm_conc
                + g_strong * m_strong_conc
                + g_sweep * m_sweep_conc
            ) / m_mag
        else:
            g_mag = 0.0
        g_mag = float(np.clip(g_mag, 0.0, 1.0))

        # ── 10. 液位 ODE + PID ──────────────────────────────────────────
        # Q_in：前浓缩底流体积流量（m³/s）
        rho_conc_kg_m3 = cfg.rho_conc_kg_m3
        Q_in = m_conc_out * 1000.0 / 3600.0 / rho_conc_kg_m3   # m³/s

        # 液位测量（含漂移）
        L_meas_raw, self._b_L = add_drift(self._L, self._b_L, cfg.sigma_b_level, self._rng)
        L_meas = add_noise(L_meas_raw, cfg.sigma_L_level, self._rng)

        # PID 输出（阀门合计开度 u_v）
        # 液位控制：直接作用（液位高 → 多排料），传入 sp=L_meas, meas=L_setpoint
        u_v = self._level_pid.step(setpoint=L_meas, measurement=cfg.L_setpoint)
        # 级联逻辑：先开阀1，阀1全开后才开阀2
        u_v1 = float(np.clip(u_v, 0.0, 1.0))
        u_v2 = float(np.clip(u_v - 1.0, 0.0, 1.0))

        # 出流量（阀门泄流 + 溢流堰）
        L_pos = max(self._L, 0.0)
        Q_tail = cfg.C_v_mag * (u_v1 + u_v2) * np.sqrt(L_pos)
        Q_over = cfg.k_conc_mag * max(self._L - cfg.L_overflow_mag, 0.0)
        Q_out = Q_tail + Q_over

        # 液位积分（欧拉）
        dL = (Q_in - Q_out) / cfg.A_tank_mag
        self._L += dL * dt
        self._L = float(np.clip(self._L, 0.0, cfg.L_overflow_mag + 0.5))

        L_dcs = add_noise(self._L + self._b_L, cfg.sigma_L_level, self._rng)

        # ── 11. 排污阀（周期脉冲）──────────────────────────────────────
        t_mod = (t * dt) % cfg.T_blow
        u_blow = cfg.u_blow_on if t_mod < cfg.dt_blow else 0.0
        u_blow_dcs = add_noise(u_blow, cfg.sigma_blow, self._rng)

        # ── 12. 冲矿水压力 ──────────────────────────────────────────────
        # P_flush = d4 - k_pipe * Q_flush² (近似，MPa)
        P_flush = d4 - cfg.k_pipe * (cfg.Q_flush ** 2) * 1e-3
        P_flush_dcs = add_noise(P_flush, cfg.sigma_P_flush, self._rng)

        # ── 13. 主电机电流 ───────────────────────────────────────────────
        I_motor = (cfg.I_motor_0
                   + cfg.k_mf * m_ball
                   + cfg.k_mr * f_ring
                   + cfg.k_mm * beta_strong * m_ball)
        I_motor_dcs = add_noise(I_motor, cfg.sigma_I_motor, self._rng)

        # ── 14. 主电机电压（电网波动）───────────────────────────────────
        self._xi_Vgrid = cfg.phi_Vgrid * self._xi_Vgrid + self._rng.normal(0.0, cfg.sigma_Vgrid)
        V_motor = cfg.V_motor_nom + self._xi_Vgrid
        V_motor_dcs = add_noise(V_motor, cfg.sigma_V_motor, self._rng)

        # ── 写入 bus（DCS 可观测量）──────────────────────────────────────
        bus["agg_mag_excit_voltage"] = V_exc_dcs
        bus["agg_mag_excit_current"] = I_exc_dcs
        bus["agg_mag_coil_temp"] = T_coil_dcs
        bus["agg_mag_tailings_valve1"] = u_v1
        bus["agg_mag_tailings_valve2"] = u_v2
        bus["agg_mag_blowdown_valve"] = u_blow_dcs
        bus["agg_mag_pulsation_freq"] = f_pul
        bus["agg_mag_ring_freq"] = f_ring
        bus["agg_mag_level"] = L_dcs
        bus["agg_mag_flush_water_pressure"] = P_flush_dcs
        bus["agg_mag_motor_current_rc"] = I_motor_dcs
        bus["agg_mag_motor_voltage_rc"] = V_motor_dcs

        # ── 写入 bus（隐藏中间量，供下游使用）───────────────────────────
        bus["_x_g_mag"] = g_mag
        bus["_x_m_mag"] = m_mag
