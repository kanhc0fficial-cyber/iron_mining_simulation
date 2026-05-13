# 程序公式与设计文档差异核对报告

本报告把 `program_formula_report/01~05` 中从程序反推的公式，与设计侧文档中的公式/伪代码进行核对。表述仅记录“设计侧写法”和“程序侧写法”的差异，不作“谁对谁错”的定性。

## 核对来源

设计侧读取文件：

- `design.md`
- `plan.md`
- `README.md`
- `REVIEW_ISSUES.md`
- `预演.md`
- `选矿仿真系统设计文档.md`

程序侧读取文件：

- `sim/config.py`
- `sim/simulator.py`
- `sim/rng.py`
- `sim/layers/*.py`
- `sim/utils/*.py`
- `scripts/run_simulation.py`
- `scripts/calibrate.py`

## 总览

主要差异集中在以下几类：

- 浮选段：设计侧是槽级 `C_Fe/C_Si` 浓度 ODE、非单调 `k_Si`、JX 出口化验时滞；程序侧是两系列级 `eta_Fe/R_Si` 代数稳态 TFe 加一阶响应。
- 时滞：设计侧多处写“先读取延迟值再 push 当前值”或给出范围；程序侧多处是固定步数，且塔磨/浮选段间缓冲为“先 push 当前值再 peek 延迟值”。
- PID/阀门：若干设计公式含 PID 积分项、阀门分段阈值或 `sqrt(2gL)`；程序侧多处使用比例控制、一阶执行机构或简化阀门流量。
- 热模型：设计侧多写成物理 ODE；程序侧在塔磨温度中多用稳态温度系数 + ZOH。
- 部分变量：设计侧包含若干输出/状态关系，如药剂泵流量、搅拌槽电流、ZJB 流量故障、槽级浓度等；程序侧未按这些关系显式仿真。

## 公共模型

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| 随机数派生 | `seed=int(rng.integers(2**31))`，按子系统独立 RNG | `RNGFactory.get(name)` 首次请求时 `master_rng.integers(0,2**31)` | 形式基本一致；程序增加同名缓存复用。 |
| 传感器漂移 | `b_new=b+N(0,sigma_b^2)` | `b_new=b+N(0,sigma_b)`，NumPy 参数为标准差 | 记号层面一个写方差、一个以 API 标准差表达。 |
| 热模型 | 公共工具为前向欧拉 `tau*dT/dt=Q-k(T-Tamb)` | `FirstOrderThermal` 同式前向欧拉；塔磨另用 ZOH | 公共工具一致；塔磨具体设备温度离散形式不同，见塔磨段。 |

## 扰动与开环激励

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| d1/d2 相关扰动 | OU/AR(1)，`Cov(eta1,eta2)=-0.6*sigma1*sigma2` | Cholesky 矩阵生成相关噪声，`cov_d1d2=-0.6` | 数学关系一致。 |
| 开环 d1 扰动倍率 | `选矿仿真系统设计文档.md` 写扩大至 `3~5` 倍；`REVIEW_ISSUES.md` 讨论并验证 10 倍 | `d1_sigma_open_factor=10.0` | 设计侧不同文件给出的倍率不完全相同；程序采用 10 倍。 |
| 开环加药 | 设计侧写 PRBS/持续激励，可由最大长度序列或切换过程表示 | 程序按每步概率 `p_prbs_switch` 切换高/低 `Q_TD` 状态 | 都是二值激励；生成机制不同。 |

## 球磨输入

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| d80 与可磨性 | 设计侧主要写球磨 d80 为 AR(1)，并说明 d3 为可磨性扰动 | 程序显式 `d80_raw=d80_ball_mean/_x_d3 + xi_d80` | 程序把 d3 直接作为除数进入 d80；设计侧公式中未在球磨 d80 处明确写出该除法。 |
| `f_{-25um}` | 设计侧 `f=fmax/(1+exp(-k*(d80_ref-d80)))+noise` | 程序 `f25_max*sigmoid(k_f25*(d80_ref-d80)+bias_f25)+noise` | 程序额外有 `bias_f25`，用于让参考点穿过 `f25_ref`。 |
| 三线相关 | 设计侧写三条线相关，相关系数约 0.7，共同扰动驱动 | 程序共享 `xi_m`，并叠加 `sigma*sqrt(1-rho_lines)` 的独立噪声 | 总体思路一致；程序只对质量流量显式做三线独立叠加。 |

