"""
塔磨段仿真（第四章）。

物理流程：
  磁选精矿（延迟 15~30 min）
  → 给矿泵池（液位动力学 + 变频泵）
  → 旋流器分级（溢流 / 沉砂）
  → 塔磨机（闭路研磨，Bond 简化模型）→ 沉砂返回泵池
  → 溢流泵池 → 进入浮选前浓缩

输出 18 个 DCS 变量（直接写入 bus，无 _x_ 前缀）及隐藏中间量：
  _x_f325_ov  : 溢流 −325目含量
  _x_m_ov     : 溢流质量流量（t/h）
  _x_g_ov     : 溢流 TFe 品位（= g_mag，研磨不改变成分）
  _x_P_mech   : 塔磨机械功率（kW，供测试用）
  _x_alpha_ov : 旋流器溢流率（供测试用）

热力学采用 ZOH（零阶保持）精确离散化，对任意 dt、tau 始终数值稳定：
  T(t+dt) = T_ss + (T(t) - T_ss) * phi,  phi = exp(-dt / tau)
"""

from __future__ import annotations
import math
import numpy as np

from sim.config import TowerMillConfig, SimConfig
from sim.utils.buffer import RingBuffer
from sim.utils.sensor import add_noise, add_drift, inject_fault
from sim.utils.aggregation import active_mask, aggregate_active, write_aggregate

_SQRT3 = math.sqrt(3.0)
_FE_KEYS = ("fe_mag", "fe_hem", "fe_carb", "fe_sil")
_MASS_KEYS = (*_FE_KEYS, "gangue")


def _zoh_step(T: float, T_ss: float, tau: float, dt: float, noise: float = 0.0) -> float:
    """ZOH 精确离散化：T(t+dt) = T_ss + (T(t) - T_ss)*exp(-dt/tau) + noise。
    
    对任意正 tau 和 dt 均数值稳定（phi ∈ (0,1)）。
    """
    phi = math.exp(-dt / tau)
    return T_ss + (T - T_ss) * phi + noise


def _stream_mass(parts: dict[str, float]) -> float:
    return float(sum(parts.get(k, 0.0) for k in _MASS_KEYS))


def _stream_fe(parts: dict[str, float]) -> float:
    return float(sum(parts.get(k, 0.0) for k in _FE_KEYS))


def _stream_grade(parts: dict[str, float]) -> float:
    m = _stream_mass(parts)
    if m <= 1e-9:
        return 0.0
    return float(np.clip(_stream_fe(parts) / m, 0.0, 1.0))


def _passing_from_d80_mm(x_mm: float, d80_mm: float, n_rr: float = 1.20) -> float:
    d80 = max(float(d80_mm), 1e-6)
    exponent = -math.log(0.20) * (max(float(x_mm), 1e-9) / d80) ** n_rr
    return float(np.clip(1.0 - math.exp(-exponent), 0.0, 1.0))


def _scale_stream(parts: dict[str, float], factor: float) -> dict[str, float]:
    factor = max(float(factor), 0.0)
    return {k: max(parts.get(k, 0.0) * factor, 0.0) for k in _MASS_KEYS}


