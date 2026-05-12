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
    open_loop: bool = False      # 开环激励模式（PRBS加药 + 扩大d1扰动）


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

    # 开环模式下 d1 扰动幅度放大倍数（≥1.0）
    d1_sigma_open_factor: float = 10.0


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


@dataclass
class TowerMillConfig:
    """塔磨段参数（旋流器分级 + 塔磨机研磨 + 温度场）。

    标定基准（来自考查报告）：
      - P_mech ∈ [730, 950] kW（CSM-1120，65~85% 负载）
      - 溢流 −325目 ≥ 92.5%
      - 旋流器分级质效率 ≈ 24.81%（即稳态溢流率 α_ov ≈ 0.2481）

    说明：
      溢流率 α_ov 在本模型中直接作为「分级质效率」的近似量，
      标定取 α_0 = 0.2481，使名义稳态与考查报告数据吻合。

    关键功率参数：
      k_mrho — 矿浆密度对 P_mech 的贡献（kW/(kg/m³)，偏差量，设计文档 §4.6）。
               偏差形式：k_mrho * (ρ_mill - ρ_nom)，ρ_nom 时贡献为零，保持基础标定不变。
               沉砂补水（Q_sand_water）→ ρ_mill → P_mech 即为此路径。
    """

    # ── 段间时滞（磁选 → 塔磨，RingBuffer 延迟）───────────────────────────
    delay_steps: int = 20             # 20 min = 20 步 @ 60 s/步

    # 名义混磁精矿参数（用于初始化延迟缓冲区）
    m_mag_nom: float = 526.0          # t/h，名义混磁精矿质量流量
    g_mag_nom: float = 0.4384         # 名义混磁精矿 TFe 品位
    rho_slurry_mag: float = 1500.0    # kg/m³，磁精矿浆体密度（~45% 浓度）

    # ── 给矿泵池（pump pool）──────────────────────────────────────────────
    A_pool: float = 8.0               # m²，泵池截面积
    L_pool_init: float = 1.8          # m，液位初始值
    L_pool_setpoint: float = 1.8      # m，液位设定值

    # 泵池补水阀（比例控制）
    k_pool_pid: float = 0.4           # 1/m，泵池水阀比例增益
    u_pool_mean: float = 0.50         # 基础开度（操作员设定）
    C_v_pool: float = 0.0010          # m³/(s·kPa^0.5)，水阀流量系数
    sigma_b_pool: float = 0.020       # m，液位传感器漂移步噪声
    sigma_L_pool: float = 0.010       # m，液位测量白噪声

    # 三旋给矿泵（离心泵，变频调速）
    # Q_pump = k_pump * f_pump * sqrt(max(L_pool, 0))
    k_pump: float = 0.0083            # m³/(s·Hz·m^0.5)，泵流量系数
    f_pump_init: float = 40.0         # Hz，初始频率
    f_pump_nom: float = 40.0          # Hz，名义频率
    f_pump_min: float = 30.0          # Hz
    f_pump_max: float = 50.0          # Hz
    # 频率跟踪：f(t) = phi_f*f(t-1) + (1-phi_f)*[f_nom + k_fb*(L-Lsp)] + eta
    phi_f_pump: float = 0.85          # 频率 AR(1) 平滑系数
    k_fb_pump: float = 5.0            # Hz/m，液位误差反馈增益
    sigma_eta_f: float = 0.10         # Hz，频率噪声

    # 泵电流模型（水力功率 → 电流）
    a0_pump: float = 35.0             # m，额定扬程（零流量）
    a1_pump: float = 5.0e-4           # m/(m³/s)²，扬程曲线斜率
    eta_pump: float = 0.80            # 泵效率
    V_pump: float = 380.0             # V，泵电机线电压
    cos_phi_pump: float = 0.85        # 功率因数
    sigma_I_pump: float = 0.30        # A，电流测量噪声
    sigma_Q_pump: float = 0.0030      # m³/s，流量测量噪声

    # ── 旋流器分级（cyclone）──────────────────────────────────────────────
    # α_ov(t) = clip(α_0 + k_αd*(1-exp(-d80/d_ref)) - k_αP*P_cyc + w, 0.05, 0.95)
    alpha_0: float = 0.2481           # 基础溢流率（标定：分级质效率 24.81%）
    k_alpha_d: float = 0.05           # d80 粒度对溢流率的影响
    k_alpha_P: float = 0.00005        # 旋流器压力对溢流率的影响（1/kPa）
    d_ref_cyc: float = 0.060          # mm，粒度归一化参考点
    # P_cyc = k_P_cyc * rho_slurry * (f_pump/f_nom)²  [kPa]
    k_P_cyc: float = 0.30             # kPa·m³/kg，旋流器给矿压力系数
    sigma_alpha: float = 0.008        # 分级效率随机噪声

    # 旋流器给矿流量传感器（含高频宽幅震荡特性）
    k_Lf: float = 5.0                 # 液位导数对流量读数的影响倍数
    sigma_Q_feed: float = 0.0030      # m³/s，流量计白噪声

    # ── 塔磨研磨动力学（闭路研磨）────────────────────────────────────────
    d80_tm_init: float = 0.060        # mm，磨机入料初始 d80（沉砂）
    tau_mill: int = 8                 # 步，磨矿停留时间（8 min @ 60s/步）
    k_mill: float = 0.0025            # 研磨速率常数（Bond 简化模型）
    P_rated: float = 1120.0           # kW，CSM-1120 额定功率

    # P_mech = P0 + k_ms*m_sand[t/h] + k_md*(1-f325_sand) + k_mrho*(ρ_mill-ρ_nom) + noise
    # 标定：P0=250kW，k_ms=0.32kW/(t/h)，名义 m_sand≈1920t/h → P≈865kW（密度项偏差约-13kW）
    P0_mech: float = 250.0            # kW，空载功率
    k_ms: float = 0.32                # kW/(t/h)，沉砂量对功率的贡献
    k_md: float = 40.0                # kW，粒度粗度贡献
    k_mrho: float = 0.20              # kW/(kg/m³)，矿浆密度偏差对功率的贡献（设计文档 §4.6）
    sigma_P_mech: float = 5.0         # kW，功率测量噪声
    rho_slurry_nom: float = 1450.0    # kg/m³，旋流器给矿浆体名义密度

    # −325目模型：f325_ov = f325_ov_base + k_f325*(P_mech/P_rated)
    # 标定：P=808kW → f325=0.900+0.040*0.721=0.929≥0.925 ✓
    f325_ov_base: float = 0.900       # 基础溢流 −325目含量
    k_f325: float = 0.040             # P_mech/P_rated 对 −325目的贡献
    sigma_f325: float = 0.003         # 噪声
    f325_sand_nom: float = 0.55       # 名义沉砂 −325目含量（用于 P_mech 计算）

    # ── 主电机（6kV，CSM-1120）────────────────────────────────────────────
    V_line_tm: float = 6000.0         # V，电机线电压
    cos_phi_motor: float = 0.88       # 功率因数
    sigma_I_motor_tm: float = 0.50    # A，电流测量噪声

    # ── 沉砂补水阀（操作员间歇调整）──────────────────────────────────────
    u_sand_mean: float = 0.60         # 基础开度
    tau_act_sand: float = 20.0        # s，执行机构时间常数（一阶跟踪）
    T_adj_sand: float = 28800.0       # s，操作员调整周期（8 小时/班）
    sigma_sand_adj: float = 0.08      # 每次调整幅度标准差
    sigma_u_sand_fb: float = 0.005    # 阀位反馈传感器噪声
    C_v_sand: float = 0.0050          # m³/(s·kPa^0.5)，沉砂水阀流量系数
    sigma_Q_sand_water: float = 0.0010 # m³/s，流量计噪声

    # ── 轴承温度（滑动轴承 1 & 2）────────────────────────────────────────
    # 热模型：ZOH 精确离散（始终数值稳定）
    #   T(t+dt) = T_ss + (T(t) - T_ss) * phi
    #   T_ss_b = T_amb + k_b_kw * P_mech[kW]
    #   phi_b = exp(-dt / tau_b)
    # 标定（@ P_mech_nom = 920 kW，T_amb = 25°C）：
    #   T_b1_ss = 55°C → k_b1_kw = (55-25)/920 = 0.0326 °C/kW
    #   T_b2_ss = 53°C → k_b2_kw = (53-25)/920 = 0.0304 °C/kW
    T_amb: float = 25.0               # °C，环境温度

    tau_b1: float = 1800.0            # s，轴承1热时间常数（30 min）
    k_b1_kw: float = 0.0326           # °C/kW，轴承1稳态温度系数
    T_b1_init: float = 55.0           # °C
    sigma_b1: float = 0.50            # °C

    tau_b2: float = 2100.0            # s，轴承2热时间常数（35 min）
    k_b2_kw: float = 0.0304           # °C/kW，轴承2稳态温度系数
    T_b2_init: float = 53.0           # °C
    sigma_b2: float = 0.50            # °C

    p_fault_bearing: float = 0.002    # 轴承温度传感器故障概率（考查报告标定）
    fault_val_bearing: float = -287.04 # °C，故障异常值

    # ── 主电机定子温度（A、B 相）─────────────────────────────────────────
    # ZOH 模型：T_ss_sA = T_coolant + k_sA_a2 * I_motor²[A²]
    # 标定（@ I_motor_nom = 96A，T_coolant = 30°C）：
    #   T_sA_ss = 80°C → k_sA_a2 = (80-30)/96² = 0.00543 °C/A²
    tau_sA: float = 900.0             # s，定子热时间常数（15 min）
    k_sA_a2: float = 0.00543          # °C/A²，定子稳态温度系数
    T_coolant: float = 30.0           # °C，冷却介质温度
    T_sA_init: float = 80.0           # °C
    sigma_sA: float = 0.50            # °C

    dT_AB: float = 1.5                # °C，B 相相对 A 相固定偏置
    sigma_AB: float = 0.30            # °C

    p_fault_stator: float = 0.002     # 定子温度传感器故障概率
    fault_val_stator: float = -287.04 # °C

    # ── 减速机温度（油池 & 出油口）───────────────────────────────────────
    # ZOH 模型：T_ss_red = T_amb + k_red_kw * P_loss[kW]
    #   P_loss = P_mech * (1-eta_red)/eta_red  [kW]
    # 标定（@ P_mech_nom = 920kW，η=0.96 → P_loss=38.3kW，T_amb=25°C）：
    #   T_red_ss = 55°C → k_red_kw = (55-25)/38.3 = 0.783 °C/kW
    tau_red: float = 2400.0           # s，减速机热时间常数（40 min）
    eta_red: float = 0.96             # 减速机效率
    k_red_kw: float = 0.783           # °C/kW，减速机稳态温度系数
    T_red_init: float = 55.0          # °C
    sigma_red: float = 0.30           # °C
    alpha_pipe: float = 0.92          # 出油口温度衰减系数
    sigma_red_out: float = 0.30       # °C

    # ── 旋流器溢流泵池───────────────────────────────────────────────────
    A_ov: float = 3.0                 # m²
    L_ov_init: float = 0.80           # m
    L_ov_low: float = 0.30            # m，泵启动下限液位
    Q_ov_pump_nom: float = 0.10       # m³/s，溢流泵额定流量
    sigma_L_ov: float = 0.020         # m

    I_ov_0: float = 5.0               # A，溢流泵空载电流
    k_ov_I: float = 80.0              # A/(m³/s)，流量-电流系数
    rho_ov: float = 1120.0            # kg/m³，溢流密度（~14.93%）
    sigma_I_ov: float = 0.30          # A