## 磁选段

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| 弱磁精矿品位 | `g_wmag=d1*k_wm_Fe/(1+k_wm_Si*(1-d1))` | 同式并 `clip(0,1)` | 公式一致，程序增加限幅。 |
| 弱磁尾矿品位 | 设计公式写作 `(d1*m_ball - g_wmag*beta_wm*m_ball)/(m_ball*(1-beta_wm))` | 程序先 `m_wm_conc=beta_wm*d1*m_ball/g_wmag`，再 `g_wm_tail=(d1*m_ball-beta_wm*d1*m_ball)/m_wm_tail` | 两侧对 `beta_wm` 在尾矿质量平衡中的放置不同；程序把 `beta_wm` 作为铁回收率使用。 |
| 浓缩机底流浓度 | 设计侧写 `rho_conc_out=rho_conc_target+noise` | 程序仅用固定 `rho_conc_kg_m3` 换算流量，没有输出动态 `rho_conc_out` | 程序没有显式仿真该浓度状态。 |
| 强磁回收率 | 设计侧是磁力-曳力差进入 sigmoid：`sigmoid(lambda*(magnetic_force - drag_force))` | 程序为归一化力竞争：`force_balance=(B/B_nom)^2/((v/v_nom)*(dp/dp_nom)^2)`，再 `sigmoid(lambda_s*log(force_balance)+bias_s)` | 非线性形式不同；程序使用无量纲比值和对数。 |
| 粒径代理 | 设计侧 `dp≈dp_ref*(1-f25)^0.5` | 程序 `dp=dp_ref*sqrt(max(1-f25,0.01))` | 程序增加下限保护。 |
| 尾矿阀 PID 误差 | 设计侧 `e=L_setpoint-L_measured` | 程序调用 `PID.step(setpoint=L_meas, measurement=L_setpoint)`，即 `e=L_meas-L_setpoint` | 误差符号写法不同。 |
| 二号尾矿阀开度 | 设计侧 `u_v2=clip(u_v-0.5,0,1)*1[u_v>0.5]` | 程序 `u_v2=clip(u_v-1.0,0,1)` | 第二阀开启阈值不同：设计侧 0.5，程序侧 1.0。 |
| 尾矿阀流量 | 设计侧 `Q_tail=C_v*(u1+u2)*sqrt(max(L,0)*2g)` | 程序 `Q_tail=C_v_mag*(u1+u2)*sqrt(max(L,0))` | 程序未显式包含 `2g` 项。 |
| 冲矿水压 | 设计侧 `P_flush=d4-k_pipe*Q_flush^2+noise` | 程序 `P_flush=d4-k_pipe*Q_flush^2*1e-3+noise` | 程序加入 `1e-3` 单位换算因子。 |
| 磁选电机电流 | `I0+k_mf*m_in+k_mr*f_ring+k_mm*beta_strong*m_in+noise` | 同式 | 一致。 |

## 塔磨段

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| 磁选到塔磨时滞 | 设计侧范围 `15~30 min`，工程文档还写 `step` 中先 `peek` 再 `push` | 程序固定 `delay_steps=20`，并在 `step` 中先 `push` 当前 `_x_m_mag/_x_g_mag` 再 `peek(delay_steps)` | 程序固定为 20 步；缓冲读写顺序与工程文档描述不同。 |
| 塔磨到浮选时滞 | 设计侧范围 `30~60 min`，工程文档写容量可覆盖最长 60 min | 程序固定 `delay_steps_tm=30`，同样先 `push` 再 `peek` | 程序固定为 30 步；读写顺序与工程文档描述不同。 |
| 内部磨矿时滞 | 设计侧 `5~15 min` 或容量 30 留余量 | 程序 `tau_mill=8` 步 | 程序使用固定 8 步。 |
| 泵频控制 | 设计侧 `f_pump=f_prev+manual+k_fb*(L_set-L_DCS)+eta` | 程序 `f_target=f_nom+k_fb*(L_pool-L_setpoint)`，再 AR(1) 平滑 | 程序使用真值液位和目标频率平滑；设计侧写 DCS 液位与增量式/手动项。 |
| 泵池补水 | 设计侧 `Q=C_v*u*sqrt(d4)+noise` | 程序 `Q=C_v*u*sqrt(d4*1000)`，DCS 输出用无噪声 `Q_pool_water` | 程序使用 kPa 换算；该输出没有在写 bus 时使用噪声版本。 |
| 泵扬程 | 设计侧 `H=a0-a1*(f/fnom)^2*Q^2` | 程序 `H=max(a0-a1*Q^2,0)` | 程序扬程没有频率平方项。 |
| 沉砂水阀设定 | 设计侧每班多次阶跃，`Delta u` 可用均匀分布 | 程序每 `T_adj_sand=28800s` 从 `u_sand_mean+N(0,sigma)` 生成一次 | 调整频率和分布不同。 |
| 机械功率密度项 | 设计侧 `+k_mrho*rho_slurry,mill` | 程序 `+k_mrho*(rho_mill-rho_slurry_nom)` | 程序使用相对名义密度的偏差项。 |
| 轴承温度 | 设计侧 ODE 含 `P_mech*omega^2*(1+k_wear*t_aging)` 和散热项 | 程序 `T_ss=T_amb+k_b_kw*P_mech`，再 ZOH | 程序没有显式螺旋转速、磨损老化项和散热系数项。 |
| 定子温度 | 设计侧 `tau*dT/dt=k*I^2*R_stator-h(T-T_coolant)+w` | 程序 `T_ss=T_coolant+k_sA_a2*I_motor^2`，再 ZOH | 程序把电阻/散热合并为稳态系数。 |
| 减速机温度 | 设计侧 ODE `k_red*P_mech*(1-eta)/eta - h_red*(T-Tamb)` | 程序 `P_loss=P_mech*(1-eta)/eta`，`T_ss=T_amb+k_red_kw*P_loss`，再 ZOH | 程序以稳态温度系数表达。 |
| 溢流泵流量 | 设计侧 `Q_ov_pump=Qbar*1[L>Llow]+epsilon` | 程序 `Q_ov_pump=Q_ov_pump_nom if L>Llow else 0` | 程序未给泵流量本身加噪声；电流和液位 DCS 后续加噪。 |

