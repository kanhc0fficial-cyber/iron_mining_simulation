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
from sim.utils.aggregation import active_mask, aggregate_active, write_aggregate


def _sigmoid(x: float) -> float:
    """数值稳定的 sigmoid。"""
    if x >= 0:
        return 1.0 / (1.0 + np.exp(-x))
    ex = np.exp(x)
    return ex / (1.0 + ex)


_FE_KEYS = ("fe_mag", "fe_hem", "fe_carb", "fe_sil")
_MASS_KEYS = (*_FE_KEYS, "gangue")


def _stream_mass(parts: dict[str, float]) -> float:
    return float(sum(parts.get(k, 0.0) for k in _MASS_KEYS))


def _stream_fe(parts: dict[str, float]) -> float:
    return float(sum(parts.get(k, 0.0) for k in _FE_KEYS))


def _stream_grade(parts: dict[str, float]) -> float:
    m = _stream_mass(parts)
    if m <= 1e-9:
        return 0.0
    return float(np.clip(_stream_fe(parts) / m, 0.0, 1.0))


def _scale_stream(parts: dict[str, float], factor: float) -> dict[str, float]:
    factor = max(float(factor), 0.0)
    return {k: max(parts.get(k, 0.0) * factor, 0.0) for k in _MASS_KEYS}