@dataclass
class FlotationConfig:
    """浮选段参数（两系列浮选槽 + 加药网络 + 化验时滞）。

    标定基准（来自考查报告）：
      - Q_TD=2100 g/t → 精矿TFe ≈ 67.43 %，尾矿 ≈ 12.86 %
      - Q_TD=1500 g/t → 精矿TFe ≈ 66.56 %，尾矿 ≈ 20.90 %
      - 稳态 pH ∈ [9.2, 10.1]

    动力学模型：
      eta_Fe(Q_TD) = eta_Fe0 + k_eta_Fe * (Q_TD - Q_TD_nom)   [Fe 回收率]
      R_Si(Q_TD, pH) = R_Si0 + k_R_Si * (Q_TD - Q_TD_nom) + k_R_Si_pH * (pH - pH_nom)
      TFe_conc = eta_Fe * g_ov / (eta_Fe*g_ov + (1-R_Si)*(1-g_ov))
      TFe_circuit(t+dt) = TFe_ss + (TFe_circuit(t) - TFe_ss) * exp(-dt/tau_flo)
    """

    # ── 塔磨 → 浮选段间时滞 ──────────────────────────────────────────────
    delay_steps_tm: int = 30          # 步，30 min @ 60 s/步

    # 名义塔磨溢流参数（RingBuffer 初始化用）
    m_ov_nom: float = 750.0           # t/h 每系列
    g_ov_nom: float = 0.4384          # TFe 品位（小数）
    rho_ov: float = 1120.0            # kg/m³（溢流密度 ~14.93%）

    # ── 浮选前浓缩机（NT-30，2台）───────────────────────────────────────
    tau_NT: float = 300.0             # s
    rho_NT_target: float = 0.39       # 底流浓度（质量分数）
    I_NT0: float = 10.0               # A，空载基础电流
    k_NT_I: float = 0.02              # A/(t/h 固体)
    sigma_NT_I: float = 0.3           # A
    sigma_NT_rho: float = 0.005       # 浓度测量噪声

    # ── 浮选动力学（标定参数）──────────────────────────────────────────
    # 中间点 Q_TD_nom = 1800 g/t（1500/2100 两点线性插值）
    eta_Fe0: float = 0.8180           # Fe 回收率（Q_TD = Q_TD_nom 时）
    k_eta_Fe: float = 1.84e-4         # Fe 回收率 Q_TD 偏导（/g/t）
    R_Si0: float = 0.6857             # Si 去除率（Q_TD = Q_TD_nom 时）
    k_R_Si: float = -4.97e-5          # Si 去除率 Q_TD 偏导（/g/t，负值）
    Q_TD_nom: float = 1800.0          # g/t，名义加药量
    Q_TD_min: float = 500.0           # g/t，加药量下限
    Q_TD_max: float = 3500.0          # g/t，加药量上限
    tau_flo: float = 800.0            # s，TFe 回路响应时间常数
    k_R_Si_pH: float = 0.02           # pH 对 Si 去除率的影响（/单位pH）

    # ── pH 动力学 ─────────────────────────────────────────────────────
    pH_nom: float = 9.6
    pH_init: float = 9.6
    tau_pH: float = 600.0             # s
    sigma_pH: float = 0.05
    k_pH_d2: float = 3.0              # d2（碳酸铁）对 pH 的抑制系数

    # ── 浮选槽液位（每系列 7 个槽）──────────────────────────────────────
    A_cell: float = 10.0              # m²，液槽截面积
    L_sp: float = 1.5                 # m，液位设定值
    L_init: float = 1.5               # m，初始液位
    Kp_lv: float = 0.4               # 液位阀比例增益
    tau_act_lv: float = 15.0          # s，阀门执行机构时间常数
    C_v_lv: float = 0.03              # m^2.5/s，阀门流量系数
    sigma_u_lv: float = 0.005         # 阀门噪声

    # ── 泡沫层高度 ──────────────────────────────────────────────────────
    h_froth_init: float = 0.30        # m
    k_gen_froth: float = 0.50         # 泡沫生成系数
    k_col_froth: float = 0.005        # /s，泡沫消散系数
    k_scrape: float = 0.002           # 刮泡系数
    omega_scraper: float = 2.0        # rpm，刮泡机转速
    p_fault_froth: float = 0.005      # 泡沫层传感器故障概率
    fault_val_froth: float = -21.0    # °C，故障异常值
    sigma_h_froth: float = 0.02       # m

    # ── 充气系统 ─────────────────────────────────────────────────────
    Q_air_nom: float = 0.010          # m³/s，每槽名义充气量
    sigma_Q_air: float = 0.001        # m³/s
    sigma_bv: float = 0.010           # 蝶阀位置噪声

    # ── 浮选机电机电流 ───────────────────────────────────────────────
    I_FXJ0: float = 5.0               # A，空载电流
    k_FXJ: float = 0.003              # A/(kg/m³ 矿浆密度偏差)
    sigma_I_FXJ: float = 0.30         # A

    # ── 加药泵（每系列 5 种：粗选TD、精选TD、K6粗选、NaOH、CaO）──────
    f_td_rough_nom: float = 30.0      # Hz，粗选 TD 泵频率
    f_td_clean_nom: float = 20.0      # Hz，精选 TD 泵频率
    f_k6_rough_nom: float = 25.0      # Hz，K6 粗选泵
    f_naoh_nom: float = 15.0          # Hz，NaOH 泵
    f_cao_nom: float = 20.0           # Hz，CaO 泵
    phi_drug: float = 0.99            # AR(1) 系数
    sigma_drug_f: float = 0.30        # Hz，泵频率噪声
    I_drug0: float = 2.0              # A，泵基础电流
    k_drug_If: float = 0.08           # A/Hz
    sigma_drug_I: float = 0.10        # A

    # ── 开环 PRBS 加药 ────────────────────────────────────────────────
    Q_TD_prbs_low: float = 1200.0     # g/t，PRBS 低值
    Q_TD_prbs_high: float = 2400.0    # g/t，PRBS 高值
    p_prbs_switch: float = 0.005      # 每步切换概率（期望保持 200 步/状态）

    # ── 搅拌槽温度（每系列 3 个：TD/K6/CaO 搅拌槽）────────────────────
    T_tk_sp: float = 50.0             # °C，设定值
    T_tk_init: float = 50.0           # °C
    tau_tk: float = 600.0             # s，热时间常数
    u_TV_nom: float = 0.20            # 蒸汽阀名义开度
    Kp_TV: float = 0.02               # 温度 PID 比例增益
    tau_TV: float = 30.0              # s，蒸汽阀执行机构
    sigma_T_tk: float = 0.30          # °C
    sigma_TV: float = 0.005           # 阀门噪声

    # ── 泵池（每系列 3 个）─────────────────────────────────────────────
    A_pool_flo: float = 5.0           # m²，泵池截面积
    L_pool_flo_sp: float = 1.0        # m，液位设定值
    L_pool_flo_init: float = 1.0      # m
    k_pump_flo: float = 0.0016        # m³/(s·Hz·m^0.5)，泵特性系数
    f_pump_flo_nom: float = 40.0      # Hz，泵额定频率
    f_pump_flo_min: float = 20.0      # Hz
    f_pump_flo_max: float = 50.0      # Hz
    Kp_pool_flo: float = 5.0          # Hz/m，液位→频率增益
    sigma_f_pump_flo: float = 0.20    # Hz
    I_pump_flo0: float = 10.0         # A，基础电流
    k_pump_flo_I: float = 0.015       # A/Hz²
    sigma_I_pool: float = 0.30        # A
    sigma_L_pool_flo: float = 0.020   # m

    # ── 鼓风机 ─────────────────────────────────────────────────────────
    P_blower_nom: float = 30.0        # kPa，名义出口压力
    sigma_blower: float = 0.50        # kPa
    phi_blower: float = 0.99

    # ── 变压器有功功率 ───────────────────────────────────────────────
    sigma_P_AH: float = 5.0           # kW

    # ── 入矿流量传感器 ───────────────────────────────────────────────
    sigma_Q_ft: float = 0.005         # m³/s

    # ── K6 贮药箱液位 ────────────────────────────────────────────────
    L_k6_init: float = 1.5            # m
    sigma_L_k6: float = 0.02          # m
    phi_k6: float = 0.9995            # AR(1) 慢漂移系数

    # ── 化验时滞（LabAssayer）────────────────────────────────────────
    tau_lab_min: int = 120            # 步，化验最小延迟（120 min）
    tau_lab_max: int = 240            # 步，化验最大延迟（240 min）
    lab_buf_capacity: int = 300       # RingBuffer 容量（步）
    sigma_lab: float = 0.0012         # TFe 化验噪声（小数单位，≈0.12%）
    delta_12: float = 0.002           # 第2系列品位偏置（+0.2%）
    assay_interval_min: int = 240     # 步，化验最小间隔（4 h）
    assay_interval_max: int = 480     # 步，化验最大间隔（8 h）