## 浮选段

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| 品位建模层级 | 设计侧以每个浮选槽状态 `[L,h,C_Fe,C_Si]` 和槽级浓度 ODE 为核心 | 程序不维护槽级 `C_Fe/C_Si`；用两系列 `TFe_circuit` 一阶响应表示最终品位 | 建模层级不同：槽级矿物浓度 vs 系列级 TFe。 |
| 浮选速率 | 设计侧核心为非单调 `k_Si(Q_TD,pH,Q_air,C_Ca)` | 程序用 `eta_Fe=eta0+k_eta*dQ`、`R_Si=R0+k_R*dQ+k_pH*dpH`，再算 `TFe_ss` | 核心品位公式不同；程序没有 `k_Si` 非单调式。 |
| 浮选拓扑 | 设计侧有 CX/JX/SX 拓扑、精选/扫选回流和 Gauss-Seidel 顺序 | 程序只在液位水力上做 7 槽串联：槽 0 入流为总流量，后续槽入流为前槽底流 | 程序没有按设计拓扑更新矿物浓度与回流。 |
| 浓缩机电流 | 设计侧 `I_NT=I0+k*m_solid*rho_underflow^0.5+noise` | 程序 `I_NT=I0+k_NT_I*m_solid+noise` | 程序没有 `rho_underflow^0.5` 因子。 |
| 浮选槽液位 ODE | 设计侧 `A*dL/dt=Q_in-Q_out_pulp-Q_out_froth` | 程序 `dL/dt=(Q_in_cell-Q_out_pulp)/A_cell` | 程序没有显式泡沫流出项。 |
| 液位阀控制 | 设计侧 PI：`Kp*(Lsp-L)+Ki*integral` | 程序 `u_lv_sp=u_lv_nom+Kp_lv*(L_sp-L_cells)`，再执行机构一阶跟踪 | 程序没有积分项，并有名义阀位偏置。 |
| 底流阀流量 | 设计侧 `C_v*u*sqrt(max(L-L_ref,0))` | 程序 `C_v_lv*u*sqrt(max(L,0))` | 程序没有 `L_ref`。 |
| 泡沫层 | 设计侧 `dh/dt=k_gen*Q_air*C_Si-k_col*h-k_scrape*omega` | 程序先 `C_Si≈clip(1-TFe_circuit)`，再 `h_ss=k_gen*Q_air*C_Si/(k_col+k_scrape*omega)`，ZOH 到 `h_ss` | 程序用稳态近似和 TFe 代理 Si；没有显式 `C_Si` 状态。 |
| 充气量 | 设计侧 `Q_air=C_d*A_orif*u_bv*sqrt(2(P_blower-P_slot)/rho_air)` | 程序 `Q_air=Q_air_sp+noise`，`Q_air_sp` 慢变 AR(1)；`u_bv` 单独慢漂移 | 程序中蝶阀开度和鼓风机压力没有参与 `Q_air` 计算。 |
| 鼓风机压力 | 设计侧 `P_blower=a0+a1*omega^2-a2*Q_total_air^2+noise` | 程序 `P_blower=P_nom+phi*(P-P_nom)+noise` | 程序采用 AR(1) 压力扰动。 |
| 加药泵流量 | 设计侧有 `Q_drug=k_screw*f_drug+noise` | 程序没有输出或使用显式 `Q_drug`；泵频按 `Q_TD/Q_TD_nom` 设目标 | 程序直接用频率和 `Q_TD` 代理加药。 |
| 加药泵电流 | 设计侧 `I=I0+k_If*f+k_IQ*rho_drug*Q_drug+noise` | 程序 `I=I_drug0+k_drug_If*f_drug+noise` | 程序没有药剂密度与流量负载项。 |
| pH | 设计侧 `[OH-]` ODE，`pH=14+log10([OH-])+noise`，`k_buff=k0+kc*d2` | 程序 `pH_ss=pH_nom+0.5*(f_naoh/f_nom-1)-k_pH_d2*(d2-0.018)`，再一阶响应 | pH 数学形式不同：化学浓度/对数模型 vs 线性稳态目标。 |
| 搅拌槽温度 | 设计侧蒸汽加热 ODE：`tau*dT/dt=k_steam*u_TV*(Tsteam-T)-h_loss*(T-Tamb)` | 程序温度直接 ZOH 到 `T_tk_sp` 并加噪；蒸汽阀按温度误差比例设定 | 程序没有显式蒸汽热量项。 |
| 搅拌槽电流 | 设计侧 `I_JBC=I0+k*mu_drug+noise`、`mu=mu0*exp(Ea/(RT))` | 程序未生成对应 JBC 搅拌电流关系 | 程序侧未显式仿真该组关系。 |
| K6 药箱液位 | 设计侧 `dL_K6/dt=Q_fill-Q_pump` | 程序 `L_k6=L_init+phi*(L_k6-L_init)+noise` | 程序使用 AR(1) 近似。 |
| 泵池拓扑 | 设计侧给出各 LT 泵池与 JX/SX/CX 流向关系 | 程序每系列 3 个泵池，共用 `Q_total_s/N_POOLS` 入流 | 程序没有按设计侧各泵池流向逐一建模。 |
| ZJB 流量故障 | 设计侧 `Q_ZJB_DCS` 可按概率变为 `-12.5` | 程序未见对应负值故障流量输出 | 程序侧未显式仿真该故障关系。 |
| 浮选机电流 | 设计侧 `I_FXJ=I0+k*rho_slurry_i+noise` | 程序 `rho_slurry_est=rho_ov+(m_ov_del-m_ov_nom)*0.05`，`I=I0+k*(rho_est-rho_ov)+noise` | 程序用上游流量估算密度偏差，而不是槽级矿浆密度。 |
| 目标 TFe | 设计侧 `TFe(t+tau_lab)=C_Fe_JX/(C_Fe_JX+C_Si_JX)*100%+noise` | 程序 `y_fx_xin_s=TFe_circuit_s+delta_s+noise`，在采样时刻写入，其他步为 `NaN` | 程序没有用 JX 出口浓度，也没有乘 `100%`；`tau_lab` 被抽样但未用于延迟写入。 |
| 两系列偏置 | 设计侧 `TFe_xin2=TFe_xin1+delta_12+epsilon_cross` | 程序每系列各自 `TFe_circuit[s]+delta_s+lab_noise`，`delta_s=[0,delta_12]` | 程序不是直接由 `xin1` 推出 `xin2`。 |