def _subtract_stream(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {k: max(a.get(k, 0.0) - b.get(k, 0.0), 0.0) for k in _MASS_KEYS}


def _write_stream_hidden(
    bus: dict,
    prefix: str,
    parts: dict[str, float],
    f325: float,
    f200: float,
    f25: float,
    d80: float,
    liberation_fe: float,
    liberation_gangue: float,
) -> None:
    bus[f"{prefix}_m"] = _stream_mass(parts)
    bus[f"{prefix}_tfe"] = _stream_grade(parts)
    bus[f"{prefix}_f325"] = f325
    bus[f"{prefix}_f200"] = f200
    bus[f"{prefix}_f25"] = f25
    bus[f"{prefix}_d80"] = d80
    bus[f"{prefix}_liberation_fe"] = liberation_fe
    bus[f"{prefix}_liberation_gangue"] = liberation_gangue
    for key in _MASS_KEYS:
        bus[f"{prefix}_{key}"] = parts.get(key, 0.0)


class TowerMillSystem:
    """
    塔磨段全部物理计算。

    读取 bus：
      _x_g_mag, _x_m_mag  （磁选精矿，经 RingBuffer 延迟后使用）
      _x_d3               （矿石可磨性系数）
      _x_d4               （公共管网水压，MPa）

    写入 bus（DCS 可观测量，18 个）：
      agg_tm_cyclone_pool_level
      agg_tm_cyclone_pool_valve_setpoint
      MC1_FET503_AI
      agg_tm_cyclone_feed_flow
      agg_tm_cyclone_pump_freq
      agg_tm_cyclone_pump_current
      agg_tm_cyclone_sand_valve_setpoint
      agg_tm_cyclone_sand_valve_feedback
      agg_tm_cyclone_sand_water_flow
      agg_tm_motor_current
      MC1_TM204_HDZC_1_WD_AI
      MC1_TM206_HDZC_2_WD_AI
      MC1_TM204_ZDJ_DZ_A_WD_AI
      MC1_TM206_ZDJ_DZ_B_WD_AI
      agg_tm_reducer_oil_temp
      agg_tm_reducer_outlet_temp
      agg_tm_cyclone_overflow_pool_level
      agg_tm_overflow_pump_current

    写入 bus（隐藏中间量，供下游及测试使用）：
      _x_f325_ov, _x_m_ov, _x_g_ov, _x_P_mech, _x_alpha_ov
    """

    def __init__(
        self,
        cfg: TowerMillConfig,
        sim_cfg: SimConfig,
        rng: np.random.Generator,
    ) -> None:
        self._cfg = cfg
        self._dt = sim_cfg.dt
        self._rng = rng

        # ── 段间时滞缓冲区（磁选 → 塔磨，capacity ≥ delay_steps + 1）────
        cap = cfg.delay_steps + 1
        self._buf_m_mag = RingBuffer(capacity=cap, default=cfg.m_mag_nom)
        self._buf_g_mag = RingBuffer(capacity=cap, default=cfg.g_mag_nom)
        total_fe_nom = cfg.m_mag_nom * cfg.g_mag_nom
        component_defaults = {
            "fe_mag": total_fe_nom * cfg.mag_fe_mag_frac_nom,
            "fe_hem": total_fe_nom * cfg.mag_fe_hem_frac_nom,
            "fe_carb": total_fe_nom * cfg.mag_fe_carb_frac_nom,
            "fe_sil": total_fe_nom * cfg.mag_fe_sil_frac_nom,
            "gangue": cfg.m_mag_nom * (1.0 - cfg.g_mag_nom),
        }
        self._buf_mag_parts = {
            key: RingBuffer(capacity=cap, default=value)
            for key, value in component_defaults.items()
        }
        self._buf_f200_mag = RingBuffer(capacity=cap, default=cfg.f200_mag_nom)
        self._buf_f325_mag = RingBuffer(capacity=cap, default=cfg.f325_sand_nom)
        self._buf_f25_mag = RingBuffer(capacity=cap, default=cfg.f25_mag_nom)
        self._buf_d80_mag = RingBuffer(capacity=cap, default=cfg.d80_tm_init)
        self._buf_lib_fe_mag = RingBuffer(capacity=cap, default=cfg.liberation_fe_feed_nom)
        self._buf_lib_gangue_mag = RingBuffer(capacity=cap, default=cfg.liberation_gangue_feed_nom)

        # ── 磨机排矿返回延迟缓冲区（tau_mill 步）──────────────────────────
        mill_cap = cfg.tau_mill + 1
        # 初始化为名义沉砂量（稳态预填充）
        Q_pump_nom = cfg.k_pump * cfg.f_pump_nom * math.sqrt(max(cfg.L_pool_init, 0.01))
        Q_sand_nom = (1.0 - cfg.alpha_0) * Q_pump_nom   # m³/s
        self._buf_Q_sand = RingBuffer(capacity=mill_cap, default=Q_sand_nom)

        # ── 泵池液位 ODE ─────────────────────────────────────────────────
        self._L_pool: float = cfg.L_pool_init
        self._b_pool: float = 0.0        # 液位传感器漂移偏置

        # ── 泵频率（初始化为额定值）──────────────────────────────────────
        self._f_pump: float = cfg.f_pump_init

        # ── 沉砂水阀（操作员间歇调整 + 执行机构一阶跟踪）────────────────
        self._u_sand_sp: float = cfg.u_sand_mean
        self._u_sand_fb: float = cfg.u_sand_mean
        self._t_last_adj: float = 0.0    # 上次阀门调整的时刻（s）

        # ── 塔磨粒度追踪（用于 P_mech 计算）──────────────────────────────
        self._d80_sand: float = cfg.d80_tm_init

        # ── 温度状态（ZOH 热力学，无数值稳定性问题）─────────────────────
        self._T_b1: float = cfg.T_b1_init
        self._T_b2: float = cfg.T_b2_init
        self._T_sA: float = cfg.T_sA_init
        self._T_red: float = cfg.T_red_init

        # ── 溢流泵池液位 ODE ──────────────────────────────────────────────
        self._L_ov: float = cfg.L_ov_init

        # ── 设备级聚合偏差 ───────────────────────────────────────────────
        self._tm_bias = self._rng.normal(0.0, cfg.train_cv_current, cfg.n_tm_units)
        self._train_flow_bias = self._rng.normal(0.0, cfg.train_cv_flow, cfg.n_cyclone_trains)
        self._train_current_bias = self._rng.normal(0.0, cfg.train_cv_current, cfg.n_cyclone_trains)
        self._train_level_bias = self._rng.normal(0.0, cfg.train_cv_level, cfg.n_cyclone_trains)

    def _mag_stream_from_bus(self, bus: dict) -> dict[str, float]:
        if all(f"_x_mag_{key}" in bus for key in _MASS_KEYS):
            return {key: float(bus[f"_x_mag_{key}"]) for key in _MASS_KEYS}

        m_mag = float(bus["_x_m_mag"])
        g_mag = float(np.clip(bus["_x_g_mag"], 0.0, 1.0))
        total_fe = m_mag * g_mag
        cfg = self._cfg
        return {
            "fe_mag": total_fe * cfg.mag_fe_mag_frac_nom,
            "fe_hem": total_fe * cfg.mag_fe_hem_frac_nom,
            "fe_carb": total_fe * cfg.mag_fe_carb_frac_nom,
            "fe_sil": total_fe * cfg.mag_fe_sil_frac_nom,
            "gangue": max(m_mag - total_fe, 0.0),
        }

    def _push_mag_stream(self, bus: dict) -> None:
        parts = self._mag_stream_from_bus(bus)
        for key in _MASS_KEYS:
            self._buf_mag_parts[key].push(parts[key])
        self._buf_f200_mag.push(float(bus.get("_x_f200_mag", self._cfg.f200_mag_nom)))
        self._buf_f325_mag.push(float(bus.get("_x_f325_mag", self._cfg.f325_sand_nom)))
        self._buf_f25_mag.push(float(bus.get("_x_f25_mag", self._cfg.f25_mag_nom)))
        self._buf_d80_mag.push(float(bus.get("_x_d80_mag", self._cfg.d80_tm_init)))
        self._buf_lib_fe_mag.push(float(bus.get("_x_liberation_fe_mag", self._cfg.liberation_fe_feed_nom)))
        self._buf_lib_gangue_mag.push(float(bus.get("_x_liberation_gangue_mag", self._cfg.liberation_gangue_feed_nom)))

    def _peek_delayed_mag_stream(self, delay_steps: int) -> tuple[dict[str, float], dict[str, float]]:
        parts = {
            key: self._buf_mag_parts[key].peek(delay_steps)
            for key in _MASS_KEYS
        }
        attrs = {
            "f200": self._buf_f200_mag.peek(delay_steps),
            "f325": self._buf_f325_mag.peek(delay_steps),
            "f25": self._buf_f25_mag.peek(delay_steps),
            "d80": self._buf_d80_mag.peek(delay_steps),
            "lib_fe": self._buf_lib_fe_mag.peek(delay_steps),
            "lib_gangue": self._buf_lib_gangue_mag.peek(delay_steps),
        }
        return parts, attrs

    # ────────────────────────────────────────────────────────────────────
    # 主步进函数
    # ────────────────────────────────────────────────────────────────────

    def step(self, bus: dict, t: int) -> None:
        """推进一步：读取 bus 上游量 → 物理计算 → 写入所有塔磨 DCS 变量。"""
        cfg = self._cfg
        dt = self._dt

        # ── 读取上游量（当前步）────────────────────────────────────────
        d3 = bus["_x_d3"]       # 可磨性系数
        d4 = bus["_x_d4"]       # 管网水压（MPa）
        d4_kpa = d4 * 1000.0    # 转换为 kPa，用于水阀计算

        # 将当前步混磁精矿压入延迟缓冲区
        self._buf_m_mag.push(bus["_x_m_mag"])
        self._buf_g_mag.push(bus["_x_g_mag"])
        self._push_mag_stream(bus)

        # 从缓冲区取 delay_steps 步前的输入（段间时滞）
        m_mag_delayed = self._buf_m_mag.peek(cfg.delay_steps)
        g_mag_delayed = self._buf_g_mag.peek(cfg.delay_steps)
        mag_parts_delayed, mag_attrs_delayed = self._peek_delayed_mag_stream(cfg.delay_steps)
        g_mag_components = _stream_grade(mag_parts_delayed)
        if _stream_mass(mag_parts_delayed) > 1e-9:
            g_mag_delayed = g_mag_components

        # ── 1. 泵池液位动力学 ─────────────────────────────────────────
        # 磁精矿入池体积流量（m³/s）
        Q_mag_in = m_mag_delayed * 1000.0 / 3600.0 / cfg.rho_slurry_mag

        # 取 tau_mill 步前的沉砂量返回泵池
        Q_sand_return = self._buf_Q_sand.peek(cfg.tau_mill)

        # 泵池液位测量（含漂移）
        L_meas_raw, self._b_pool = add_drift(
            self._L_pool, self._b_pool, cfg.sigma_b_pool, self._rng
        )
        L_meas = add_noise(L_meas_raw, cfg.sigma_L_pool, self._rng)
        L_meas_clipped = float(np.clip(L_meas, 0.0, 10.0))

        # 泵频率控制（一阶跟踪 + 液位反馈）
        # L > L_sp → f_target > f_nom（加快泵送，降低液位）
        # L < L_sp → f_target < f_nom（减慢泵送，液位回升）
        f_target = cfg.f_pump_nom + cfg.k_fb_pump * (self._L_pool - cfg.L_pool_setpoint)
        f_target = float(np.clip(f_target, cfg.f_pump_min, cfg.f_pump_max))
        self._f_pump = (
            cfg.phi_f_pump * self._f_pump
            + (1.0 - cfg.phi_f_pump) * f_target
            + self._rng.normal(0.0, cfg.sigma_eta_f)
        )
        self._f_pump = float(np.clip(self._f_pump, cfg.f_pump_min, cfg.f_pump_max))
        f_pump_dcs = add_noise(self._f_pump, cfg.sigma_eta_f, self._rng)
        f_pump_dcs = float(np.clip(f_pump_dcs, cfg.f_pump_min, cfg.f_pump_max))

        # 泵排量
        Q_pump = cfg.k_pump * self._f_pump * math.sqrt(max(self._L_pool, 0.0))

        # 泵池水阀设定（比例控制）
        u_pool_sp = float(np.clip(
            cfg.u_pool_mean + cfg.k_pool_pid * (cfg.L_pool_setpoint - L_meas_clipped),
            0.0, 1.0,
        ))
        # 泵池补水流量（d4 用 kPa 单位）
        Q_pool_water = cfg.C_v_pool * u_pool_sp * math.sqrt(max(d4_kpa, 0.0))
        Q_pool_water = max(Q_pool_water, 0.0)

        # 泵池液位 ODE（前向欧拉）
        dL_pool = (Q_mag_in + Q_sand_return + Q_pool_water - Q_pump) / cfg.A_pool
        self._L_pool += dL_pool * dt
        self._L_pool = float(np.clip(self._L_pool, 0.0, 5.0))

        # DCS 液位读数
        L_pool_dcs = add_noise(self._L_pool + self._b_pool, cfg.sigma_L_pool, self._rng)

        # 旋流器给矿流量 DCS（含高频震荡）
        Q_cyc_feed_dcs = add_noise(
            Q_pump + cfg.k_Lf * dL_pool,
            cfg.sigma_Q_feed,
            self._rng,
        )
        Q_cyc_feed_dcs = max(Q_cyc_feed_dcs, 0.0)

        # ── 2. 旋流器分级 ─────────────────────────────────────────────
        # 旋流器给矿压力（kPa）
        f_ratio = self._f_pump / max(cfg.f_pump_nom, 1.0)
        P_cyc = cfg.k_P_cyc * cfg.rho_slurry_nom * f_ratio ** 2

        # 溢流率
        d80_effect = 1.0 - math.exp(-max(self._d80_sand, 0.0) / cfg.d_ref_cyc)
        alpha_ov = float(np.clip(
            cfg.alpha_0
            + cfg.k_alpha_d * d80_effect
            - cfg.k_alpha_P * P_cyc
            + self._rng.normal(0.0, cfg.sigma_alpha),
            0.05, 0.95,
        ))

        Q_ov = alpha_ov * Q_pump          # 溢流体积流量（m³/s）
        Q_sand = (1.0 - alpha_ov) * Q_pump  # 沉砂体积流量（m³/s）

        Q_mag_in_safe = max(Q_mag_in, 1e-9)
        cyclone_feed_scale = float(np.clip(Q_pump / Q_mag_in_safe, 0.1, 8.0))
        cyclone_feed_parts = _scale_stream(mag_parts_delayed, cyclone_feed_scale)
        cyclone_overflow_parts = _scale_stream(cyclone_feed_parts, alpha_ov)
        cyclone_sand_parts = _subtract_stream(cyclone_feed_parts, cyclone_overflow_parts)

        # 推入沉砂量缓冲区（延迟后返回泵池）
        self._buf_Q_sand.push(Q_sand)

        # 沉砂质量流量（t/h，湿态）
        m_sand = Q_sand * cfg.rho_slurry_nom * 3600.0 / 1000.0

        # ── 3. 沉砂水阀（前置，为 §4.6 矿浆密度路径提供 Q_sand_water）────
        t_sec = t * dt
        if t_sec - self._t_last_adj >= cfg.T_adj_sand:
            adj = self._rng.normal(0.0, cfg.sigma_sand_adj)
            self._u_sand_sp = float(np.clip(cfg.u_sand_mean + adj, 0.0, 1.0))
            self._t_last_adj = t_sec
        tau_act = max(cfg.tau_act_sand, dt)
        self._u_sand_fb += (dt / tau_act) * (self._u_sand_sp - self._u_sand_fb)
        u_sand_fb_dcs = add_noise(self._u_sand_fb, cfg.sigma_u_sand_fb, self._rng)
        u_sand_fb_dcs = float(np.clip(u_sand_fb_dcs, 0.0, 1.0))

        Q_sand_water = cfg.C_v_sand * self._u_sand_fb * math.sqrt(max(d4_kpa, 0.0))
        Q_sand_water = max(Q_sand_water, 0.0)
        Q_sand_water_dcs = add_noise(Q_sand_water, cfg.sigma_Q_sand_water, self._rng)

        # ── 4. 磨内矿浆密度（沉砂浆体 + 补水混合，设计文档 §4.6）─────────
        # Q_sand_water → ρ_slurry,mill → P_mech → f_{-325μm,ov} → TFe
        Q_mix = max(Q_sand + Q_sand_water, 1e-9)
        rho_mill = (Q_sand * cfg.rho_slurry_nom + Q_sand_water * 1000.0) / Q_mix

        # ── 5. 塔磨研磨动力学 ────────────────────────────────────────
        # 沉砂中 −325目含量（名义值）
        f325_sand = cfg.f325_sand_nom

        # 机械功率（含矿浆密度偏差项，设计文档 §4.6）
        P_mech = (
            cfg.P0_mech
            + cfg.k_ms * m_sand
            + cfg.k_md * (1.0 - f325_sand)
            + cfg.k_mrho * (rho_mill - cfg.rho_slurry_nom)
            + self._rng.normal(0.0, cfg.sigma_P_mech)
        )
        P_mech = float(np.clip(P_mech, 0.0, cfg.P_rated * 1.1))

        # 研磨后出料粒度（Bond 简化模型）
        m_sand_kg_s = max(m_sand * 1000.0 / 3600.0, 0.1)  # kg/s
        grind_rate = cfg.k_mill * P_mech / (m_sand_kg_s * max(d3, 0.1))
        d80_disch = self._d80_sand * math.exp(-grind_rate * dt)
        d80_disch = float(np.clip(d80_disch, 0.005, cfg.d80_tm_init * 2.0))
        self._d80_sand = d80_disch
        f325_discharge = _passing_from_d80_mm(0.045, d80_disch)

        # 溢流 −325目含量
        f325_ov = float(np.clip(
            cfg.f325_ov_base
            + cfg.k_f325 * (P_mech / cfg.P_rated)
            + self._rng.normal(0.0, cfg.sigma_f325),
            0.0, 1.0,
        ))
        f325_feed = float(np.clip(mag_attrs_delayed["f325"], 0.0, 1.0))
        f200_feed = float(np.clip(mag_attrs_delayed["f200"], 0.0, 1.0))
        f25_feed = float(np.clip(mag_attrs_delayed["f25"], 0.0, 1.0))
        d80_feed = float(max(mag_attrs_delayed["d80"], 1e-6))
        delta_f325 = f325_ov - f325_feed
        E_spec = P_mech / max(m_sand, 1e-6)
        lib_fe_over = float(np.clip(
            mag_attrs_delayed["lib_fe"]
            + cfg.lib_class_fe_gain * delta_f325
            + cfg.lib_energy_fe_gain * math.log1p(E_spec / max(cfg.E_spec_ref, 1e-6)),
            0.0,
            1.0,
        ))
        lib_gangue_over = float(np.clip(
            mag_attrs_delayed["lib_gangue"]
            + cfg.lib_class_gangue_gain * delta_f325
            + cfg.lib_energy_gangue_gain * math.log1p(E_spec / max(cfg.E_spec_ref, 1e-6)),
            0.0,
            1.0,
        ))
        # 第一版沉砂粒级按更粗处理，解离度用残余趋势近似，避免复制溢流。
        f325_sand_stream = float(np.clip(min(f325_feed, cfg.f325_sand_nom), 0.0, 1.0))
        f200_sand_stream = float(np.clip(min(f200_feed, cfg.f200_mag_nom), 0.0, 1.0))
        f25_sand_stream = float(np.clip(min(f25_feed, cfg.f25_mag_nom), 0.0, 1.0))
        lib_fe_sand = float(np.clip(mag_attrs_delayed["lib_fe"] - 0.08 * max(delta_f325, 0.0), 0.0, 1.0))
        lib_gangue_sand = float(np.clip(mag_attrs_delayed["lib_gangue"] - 0.14 * max(delta_f325, 0.0), 0.0, 1.0))

        # ── 6. 主电机电流 ─────────────────────────────────────────────
        I_motor = P_mech * 1000.0 / (_SQRT3 * cfg.V_line_tm * cfg.cos_phi_motor)
        I_motor_dcs = add_noise(I_motor, cfg.sigma_I_motor_tm, self._rng)

        # ── 7. 泵电流 ────────────────────────────────────────────────
        H_pump = max(cfg.a0_pump - cfg.a1_pump * Q_pump ** 2, 0.0)
        P_pump_W = (cfg.rho_slurry_nom * 9.81 * H_pump * Q_pump) / cfg.eta_pump
        I_pump = P_pump_W / (_SQRT3 * cfg.V_pump * cfg.cos_phi_pump)
        I_pump_dcs = add_noise(I_pump, cfg.sigma_I_pump, self._rng)
        Q_pump_dcs = add_noise(Q_pump, cfg.sigma_Q_pump, self._rng)  # noqa: F841

        # ── 8. 轴承温度（ZOH + 故障注入）────────────────────────────
        T_ss_b1 = cfg.T_amb + cfg.k_b1_kw * P_mech
        self._T_b1 = _zoh_step(self._T_b1, T_ss_b1, cfg.tau_b1, dt)
        T_b1_dcs = inject_fault(
            add_noise(self._T_b1, cfg.sigma_b1, self._rng),
            cfg.p_fault_bearing,
            cfg.fault_val_bearing,
            self._rng,
        )

        T_ss_b2 = cfg.T_amb + cfg.k_b2_kw * P_mech
        self._T_b2 = _zoh_step(self._T_b2, T_ss_b2, cfg.tau_b2, dt)
        T_b2_dcs = inject_fault(
            add_noise(self._T_b2, cfg.sigma_b2, self._rng),
            cfg.p_fault_bearing,
            cfg.fault_val_bearing,
            self._rng,
        )

        # ── 9. 定子温度（ZOH + 故障注入）────────────────────────────
        T_ss_sA = cfg.T_coolant + cfg.k_sA_a2 * I_motor ** 2
        self._T_sA = _zoh_step(self._T_sA, T_ss_sA, cfg.tau_sA, dt)
        T_sA_dcs = inject_fault(
            add_noise(self._T_sA, cfg.sigma_sA, self._rng),
            cfg.p_fault_stator,
            cfg.fault_val_stator,
            self._rng,
        )
        T_sB = self._T_sA + cfg.dT_AB + self._rng.normal(0.0, cfg.sigma_AB)
        T_sB_dcs = inject_fault(
            add_noise(T_sB, cfg.sigma_sA, self._rng),
            cfg.p_fault_stator,
            cfg.fault_val_stator,
            self._rng,
        )

        # ── 10. 减速机温度（ZOH）──────────────────────────────────────
        P_loss_kw = P_mech * (1.0 - cfg.eta_red) / cfg.eta_red
        T_ss_red = cfg.T_amb + cfg.k_red_kw * P_loss_kw
        self._T_red = _zoh_step(self._T_red, T_ss_red, cfg.tau_red, dt)
        T_red_dcs = add_noise(self._T_red, cfg.sigma_red, self._rng)
        T_red_out = cfg.alpha_pipe * self._T_red + (1.0 - cfg.alpha_pipe) * cfg.T_amb
        T_red_out_dcs = add_noise(T_red_out, cfg.sigma_red_out, self._rng)

        # ── 11. 溢流泵池液位 ODE ─────────────────────────────────────
        Q_ov_pump = cfg.Q_ov_pump_nom if self._L_ov > cfg.L_ov_low else 0.0
        dL_ov = (Q_ov - Q_ov_pump) / cfg.A_ov
        self._L_ov += dL_ov * dt
        self._L_ov = float(np.clip(self._L_ov, 0.0, 5.0))
        L_ov_dcs = add_noise(self._L_ov, cfg.sigma_L_ov, self._rng)

        # ── 12. 溢流泵电流 ────────────────────────────────────────────
        pump_on = 1.0 if self._L_ov > cfg.L_ov_low else 0.0
        I_ov_pump = (
            cfg.I_ov_0 * pump_on
            + cfg.k_ov_I * Q_ov_pump * cfg.rho_ov / 1000.0
        )
        I_ov_pump_dcs = add_noise(I_ov_pump, cfg.sigma_I_ov, self._rng)

        # ── 溢流质量流量 & 品位（供下游浮选段使用）───────────────────
        m_ov = Q_ov * cfg.rho_ov * 3600.0 / 1000.0   # t/h（湿态，溢流密度 ~14.93%）
        c_ov = (cfg.rho_ov - 1000.0) / (2700.0 - 1000.0) * (2700.0 / cfg.rho_ov)
        g_ov = _stream_grade(cyclone_overflow_parts)

        # ── 写入 bus（DCS 可观测量）───────────────────────────────────
        load_ratio = float(np.clip(Q_pump / max(cfg.k_pump * cfg.f_pump_nom * math.sqrt(max(cfg.L_pool_setpoint, 0.01)), 1e-9), 0.0, 1.8))
        tm_on = int(np.clip(round(cfg.n_tm_units * load_ratio), cfg.tm_units_min, cfg.tm_units_max))
        train_on = int(np.clip(round(cfg.n_cyclone_trains * load_ratio), cfg.cyclone_trains_min, cfg.n_cyclone_trains))
        tm_active = active_mask(cfg.n_tm_units, tm_on)
        train_active = active_mask(cfg.n_cyclone_trains, train_on)

        train_feed_flow = Q_cyc_feed_dcs * (1.0 + self._train_flow_bias)
        train_pump_current = I_pump_dcs * (1.0 + self._train_current_bias)
        train_pool_level = L_pool_dcs * (1.0 + self._train_level_bias)
        train_ov_level = L_ov_dcs * (1.0 + self._train_level_bias)
        train_sand_water = Q_sand_water_dcs * (1.0 + self._train_flow_bias)
        tm_motor_current = I_motor_dcs * (1.0 + self._tm_bias)
        tm_reducer_temp = T_red_dcs + 5.0 * self._tm_bias
        tm_reducer_out = T_red_out_dcs + 4.0 * self._tm_bias

        bus["tm_units_on"] = tm_on
        bus["tm_cyclone_trains_on"] = train_on
        write_aggregate(bus, "agg_tm_cyclone_pool_level", aggregate_active(train_pool_level, train_active))
        bus["agg_tm_cyclone_pool_valve_setpoint"] = u_pool_sp
        bus["MC1_FET503_AI"] = Q_pool_water
        write_aggregate(bus, "agg_tm_cyclone_feed_flow", aggregate_active(train_feed_flow, train_active))
        bus["agg_tm_cyclone_pump_freq"] = f_pump_dcs
        write_aggregate(bus, "agg_tm_cyclone_pump_current", aggregate_active(train_pump_current, train_active))
        bus["agg_tm_cyclone_sand_valve_setpoint"] = self._u_sand_sp
        bus["agg_tm_cyclone_sand_valve_feedback"] = u_sand_fb_dcs
        write_aggregate(bus, "agg_tm_cyclone_sand_water_flow", aggregate_active(train_sand_water, train_active))
        write_aggregate(bus, "agg_tm_motor_current", aggregate_active(tm_motor_current, tm_active))
        bus["MC1_TM204_HDZC_1_WD_AI"] = T_b1_dcs
        bus["MC1_TM206_HDZC_2_WD_AI"] = T_b2_dcs
        bus["MC1_TM204_ZDJ_DZ_A_WD_AI"] = T_sA_dcs
        bus["MC1_TM206_ZDJ_DZ_B_WD_AI"] = T_sB_dcs
        write_aggregate(bus, "agg_tm_reducer_oil_temp", aggregate_active(tm_reducer_temp, tm_active))
        write_aggregate(bus, "agg_tm_reducer_outlet_temp", aggregate_active(tm_reducer_out, tm_active))
        write_aggregate(bus, "agg_tm_cyclone_overflow_pool_level", aggregate_active(train_ov_level, train_active))
        bus["agg_tm_overflow_pump_current"] = I_ov_pump_dcs

        # ── 写入 bus（隐藏中间量）────────────────────────────────────
        bus["_x_f325_ov"] = f325_ov
        bus["_x_m_ov"] = m_ov
        bus["_x_g_ov"] = g_ov
        bus["_x_P_mech"] = P_mech
        bus["_x_alpha_ov"] = alpha_ov
        bus["_x_tm_cyclone_feed_pressure"] = P_cyc
        bus["_x_tm_E_spec"] = E_spec
        bus["_x_tm_discharge_f325"] = f325_discharge
        bus["_x_tm_discharge_d80"] = d80_disch
        bus["_x_tm_overflow_conc"] = float(np.clip(c_ov, 0.0, 1.0))

        _write_stream_hidden(
            bus,
            "_x_tm_cyclone_feed",
            cyclone_feed_parts,
            f325_feed,
            f200_feed,
            f25_feed,
            d80_feed,
            mag_attrs_delayed["lib_fe"],
            mag_attrs_delayed["lib_gangue"],
        )
        _write_stream_hidden(
            bus,
            "_x_tm_cyclone_overflow",
            cyclone_overflow_parts,
            f325_ov,
            f200_feed,
            f25_feed,
            d80_disch,
            lib_fe_over,
            lib_gangue_over,
        )
        _write_stream_hidden(
            bus,
            "_x_tm_cyclone_sand",
            cyclone_sand_parts,
            f325_sand_stream,
            f200_sand_stream,
            f25_sand_stream,
            self._d80_sand,
            lib_fe_sand,
            lib_gangue_sand,
        )
        _write_stream_hidden(
            bus,
            "_x_tm_overflow",
            cyclone_overflow_parts,
            f325_ov,
            f200_feed,
            f25_feed,
            d80_disch,
            lib_fe_over,
            lib_gangue_over,
        )
        for key in _MASS_KEYS:
            bus[f"_x_tm_overflow_{key}"] = cyclone_overflow_parts.get(key, 0.0)
