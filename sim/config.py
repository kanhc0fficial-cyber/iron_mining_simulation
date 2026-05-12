"""
全局仿真参数配置（唯一参数入口）。

所有 Config 对象在 run_simulation.py 中构造并以构造函数参数传入各子系统，
不使用全局变量。
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class SimConfig:
    """顶层仿真控制参数。"""
    dt: int = 60                 # 仿真步长（秒）
    n_steps: int = 43_200        # 总步数（30天 = 43200步）
    seed: int = 42               # 全局随机种子
    warm_up_steps: int = 300     # 预热步数（使动态状态达到稳态）


@dataclass
class DisturbanceConfig:
    """外生扰动过程（OU过程）参数。"""
    # d1: 球磨溢流 TFe 品位（隐藏）
    d1_mean: float = 0.3149
    d1_phi: float = 0.99
    d1_sigma: float = 0.0005
    d1_min: float = 0.25
    d1_max: float = 0.38

    # d2: 碳酸铁含量（隐藏）
    d2_mean: float = 0.018
    d2_phi: float = 0.99
    d2_sigma: float = 0.0002
    d2_min: float = 0.01
    d2_max: float = 0.04

    # d3: 矿石可磨性系数（隐藏）
    d3_mean: float = 1.0
    d3_phi: float = 0.99
    d3_sigma: float = 0.01
    d3_min: float = 0.8
    d3_max: float = 1.2

    # d4: 公共管网水压（MPa，间接可测）
    d4_mean: float = 0.40
    d4_phi: float = 0.99
    d4_sigma: float = 0.002
    d4_min: float = 0.30
    d4_max: float = 0.50

    # d1–d2 地质相关性（碳酸铁高时原矿品位往往偏低）
    cov_d1d2: float = -0.6


@dataclass
class BallMillConfig:
    """球磨溢流边界输入参数（3条线并联，AR(1)过程）。"""
    n_lines: int = 3                  # 球磨线数

    m_ball_mean: float = 265.0        # t/h per line, 正常运行均值
    m_ball_phi: float = 0.98
    m_ball_sigma: float = 2.0
    m_ball_min: float = 240.0
    m_ball_max: float = 290.0

    rho_ball_mean: float = 0.385      # 球磨溢流浓度（质量分数，无量纲）
    rho_ball_phi: float = 0.97
    rho_ball_sigma: float = 0.005
    rho_ball_min: float = 0.345
    rho_ball_max: float = 0.425

    d80_ball_mean: float = 0.074      # mm，球磨溢流 d80 粒度
    d80_ball_phi: float = 0.97
    d80_ball_sigma: float = 0.003
    d80_ball_min: float = 0.050
    d80_ball_max: float = 0.110

    # f_{-25μm} 反 S 形函数参数
    # f25 = f25_max * sigmoid(k_f25 * (d80_ref - d80) + bias_f25) + noise
    # bias_f25 = logit(f25_ref / f25_max) 保证 d80 = d80_ref 时 f25 = f25_ref
    f25_max: float = 0.80
    k_f25: float = 60.0
    d80_ref: float = 0.074            # mm，标定参考点
    f25_ref: float = 0.5419           # 文档标定值（d80=d80_ref 时的 f25）
    bias_f25: float = 0.7417          # logit(0.5419/0.80)，使标定点精确通过
    sigma_f25: float = 0.005

    # 三条线之间相关系数（共用同一扰动分量驱动）
    rho_lines: float = 0.70


@dataclass
class MagSepConfig:
    """磁选段参数（弱磁+强磁前浓缩+强磁+扫强磁）。

    标定基准（来自考查报告）：
      - d1=31.49% → 弱磁精矿 51.29%，作业回收率 45.23%
      - 强磁给矿 23.91% → 强磁精矿 40.73%，回收率 67.99%
      - 混磁精矿品位 43.84%
    """

    # ── 弱磁选（准静态代数）────────────────────────────────────────────
    # g_wmag = d1 * k_wm_Fe / (1 + k_wm_Si * (1 - d1))
    # 标定：d1=0.3149 → g_wmag=0.5129; k_wm_Si 取 1.0
    k_wm_Fe: float = 2.744
    k_wm_Si: float = 1.0
    # beta_wm = beta_wm0 * (1 - k_wm_f25 * f25)  [铁作业回收率]
    # 标定：beta_wm0 = 0.4523；k_wm_f25=0 保证标定点精确通过
    beta_wm0: float = 0.4523
    k_wm_f25: float = 0.0

    # ── 强磁前浓缩（一阶滞后）─────────────────────────────────────────
    tau_conc: float = 120.0           # s
    rho_conc_target: float = 0.45     # 底流浓度（质量分数）

    # ── 励磁系统（热-电耦合）──────────────────────────────────────────
    V_nom: float = 80.0               # V DC 额定励磁电压
    R0_coil: float = 3.0              # Ω，线圈冷阻（20°C）
    alpha_Cu: float = 0.00393         # /°C，铜电阻温度系数
    T0_coil: float = 20.0             # °C，冷阻参考温度
    T_amb: float = 25.0               # °C，环境温度

    # 线圈热力学：tau * dT/dt = I²R - k_cool*(T - T_amb)
    # 稳态: T_ss = T_amb + I_nom²*R_nom / k_cool ≈ 68°C（在 60~80°C 范围内）
    tau_thermal_coil: float = 1800.0  # s，热时间常数
    k_cool_coil: float = 50.0         # W/°C，散热系数

    # 励磁电压 AR(1)
    phi_V_exc: float = 0.999
    sigma_V_exc: float = 0.05         # V
    sigma_I_exc: float = 0.01         # A
    sigma_T_coil: float = 0.2         # °C

    # ── 磁场与粒子力学（归一化力竞争模型）────────────────────────────
    # B = mu0_N_over_l * I_exc，其中 mu0_N_over_l = mu0*N/l_gap
    # 取 N=500，l_gap=0.05m：mu0_N_over_l = 4π×10⁻⁷*500/0.05 ≈ 0.01257
    # 使 I_nom=26.7A 时 B_nom ≈ 0.34 T
    mu0_N_over_l: float = 0.01257     # H/m

    # 粒径模型：dp = dp_ref * sqrt(1 - f25)
    dp_ref: float = 50e-6             # m，参考粒径（对应 f25=0）
    f25_nom: float = 0.5419           # 文档标定 f25 参考值

    # 归一化力竞争 sigmoid：
    # force_balance = (B/B_nom)² / (v_norm * dp_norm²)
    # beta_strong = sigmoid(lambda_s * log(force_balance) + bias_s)
    # bias_s = logit(0.6799)，使名义点 beta_strong = 0.6799
    lambda_s: float = 1.0
    bias_s: float = 0.7534            # logit(0.6799)

    # 名义矿浆流速（m/s），用于归一化 v_slurry
    v_nom: float = 0.10
    # 浆体参数
    rho_conc_kg_m3: float = 1450.0    # kg/m³，~45% 浓度浆体密度
    A_cross: float = 1.5              # m²，LHGC-3000 横截面积
    f_matrix: float = 0.30            # 介质（磁球）填充率
    k_ring_v: float = 0.50            # 转环频率对流速的修正系数

    # ── 强磁精矿品位（代数公式，类似弱磁）────────────────────────────
    # g_strong = g_feed * k_s_Fe / (1 + k_s_Si * (1 - g_feed))
    # 标定：g_feed=0.2391 → g_strong=0.4073；k_s_Si=2.0
    k_s_Fe: float = 4.296
    k_s_Si: float = 2.0

    # ── 扫强磁精矿品位（代数公式）────────────────────────────────────
    # g_sweep = g_feed * k_sw_Fe / (1 + k_sw_Si * (1 - g_feed))
    # 标定：g_feed≈0.1274 → g_sweep≈0.3167；k_sw_Si=2.0
    k_sw_Fe: float = 6.82
    k_sw_Si: float = 2.0
    beta_sweep_Fe: float = 0.55       # 扫强磁铁作业回收率

    # ── 液位控制（PID + 质量守恒ODE）──────────────────────────────────
    L_setpoint: float = 1.5           # m，液位设定值
    L_init: float = 1.5               # m，液位初始值
    Kp_L: float = 0.5
    Ki_L: float = 0.01
    Kd_L: float = 0.0
    A_tank_mag: float = 5.0           # m²，选别槽截面积
    L_overflow_mag: float = 2.0       # m，溢流堰高度
    k_conc_mag: float = 0.008         # m²/s，溢流堰系数
    C_v_mag: float = 0.090            # m^{5/2}/s，阀门流量系数（标定：阀1全开稳态Q≈Q_in）

    # 液位传感器漂移与噪声
    sigma_b_level: float = 0.02       # m，随机游走漂移步噪声
    sigma_L_level: float = 0.01       # m，测量白噪声

    # ── 排污阀（周期脉冲）──────────────────────────────────────────────
    T_blow: float = 28800.0           # s，排污周期（8小时）
    dt_blow: float = 300.0            # s，排污持续时间
    u_blow_on: float = 1.0
    sigma_blow: float = 0.02

    # ── 操作员设定量（AR(1)）──────────────────────────────────────────
    f_pul_mean: float = 300.0         # /min，脉动频率均值
    phi_pul: float = 0.999
    sigma_pul: float = 0.5

    f_ring_mean: float = 2.0          # Hz，转环频率均值
    phi_ring: float = 0.999
    sigma_ring: float = 0.01

    # ── 电机电流─────────────────────────────────────────────────────────
    I_motor_0: float = 20.0           # A，空载基础电流
    k_mf: float = 0.05                # A/(t/h)，给矿量系数
    k_mr: float = 2.0                 # A/Hz，转环频率系数
    k_mm: float = 0.02                # A/(t/h)，beta_strong*给矿 耦合系数
    sigma_I_motor: float = 0.5        # A

    # ── 电机电压（电网波动）──────────────────────────────────────────
    V_motor_nom: float = 380.0        # V，额定线电压
    phi_Vgrid: float = 0.99
    sigma_Vgrid: float = 1.0          # V
    sigma_V_motor: float = 0.5        # V

    # ── 冲矿水压力──────────────────────────────────────────────────────
    k_pipe: float = 50.0              # kPa·h²/m⁶，管路阻力系数（近似）
    Q_flush: float = 0.01             # m³/s，冲矿水量（操作员设定）
    sigma_P_flush: float = 0.002      # MPa，压力测量噪声