## 输出与变量覆盖

| 项目 | 设计侧 | 程序侧 | 差异记录 |
|---|---|---|---|
| 磁选 DCS 数量 | 12 个 | 12 个 | 数量一致。 |
| 塔磨 DCS 数量 | 18 个 | 18 个 | 数量一致。 |
| 浮选 DCS 结构 | 设计侧约 170 个，含槽级、药剂、泵池、状态、电力等 | 程序生成大量槽级、药剂、泵池、电力变量，但采用简化/代理公式 | 输出数量层面接近；若干变量的生成机理与设计侧不同。 |
| 隐藏量输出 | 设计侧作为内部物理状态 | 程序 `_x_` 隐藏量用于模块传递，最终 writer 过滤 | 架构一致。 |

## 可直接用于逐项追踪的程序侧变量

以下差异项在程序里有明确变量名，后续若要做逐项实验，可优先跟踪：

- 磁选：`beta_wm`、`g_wm_tail`、`beta_strong`、`u_v1/u_v2`、`Q_tail`、`P_flush`。
- 塔磨：`m_mag_delayed/g_mag_delayed`、`f_pump`、`Q_pool_water`、`H_pump`、`P_mech`、`T_b1/T_b2/T_sA/T_red`、`_x_m_ov`。
- 浮选：`_Q_TD`、`_f_drug`、`_pH`、`_TFe_circuit`、`_L_cells`、`_h_froth`、`_Q_air_sp`、`_P_blower`、`_L_k6`、`y_fx_xin1/2`。

## 结语

本报告只记录公式层面的不同表达、不同简化层级、不同变量连接方式，以及部分设计侧有而程序侧未显式仿真的关系，不对差异作价值判断或归因。