def _subtract_stream(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {k: max(a.get(k, 0.0) - b.get(k, 0.0), 0.0) for k in _MASS_KEYS}


def _merge_streams(*streams: dict[str, float]) -> dict[str, float]:
    return {k: float(sum(s.get(k, 0.0) for s in streams)) for k in _MASS_KEYS}


def _split_by_component_recovery(
    feed: dict[str, float],
    fe_recovery: float,
    grade_target: float,
    selectivity: tuple[float, float, float, float],
    gangue_recovery_max: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """按组分选择性和目标铁回收率分流，夹带量由品位锚点约束。"""
    total_fe = _stream_fe(feed)
    if total_fe <= 1e-9 or _stream_mass(feed) <= 1e-9:
        empty = {k: 0.0 for k in _MASS_KEYS}
        return empty.copy(), empty.copy(), {f"R_{k}": 0.0 for k in _MASS_KEYS}

    weights = np.array(selectivity, dtype=float)
    fe_vec = np.array([feed[k] for k in _FE_KEYS], dtype=float)
    weighted_fe = float(np.sum(weights * fe_vec))
    desired_fe = float(np.clip(fe_recovery, 0.0, 0.98) * total_fe)
    scale = desired_fe / max(weighted_fe, 1e-9)
    fe_rec = np.clip(weights * scale, 0.0, 0.98)

    conc = {k: float(feed[k] * r) for k, r in zip(_FE_KEYS, fe_rec)}
    fe_conc = _stream_fe(conc)
    target = float(np.clip(grade_target, 0.02, 0.90))
    desired_gangue = max(fe_conc * (1.0 / target - 1.0), 0.0)
    gangue_feed = max(feed.get("gangue", 0.0), 0.0)
    gangue_rec = float(np.clip(
        desired_gangue / max(gangue_feed, 1e-9),
        0.0,
        gangue_recovery_max,
    ))
    conc["gangue"] = gangue_feed * gangue_rec
    tail = _subtract_stream(feed, conc)

    recoveries = {f"R_{k}": float(r) for k, r in zip(_FE_KEYS, fe_rec)}
    recoveries["R_gangue"] = gangue_rec
    return conc, tail, recoveries


def _write_stream_hidden(
    bus: dict,
    prefix: str,
    parts: dict[str, float],
    concentration: float,
    f200: float,
    f325: float,
    f25: float,
    d80: float,
    liberation_fe: float,
    liberation_gangue: float,
) -> None:
    bus[f"{prefix}_m"] = _stream_mass(parts)
    bus[f"{prefix}_tfe"] = _stream_grade(parts)
    bus[f"{prefix}_c"] = concentration
    bus[f"{prefix}_f200"] = f200
    bus[f"{prefix}_f325"] = f325
    bus[f"{prefix}_f25"] = f25
    bus[f"{prefix}_d80"] = d80
    bus[f"{prefix}_liberation_fe"] = liberation_fe
    bus[f"{prefix}_liberation_gangue"] = liberation_gangue
    for key in _MASS_KEYS:
        bus[f"{prefix}_{key}"] = parts.get(key, 0.0)


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

        # ── 设备级聚合偏差：固定设备差异 + 每步公共扰动 ────────────────
        self._hm_elec_bias = self._rng.normal(0.0, cfg.unit_cv_electrical, cfg.n_hm_units)
        self._sw_elec_bias = self._rng.normal(0.0, cfg.unit_cv_electrical, cfg.n_sw_units)
        self._hm_mech_bias = self._rng.normal(0.0, cfg.unit_cv_mechanical, cfg.n_hm_units)
        self._sw_mech_bias = self._rng.normal(0.0, cfg.unit_cv_mechanical, cfg.n_sw_units)

    def _feed_stream_from_bus(self, bus: dict) -> dict[str, float]:
        """读取阶段 1 边界组分；旧测试路径缺字段时按矿石先验回退。"""
        if all(f"_x_boundary_{k}" in bus for k in _MASS_KEYS):
            return {k: float(bus[f"_x_boundary_{k}"]) for k in _MASS_KEYS}

        m_solid = float(bus["_x_m_ball"])
        total_fe = float(np.clip(bus["_x_d1"], 0.0, 1.0) * m_solid)
        carb_abs = float(np.clip(bus.get("_x_d2", 0.018), 0.0, 0.20))
        fe_carb = min(carb_abs * m_solid, total_fe * 0.20)
        fe_sil = min(total_fe * 0.060, max(total_fe - fe_carb, 0.0))
        fe_hem = min(total_fe * 0.118, max(total_fe - fe_carb - fe_sil, 0.0))
        fe_mag = max(total_fe - fe_hem - fe_carb - fe_sil, 0.0)
        return {
            "fe_mag": fe_mag,
            "fe_hem": fe_hem,
            "fe_carb": fe_carb,
            "fe_sil": fe_sil,
            "gangue": max(m_solid - total_fe, 0.0),
        }

    def _liberation_from_size(self, f200: float) -> tuple[float, float]:
        cfg = self._cfg
        d = f200 - cfg.liberation_f200_ref
        lib_fe = np.clip(cfg.liberation_fe_mixed_ref + 0.28 * d, 0.0, 1.0)
        lib_g = np.clip(cfg.liberation_gangue_mixed_ref + 0.45 * d, 0.0, 1.0)
        return float(lib_fe), float(lib_g)

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
        c_feed = bus.get("_x_rho_ball", cfg.hm_actual_concentration)
        f200 = bus.get("_x_f200_ball", 0.77)
        f325 = bus.get("_x_f325_ball", 0.55)
        d80 = bus.get("_x_d80_ball", 0.074)
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

        # ── 3. 弱磁选（阶段 2：组分质量平衡分流）────────────────────────
        feed_parts = self._feed_stream_from_bus(bus)
        lib_fe, lib_gangue = self._liberation_from_size(float(f200))

        g_wmag_target = d1 * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1))
        g_wmag_target = float(np.clip(g_wmag_target, 0.0, 1.0))
        beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25)
        beta_wm = float(np.clip(beta_wm, 0.01, 0.99))

        wm_conc_parts, wm_tail_parts, wm_rec = _split_by_component_recovery(
            feed_parts,
            beta_wm,
            g_wmag_target,
            cfg.wm_component_selectivity,
            cfg.wm_gangue_recovery_max,
        )
        m_wm_conc = _stream_mass(wm_conc_parts)
        m_wm_tail = _stream_mass(wm_tail_parts)
        g_wm_tail = _stream_grade(wm_tail_parts)

        # ── 4. 强磁前浓缩（一阶滞后）────────────────────────────────────
        self._m_conc_out += (dt / cfg.tau_conc) * (m_wm_tail - self._m_conc_out)
        m_conc_out = max(self._m_conc_out, 0.0)
        hm_feed_parts = _scale_stream(
            wm_tail_parts,
            m_conc_out / max(m_wm_tail, 1e-9),
        )
        g_hm_feed = _stream_grade(hm_feed_parts)

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

        # ── 7. 强磁精矿组分分流 ───────────────────────────────────────
        g_strong_target = (g_hm_feed * cfg.k_s_Fe
                           / (1.0 + cfg.k_s_Si * (1.0 - g_hm_feed)))
        g_strong_target = float(np.clip(g_strong_target, g_hm_feed, 1.0))
        hm_conc_parts, hm_tail_parts, hm_rec = _split_by_component_recovery(
            hm_feed_parts,
            beta_strong,
            g_strong_target,
            cfg.hm_component_selectivity,
            cfg.hm_gangue_recovery_max,
        )
        m_strong_conc = _stream_mass(hm_conc_parts)
        m_strong_tail = _stream_mass(hm_tail_parts)
        g_strong_tail = _stream_grade(hm_tail_parts)

        # ── 8. 扫强磁精矿组分分流 ──────────────────────────────────────
        g_sweep_target = (g_strong_tail * cfg.k_sw_Fe
                          / (1.0 + cfg.k_sw_Si * (1.0 - g_strong_tail)))
        g_sweep_target = float(np.clip(
            min(g_sweep_target, cfg.sw_conc_grade_target),
            g_strong_tail,
            1.0,
        ))
        sw_conc_parts, sw_tail_parts, sw_rec = _split_by_component_recovery(
            hm_tail_parts,
            cfg.beta_sweep_Fe,
            g_sweep_target,
            cfg.sw_component_selectivity,
            cfg.sw_gangue_recovery_max,
        )
        m_sweep_conc = _stream_mass(sw_conc_parts)

        # ── 9. 混磁精矿 ─────────────────────────────────────────────────
        mixed_parts = _merge_streams(wm_conc_parts, hm_conc_parts, sw_conc_parts)
        m_mag = _stream_mass(mixed_parts)
        g_mag = _stream_grade(mixed_parts)

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
        # ── 14.5 设备级聚合（保留 agg_* 兼容列，但不再假装单台设备）──────
        # 开台数按负荷离散变化。工厂报告中弱磁 3-11 台，强磁/扫强磁
        # 各 2-6 台；这里用负荷比例驱动，避免连续噪声伪装离散调度。
        load_ratio = float(np.clip(m_ball / (265.0 * 3.0), 0.0, 1.5))
        wm_on = int(np.clip(round(cfg.n_wm_units * load_ratio), cfg.wm_units_min, cfg.wm_units_max))
        hm_on = int(np.clip(round(cfg.hm_units_max * load_ratio), cfg.hm_units_min, cfg.hm_units_max))
        sw_on = int(np.clip(round(cfg.sw_units_max * load_ratio), cfg.sw_units_min, cfg.sw_units_max))
        hm_active = active_mask(cfg.n_hm_units, hm_on)
        sw_active = active_mask(cfg.n_sw_units, sw_on)

        hm_I = I_exc_dcs * cfg.hm_current_factor * (1.0 + self._hm_elec_bias)
        sw_I = I_exc_dcs * cfg.sw_current_factor * (1.0 + self._sw_elec_bias)
        hm_V = V_exc_dcs * (1.0 + 0.5 * self._hm_elec_bias)
        sw_V = V_exc_dcs * (1.0 + 0.5 * self._sw_elec_bias)
        hm_T = T_coil_dcs + 6.0 * self._hm_elec_bias
        sw_T = T_coil_dcs + 6.0 * self._sw_elec_bias
        hm_motor = I_motor_dcs * (1.0 + self._hm_mech_bias)
        sw_motor = 0.85 * I_motor_dcs * (1.0 + self._sw_mech_bias)
        hm_level = L_dcs * (1.0 + 0.4 * self._hm_mech_bias)
        sw_level = L_dcs * (1.0 + 0.4 * self._sw_mech_bias)
        hm_ring = f_ring * (1.0 + 0.2 * self._hm_mech_bias)
        sw_ring = f_ring * (1.0 + 0.2 * self._sw_mech_bias)
        hm_pul = f_pul * (1.0 + 0.15 * self._hm_mech_bias)
        sw_pul = f_pul * (1.0 + 0.15 * self._sw_mech_bias)

        hm_I_stats = aggregate_active(hm_I, hm_active)
        sw_I_stats = aggregate_active(sw_I, sw_active)
        all_active = np.concatenate([hm_active, sw_active])

        bus["wm_units_on"] = wm_on
        bus["hm_units_on"] = hm_on
        bus["sw_units_on"] = sw_on
        write_aggregate(bus, "hm_mag_excit_current", hm_I_stats)
        write_aggregate(bus, "sw_mag_excit_current", sw_I_stats)
        write_aggregate(bus, "agg_mag_excit_current", aggregate_active(np.concatenate([hm_I, sw_I]), all_active))
        write_aggregate(bus, "agg_mag_excit_voltage", aggregate_active(np.concatenate([hm_V, sw_V]), all_active))
        write_aggregate(bus, "agg_mag_coil_temp", aggregate_active(np.concatenate([hm_T, sw_T]), all_active))
        write_aggregate(bus, "agg_mag_level", aggregate_active(np.concatenate([hm_level, sw_level]), all_active))
        write_aggregate(bus, "agg_mag_ring_freq", aggregate_active(np.concatenate([hm_ring, sw_ring]), all_active))
        write_aggregate(bus, "agg_mag_pulsation_freq", aggregate_active(np.concatenate([hm_pul, sw_pul]), all_active))
        write_aggregate(bus, "agg_mag_motor_current_rc", aggregate_active(np.concatenate([hm_motor, sw_motor]), all_active))

        bus["agg_mag_tailings_valve1"] = u_v1
        bus["agg_mag_tailings_valve2"] = u_v2
        bus["agg_mag_blowdown_valve"] = u_blow_dcs
        bus["agg_mag_flush_water_pressure"] = P_flush_dcs
        bus["agg_mag_motor_voltage_rc"] = V_motor_dcs

        # ── 写入 bus（隐藏中间量，供下游使用）───────────────────────────
        bus["_x_g_mag"] = g_mag
        bus["_x_m_mag"] = m_mag
        bus["_x_C_mag"] = cfg.mixed_conc_concentration
        bus["_x_f200_mag"] = f200
        bus["_x_f325_mag"] = f325
        bus["_x_f25_mag"] = f25
        bus["_x_d80_mag"] = d80
        bus["_x_liberation_fe_mag"] = lib_fe
        bus["_x_liberation_gangue_mag"] = lib_gangue
        for key in _MASS_KEYS:
            bus[f"_x_mag_{key}"] = mixed_parts.get(key, 0.0)

        _write_stream_hidden(
            bus, "_x_mag_feed", feed_parts, c_feed, f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_wm_conc", wm_conc_parts, c_feed, f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_wm_tail", wm_tail_parts, c_feed, f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_hm_feed", hm_feed_parts, cfg.hm_actual_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_hm_conc", hm_conc_parts, cfg.hm_actual_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_hm_tail", hm_tail_parts, cfg.hm_actual_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_sw_conc", sw_conc_parts, cfg.sw_actual_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_sw_tail", sw_tail_parts, cfg.sw_actual_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )
        _write_stream_hidden(
            bus, "_x_mag_mixed_conc", mixed_parts, cfg.mixed_conc_concentration,
            f200, f325, f25, d80, lib_fe, lib_gangue
        )

        for name, rec in (
            ("wm", wm_rec),
            ("hm", hm_rec),
            ("sw", sw_rec),
        ):
            for key, value in rec.items():
                bus[f"_x_mag_{name}_{key}"] = value
