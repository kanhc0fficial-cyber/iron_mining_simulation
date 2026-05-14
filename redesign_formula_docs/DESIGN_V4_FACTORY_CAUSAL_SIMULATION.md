# 选矿仿真系统 v4 工厂因果仿真设计文档

版本：v4.0-factory-causal-redesign  
日期：2026-05-14  
取代关系：本文是对 `DESIGN_V3_CAUSAL_SOFT_SENSOR.md` 的重审和重新设计。v3 可作为过渡记录，后续实现、公式、特征准入和验收以本文为准。

## 0. 根本目的

本仿真系统的根本目的不是让模型预测分数好看，而是尽量模拟工厂中真实存在的因果关系，让生成数据可用于：

```text
软测量预测
因果发现
DAG/时序因果图构建
因果强度估计
因果约束软测量建模
干预和反事实分析
```

因此，任何变量、公式和代码必须优先满足：

```text
真实因果路径存在
因果方向清楚
滞后结构合理
DCS 可观测链可信
lab 可用时间明确
隐藏变量不泄漏
最终标签不反写
```

## 1. 对旧设计的重新判定

旧设计的主要问题不是“参数没调好”，而是“因果观测链没有按研究目标设计”。旧设计中即使存在物料平衡和流程顺序，也不能自动说明它适合因果软测量。

### 1.1 必须废弃的旧模式

以下模式全部判定为不合格：

```text
模式 A: 关键质量信息只存在于 lab_* 或 _x_* 中
例如混磁精矿 TFe、塔磨溢流 TFe/F325、解离度、浮选给矿组分只在隐藏量中，
DCS 只输出流量、液位、电流的弱噪声响应。

模式 B: 操作量围绕名义值 AR 漂移
例如 pH、NaOH/CaO/TD/DF_K6 泵频、气量设定、液位阀位、泵频只做名义值附近随机游走。

模式 C: DCS 只作为结果副产品，权重弱且噪声大
例如泡沫高度、电机电流、泵电流理论上应承载矿质信息，
但正常信号太窄，故障值过强，导致特征不可用。

模式 D: 为避免泄漏而切断隐藏矿质到 DCS 的路径
正确做法不是切断，而是通过设备负荷、控制策略、传感器响应让隐藏状态投影到 DCS。

模式 E: 最终品位由 hidden stream 直接决定，DCS 与该路径只弱连接
这会生成适合 lab 辅助建模的数据，但不适合纯 DCS 在线软测量和因果发现。
```

### 1.2 新设计的核心原则

所有工厂实际因果关系必须优先建成以下结构：

```text
矿石性质/设备状态/外生扰动
  -> 物料状态
  -> 设备负荷与控制需求
  -> 控制设定
  -> 执行器实际值
  -> 工艺响应
  -> DCS 传感器
  -> 过程化验
  -> 最终标签
```

禁止：

```text
最终标签 -> DCS
当前最终浮选 lab -> 当前特征
未来 lab -> 当前特征
_x_* hidden true value -> 模型特征
DCS = a*y + noise
DCS = a*final_conc_tfe + noise
```

允许并且必须加强：

```text
_x_flo_feed_tfe/r_carb/r_sil/Liberation/WI/clay
  -> 药剂需求、pH 缓冲、Ca2+、泡沫负荷、矿浆黏度、塔磨负荷
  -> DCS
```

## 2. 全局变量分类

### 2.1 外生变量

外生变量不由系统内部结果反推：

```text
z_ore = {
  G_base,                 # 入口 TFe, 0-1
  r_mag, r_hem, r_carb, r_sil,
  WI,                     # 难磨性/可磨性代理
  clay,                   # 黏土/泥化代理
  carbonate_buffer,       # 碳酸盐缓冲能力
  silicate_buffer,        # 硅酸盐缓冲能力
  ore_density_index,      # 固体密度变化代理
  liberation_potential    # 同等磨矿能量下可解离性
}

z_utility = {
  water_pressure,
  grid_voltage,
  ambient_temp,
  reagent_supply_pressure,
  air_supply_health
}

z_equipment = {
  mag_unit_health[],
  tm_unit_health[],
  cyclone_open_count,
  flo_cell_health[],
  pump_health[],
  sensor_fault_state[]
}

z_intervention = {
  PRBS_TD, PRBS_NaOH, PRBS_CaO, PRBS_air, PRBS_water, PRBS_feed_rate
}
```

外生慢变：

```text
z_ore(t+1)=z_ore(t)+(dt/tau_ore)*(z_target-z_ore(t))+L_ore*eps(t)
[r_mag,r_hem,r_carb,r_sil]=normalize_clip(...)
```

入口矿质必须作为动态时间序列生成，不能在整段仿真中固定为常数。对 `WI`、`clay`、`r_carb` 等慢变矿脉属性，推荐使用带均值回归的 OU 过程，并对三条入口线分别生成：

```text
dWI_i = theta_WI*(WI_target_i-WI_i)*dt + sigma_WI*dW_WI_i
dclay_i = theta_clay*(clay_target_i-clay_i)*dt + sigma_clay*dW_clay_i
dr_carb_i = theta_carb*(r_carb_target_i-r_carb_i)*dt + sigma_carb*dW_carb_i

WI_i(t+dt)=clip(WI_i(t)+dWI_i,WI_min,WI_max)
clay_i(t+dt)=clip(clay_i(t)+dclay_i,clay_min,clay_max)
r_carb_i(t+dt)=clip(r_carb_i(t)+dr_carb_i,r_carb_min,r_carb_max)
[r_mag_i,r_hem_i,r_carb_i,r_sil_i]=normalize_clip(...)
```

### 2.2 隐藏物料状态

所有流程物料必须使用 Stream：

```text
Stream = {
  M_solid, M_water, C,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  FeO_proxy,
  TFe,
  F200, F325, f25, d80,
  Liberation_fe, Liberation_gangue,
  WI, clay, T_slurry,
  rho_solid_mix,
  mu_slurry,
  buffer_capacity,
  hydrophobic_potential
}
```

组分品位：

```text
Fe_total = Fe_mag+Fe_hem+Fe_carb+Fe_sil
M_solid = Fe_total+Gangue
TFe = Fe_total/max(M_solid,eps)
```

混合固体密度必须按矿物组分计算，不能使用固定 `rho_solid`：

```text
rho_solid_mix =
  M_solid / max(
    Fe_mag/rho_fe_mag
    + Fe_hem/rho_fe_hem
    + Fe_carb/rho_fe_carb
    + Fe_sil/rho_fe_sil
    + Gangue/rho_gangue,
    eps)
```

矿浆密度：

```text
M_wet = M_solid/max(C,eps)
M_water = M_wet-M_solid
V_slurry = M_solid/rho_solid_mix + M_water/rho_water
rho_slurry = M_wet/max(V_slurry,eps)
```

黏度必须显式承载 clay 和微细粒：

```text
mu_slurry = mu_water
  * exp(k_C_mu*C/(1-C+eps))
  * (1+k_clay_mu*clay)
  * (1+k_f25_mu*f25)
  * (1+k_sil_mu*r_sil)
  * exp(k_temp_mu*(T_ref-T_slurry))
```

任意泵池、混合槽、浮选槽或返回物流的 Stream 混合，所有非守恒属性必须按对应质量或热容加权更新，禁止直接沿用某一路输入：

```text
F325_mixed =
  (M_solid_in1*F325_in1+M_solid_in2*F325_in2)
  / max(M_solid_in1+M_solid_in2,eps)

Liberation_fe_mixed =
  (M_solid_in1*Liberation_fe_in1+M_solid_in2*Liberation_fe_in2)
  / max(M_solid_in1+M_solid_in2,eps)

Liberation_gangue_mixed =
  (M_solid_in1*Liberation_gangue_in1+M_solid_in2*Liberation_gangue_in2)
  / max(M_solid_in1+M_solid_in2,eps)

T_slurry_mixed =
  (M_wet_in1*Cp_slurry_in1*T_slurry_in1+M_wet_in2*Cp_slurry_in2*T_slurry_in2)
  / max(M_wet_in1*Cp_slurry_in1+M_wet_in2*Cp_slurry_in2,eps)
```

缓冲能力：

```text
buffer_capacity =
  b0
  + b_carb*r_carb
  + b_sil*r_sil
  + b_clay*clay
  + b_C*C
  + b_flow*M_solid
```

脉石疏水潜势：

```text
hydrophobic_potential =
  h0
  + h_lib*Liberation_gangue
  + h_sil*r_sil
  + h_carb*r_carb
  + h_fine*f25
  - h_k6*dose_DF_K6
  + h_ca*Ca2_effect
```

### 2.3 DCS、lab、标签

```text
DCS = 在线传感器或控制系统可见值，可作 DCS-only 特征。
lab_* = 人工/过程化验，必须有 sample_time 和 report_time。
y_fx_xin1/y_fx_xin2 = 目标标签，只能作监督目标。
_x_* = 隐藏真值，禁止作训练特征。
```

## 3. 基础动态函数

```text
clip(x,a,b)=min(max(x,a),b)
sigmoid(x)=1/(1+exp(-x))
ZOH(x,x_ss,tau)=x_ss+(x-x_ss)*exp(-dt/max(tau,eps))
sat_act(u,u_min,u_max,tau)=ZOH(u_actual,clip(u,u_min,u_max),tau)
delay(x,L)=ring_buffer_read(x,t-L)
```

所有控制器统一形式：

```text
u_sp = clip(
  u_nom
  + Kp*error
  + Ki*integral(error)
  + Kff*feedforward_state
  + operator_trim
  + intervention,
  u_min,u_max)
u_actual = sat_act(u_sp,u_min,u_max,tau_act)
```

禁止把 `operator_trim` 或噪声当成主控制律。

DCS 传感器不得在实现中写成未展开的 `sensor(x,...)` 占位。所有 DCS 必须使用以下显式测量方程，并在变量公式中明确写出 `x_phys` 的来源：

```text
x_lpf(t) = x_phys(t) + (x_lpf(t-dt)-x_phys(t))*exp(-dt/max(tau_sensor,eps))
x_meas_raw(t) = x_lpf(t) + bias_sensor + eps_sensor(t)
eps_sensor(t) ~ N(0,sigma_sensor^2)

if event_sensor_fault(t)=1:
    x_dcs(t)=fault_value(t)
else:
    x_dcs(t)=clip(x_meas_raw(t),x_dcs_min,x_dcs_max)
```

也就是说，`x_phys` 必须是由物料、控制器、执行器、设备负荷或公用系统计算出来的物理量，不能是最终精矿品位、当前浮选最终化验或隐藏最终品位的函数。

## 4. 入口边界因果模型

三路线入口：

```text
availability_i in {0,1}, i=1,2,3
M_wet_i = availability_i*clip(M_nom_i+xi_common+xi_i,M_min_i,M_max_i)
C_i = clip(C_nom+k_load_C*(M_wet_i-M_nom_i)+k_clay_C*clay_i+xi_C_i,C_min,C_max)
M_solid_i = M_wet_i*C_i
M_water_i = M_wet_i-M_solid_i
TFe_i = clip(G_base_i+k_mag_G*(r_mag_i-r_mag_ref)-k_clay_G*clay_i+xi_G_i,G_min,G_max)
```

粒度：

```text
logit(F200_i)=logit(F200_nom)
  - k_WI_size*(WI_i-WI_ref)
  - k_load_size*(M_wet_i-M_nom_i)
  - k_clay_size*clay_i
  + k_liberation_potential*liberation_potential_i
  + eta_size_i
F200_i=sigmoid(logit(F200_i))
F325_i=F(45e-6;d80_i,n_rr)
f25_i=F(25e-6;d80_i,n_rr)
```

组分：

```text
Fe_total_i=M_solid_i*TFe_i
Fe_mag_i=Fe_total_i*r_mag_i
Fe_hem_i=Fe_total_i*r_hem_i
Fe_carb_i=Fe_total_i*r_carb_i
Fe_sil_i=Fe_total_i*r_sil_i
Gangue_i=M_solid_i-Fe_total_i
FeO_proxy_i=k_feo_mag*Fe_mag_i+k_feo_carb*Fe_carb_i+k_feo_hem*Fe_hem_i+k_feo_sil*Fe_sil_i

rho_solid_mix_i =
  M_solid_i / max(
    Fe_mag_i/rho_fe_mag
    + Fe_hem_i/rho_fe_hem
    + Fe_carb_i/rho_fe_carb
    + Fe_sil_i/rho_fe_sil
    + Gangue_i/rho_gangue,
    eps)
```

入口初始解离度是解离状态的出生地，必须进入 Stream 并随混合物流传递：

```text
Liberation_fe_i = clip(
  L0_fe
  - k_L_wi*(WI_i-WI_ref)
  - k_L_size*(1-F200_i)
  - k_L_clay*clay_i,
  0.1,0.8)

Liberation_gangue_i = clip(
  L0_gangue
  - k_Lg_wi*(WI_i-WI_ref)
  - k_Lg_size*(1-F200_i),
  0.1,0.8)

T_slurry_i = T_amb+k_ore_temp*(T_ore_feed-T_amb)+k_water_temp*(T_process_water-T_amb)
```

三条入口线汇合必须严格执行干矿质量加权，混合后的 Stream 才能进入后续磨矿和磁选。禁止对 `WI/clay/r_carb/F325/Liberation` 做简单平均：

```text
M_solid_mixed = M_wet_1*C_1 + M_wet_2*C_2 + M_wet_3*C_3
M_water_mixed = M_water_1 + M_water_2 + M_water_3
M_wet_mixed = M_solid_mixed + M_water_mixed
C_mixed = M_solid_mixed/max(M_wet_mixed,eps)

_x_d3_WI_mixed =
  (M_solid_1*WI_1+M_solid_2*WI_2+M_solid_3*WI_3)
  / max(M_solid_mixed,eps)
_x_clay_mixed =
  (M_solid_1*clay_1+M_solid_2*clay_2+M_solid_3*clay_3)
  / max(M_solid_mixed,eps)
_x_r_carb_mixed =
  (M_solid_1*r_carb_1+M_solid_2*r_carb_2+M_solid_3*r_carb_3)
  / max(M_solid_mixed,eps)

TFe_mixed =
  (M_solid_1*TFe_1+M_solid_2*TFe_2+M_solid_3*TFe_3)
  / max(M_solid_mixed,eps)
rho_solid_mix_mixed =
  M_solid_mixed / max(
    sum_i(Fe_mag_i/rho_fe_mag)
    + sum_i(Fe_hem_i/rho_fe_hem)
    + sum_i(Fe_carb_i/rho_fe_carb)
    + sum_i(Fe_sil_i/rho_fe_sil)
    + sum_i(Gangue_i/rho_gangue),
    eps)
F200_mixed = sum_i(M_solid_i*F200_i)/max(M_solid_mixed,eps)
F325_mixed = sum_i(M_solid_i*F325_i)/max(M_solid_mixed,eps)
f25_mixed = sum_i(M_solid_i*f25_i)/max(M_solid_mixed,eps)
Liberation_fe_mixed = sum_i(M_solid_i*Liberation_fe_i)/max(M_solid_mixed,eps)
Liberation_gangue_mixed = sum_i(M_solid_i*Liberation_gangue_i)/max(M_solid_mixed,eps)
T_slurry_mixed = sum_i(M_wet_i*Cp_slurry_i*T_slurry_i)/max(sum_i(M_wet_i*Cp_slurry_i),eps)
```

入口 hidden：

```text
_x_d1=TFe_mixed
_x_d2=_x_r_carb_mixed or Fe_carb load, config must state exact meaning
_x_d3=_x_d3_WI_mixed
_x_d4=water_pressure
_x_m_ball=M_wet_mixed
_x_rho_ball=C_mixed
_x_d80_ball,_x_f25_ball,_x_f200_ball,_x_f325_ball
_x_boundary_tfe,_x_boundary_c,_x_boundary_wi,_x_boundary_clay,_x_boundary_r_carb
_x_boundary_fe_mag,_x_boundary_fe_hem,_x_boundary_fe_carb,_x_boundary_fe_sil,_x_boundary_gangue,_x_boundary_feo_proxy
_x_eryi_line{i}_{m,c,tfe,f200,f325,f25,d80,liberation_fe,liberation_gangue,t_slurry,fe_mag,fe_hem,fe_carb,fe_sil,gangue,feo_proxy}
```

入口 lab：

```text
lab_{i}_eryi_tfe=100*_x_eryi_line{i}_tfe+N(0,sigma_tfe_pct)
lab_{i}_eryi_f200=100*_x_eryi_line{i}_f200+N(0,sigma_f200_pct)
```

## 5. 磁选因果模型

### 5.1 必须模拟的实际因果关系

```text
r_mag/Liberation_fe/F200/C/flow
  -> 磁选回收率
  -> 混磁精矿 TFe 和有害铁矿物富集
  -> 塔磨负荷和浮选给矿性质

r_carb/r_sil/clay/f25
  -> 夹带、矩阵堵塞、冲洗负荷
  -> 脉动频率、转环频率、排污阀、冲洗水压力
  -> DCS

Liberation_fe/r_mag/粗粒
  -> 励磁电流需求
  -> DCS
```

### 5.2 控制设定不得孤立

励磁电流：

```text
magnetic_difficulty =
  w_low_mag*(r_mag_ref-r_mag)
  + w_low_lib*(1-Liberation_fe)
  + w_coarse*(1-F200)
  + w_load*(Q_feed-Q_ref)
  + w_carb*r_carb
  + w_sil*r_sil

I_exc_sp = clip(I_nom
  + Kdiff_I*magnetic_difficulty
  - Kmag_I*(r_mag-r_mag_ref)
  + operator_trim_I
  + PRBS_mag_I,
  I_min,I_max)

I_exc=sat_act(I_exc_sp,I_min,I_max,tau_exc)
B_eff=B_max*(1-exp(-I_exc/I_ref))*thermal_derate(T_coil)
```

脉动频率：

```text
f_pul_sp=clip(f_pul_nom
  + Kcoarse_pul*(1-F325)
  + Kclay_pul*clay
  + Kslime_pul*f25
  + Kload_pul*(Q_feed-Q_ref)
  + operator_trim_pul,
  f_pul_min,f_pul_max)
f_pul=sat_act(f_pul_sp,f_pul_min,f_pul_max,tau_pul)
```

转环频率：

```text
clog_buildup =
  c0
  + c_clay*clay
  + c_f25*f25
  + c_C*C
  + c_load*Q_feed/max(Q_ref,eps)
clog_wash =
  c_flush_Q*Q_flush_lag/max(Q_flush_ref,eps)
  + c_pul_clog*f_pul_lag/max(f_pul_ref,eps)
matrix_clog = clip(matrix_clog_prev+dt*(clog_buildup-clog_wash),0,1)

f_ring_sp=clip(f_ring_nom
  + Kclog_ring*matrix_clog
  + Kcoarse_ring*(1-F200)
  + operator_trim_ring,
  f_ring_min,f_ring_max)
f_ring=sat_act(f_ring_sp,f_ring_min,f_ring_max,tau_ring)
```

### 5.3 分选公式

```text
capture_j=sigmoid(a0_j+aB_j*log(B_eff/B_ref)+aL_j*log(Liberation_j/L_ref)
  +aSize_j*(F200-F200_ref)+aC_j*(C-C_ref)-aQ_j*(Q_feed-Q_ref))

E_pulse=exp(-((f_pul-f_pul_opt)/sigma_pul)^2)
E_ring=exp(-((f_ring-f_ring_opt)/sigma_ring)^2)*(1-k_clog*matrix_clog)
E_level=exp(-((L_mag-L_ref)/sigma_L)^2)
Entr=clip(
  e0
  + eC*C
  + ef25*f25
  + eclay*clay
  + eL*(L_mag-L_ref)
  - e_pul*(f_pul-f_pul_min)/max(f_pul_ref,eps),
  0,e_max)

R_hm_j=clip(capture_j*E_pulse*E_ring*E_level,0,Rmax_j)
conc_j=R_hm_j*feed_j+Entr*Gangue*entr_share_j
tail_j=feed_j-conc_j
```

### 5.4 磁选 DCS 变量

| DCS | 实际父节点 | 公式 | 特征准入 |
|---|---|---|---|
| `agg_mag_excit_current` | `I_exc_sp`, `I_exc`, 难选性、解离度、r_mag | 具体公式见第 10.2 节 | DCS |
| `agg_mag_excit_voltage` | `I_exc`, `T_coil`, 电阻 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_coil_temp` | `I_exc^2`, 冷却水、环境 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_pulsation_freq` | 粒度、clay、f25、负荷 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_ring_freq` | matrix_clog、粗粒、clay | 具体公式见第 10.2 节 | DCS |
| `agg_mag_level` | 入流、出流、阀位 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_tailings_valve1/2` | 液位控制 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_blowdown_valve` | matrix_clog、排污策略 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_flush_water_pressure` | 公共水压、冲洗阀、堵塞 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_motor_current_rc` | 转环频率、矿浆密度、堵塞、负荷 | 具体公式见第 10.2 节 | DCS |
| `agg_mag_motor_voltage_rc` | 电网、电流负荷 | 具体公式见第 10.2 节 | DCS |

## 6. 塔磨与旋流器因果模型

### 6.1 必须模拟的实际因果关系

```text
WI/Liberation_potential/F325_sand/C/rho_solid_mix
  -> 塔磨功耗、电流、温度、粒度改善
  -> 旋流器分级效率、返砂负荷
  -> 浮选给矿 F325/Liberation
  -> 精矿品位
```

### 6.2 泵池与旋流器

```text
dL_pool/dt=(Q_in-Q_pump-Q_spill)/A_pool
P_cyc_lag=delay(P_cyc,L_pump_pressure)
f_pump_sp=clip(f0+Kp_L*(L_pool-L_sp)+Kp_P*(P_sp-P_cyc_lag)+Kff_Q*Q_in,f_min,f_max)
f_pump=sat_act(f_pump_sp,f_min,f_max,tau_pump)
Q_pump=k_pump*f_pump*(1-exp(-max(L_pool,0)/max(L_min_safe,eps)))*health_pump
P_cyc=clip(kP*rho_slurry*(Q_pump/max(N_cyc_on,1))^2,P_min,P_max)
I_pump=I0+kf*f_pump^2+kQ*Q_pump+krho*rho_slurry+kmu*mu_slurry+kP_pump*P_cyc
```

旋流器给矿泵池必须作为 CSTR 混合缓冲，不能让磁选精矿和塔磨排矿的粒度/解离度瞬时穿透到旋流器：

```text
tau_cyc_pool=max(L_pool*A_pool/max(Q_pump,eps),min_tau_cyc_pool)
C_feed_in=(M_mag_conc_solid+M_tm_discharge_solid_prev)/max(M_mag_conc_wet+M_tm_discharge_wet_prev+M_water_add,eps)
F325_feed_in=(M_mag_conc_solid*F325_mag_conc+M_tm_discharge_solid_prev*F325_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
Liberation_fe_feed_in=(M_mag_conc_solid*Liberation_fe_mag_conc+M_tm_discharge_solid_prev*Liberation_fe_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
Liberation_gangue_feed_in=(M_mag_conc_solid*Liberation_gangue_mag_conc+M_tm_discharge_solid_prev*Liberation_gangue_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
WI_feed_in=(M_mag_conc_solid*WI_mag_conc+M_tm_discharge_solid_prev*WI_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)

C_feed=C_feed_prev+(dt/max(tau_cyc_pool,eps))*(C_feed_in-C_feed_prev)
F325_feed=F325_feed_prev+(dt/max(tau_cyc_pool,eps))*(F325_feed_in-F325_feed_prev)
Liberation_fe_feed=Liberation_fe_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_fe_feed_in-Liberation_fe_feed_prev)
Liberation_gangue_feed=Liberation_gangue_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_gangue_feed_in-Liberation_gangue_feed_prev)
WI_feed=WI_feed_prev+(dt/max(tau_cyc_pool,eps))*(WI_feed_in-WI_feed_prev)
```

旋流器分级：

```text
d50=d50_ref*(P_ref/max(P_cyc,eps))^aP*(C/C_ref)^aC*(mu_slurry/mu_ref)^amu
alpha_ov=clip(sigmoid(kF*(F325_feed-F325_ref)+kP*(P_cyc-P_ref)-kC*(C-C_ref)-kmu*(mu_slurry-mu_ref)),0,1)
overflow_j=feed_j*partition_fine_j(d50,alpha_ov)
sand_j=feed_j-overflow_j

M_overflow_solid = feed_solid*alpha_ov
M_sand_solid = feed_solid-M_overflow_solid

alpha_ov_water = clip(alpha_ov*k_water_split,0,1)
M_overflow_water = feed_water*alpha_ov_water
M_sand_water = feed_water-M_overflow_water

Q_overflow = M_overflow_solid/rho_solid_mix + M_overflow_water/rho_water
rho_overflow = (M_overflow_solid+M_overflow_water)/max(Q_overflow,eps)

F325_overflow = clip(F325_feed*k_fine_enrich/max(alpha_ov,eps),F325_feed,1.0)
Liberation_fe_overflow = clip(Liberation_fe_feed*k_lib_fe_enrich,Liberation_fe_feed,1.0)
Liberation_gangue_overflow = clip(Liberation_gangue_feed*k_lib_g_enrich,Liberation_gangue_feed,1.0)

F325_sand = clip(
  (F325_feed-F325_overflow*alpha_ov)/max(1-alpha_ov,eps),
  0,F325_feed)
Liberation_fe_sand = clip(
  (Liberation_fe_feed-Liberation_fe_overflow*alpha_ov)/max(1-alpha_ov,eps),
  0,Liberation_fe_feed)
Liberation_gangue_sand = clip(
  (Liberation_gangue_feed-Liberation_gangue_overflow*alpha_ov)/max(1-alpha_ov,eps),
  0,Liberation_gangue_feed)

T_slurry_overflow = T_slurry_feed-k_cool_cyc*max(T_slurry_feed-T_amb,0)
T_slurry_sand = T_slurry_feed-k_cool_sand*max(T_slurry_feed-T_amb,0)
```

### 6.3 塔磨功耗和解离

```text
inst_circ_load=M_sand/max(M_overflow,eps)
circulating_load=clip(inst_circ_load,0.0,5.0)
circulating_load_lag=delay(circulating_load,L_sand_control)
M_mill_water_in=M_sand_water+Q_sand_water_phys*rho_water
C_mill=M_sand/max(M_sand+M_mill_water_in,eps)
WI_mill=WI_sand
# WI_mill 必须来自随物流传递的 Stream，禁止直接读取入口边界 WI_i(t)。
grind_difficulty =
  kWI*(WI_mill-WI_ref)
  + kcoarse*(1-F325_sand)
  + kC*(C_mill-C_opt)^2
  + kmu*(mu_slurry-mu_ref)
  + kCL*(circulating_load-CL_ref)

P_mech_ss=P_idle+P_media+kM*M_sand*(1+grind_difficulty)
P_mech=ZOH(P_mech,clip(P_mech_ss,0,1.15*P_rated),tau_P)
I_tm=P_mech/(sqrt(3)*V_motor*pf*eta)

E_spec=P_mech/max(M_sand,eps)
F325_discharge_inst=clip(F325_sand+kE*log1p(E_spec/max(WI_mill,eps))-k_over*f25,0,1)
Liberation_fe_discharge_inst = clip(
  Liberation_fe_sand
  + k_lib_fe*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_fe_sand),
  0,1)
Liberation_gangue_discharge_inst = clip(
  Liberation_gangue_sand
  + k_lib_g*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_gangue_sand),
  0,1)

delta_T_mill = P_mech*k_heat_conv/max(Q_pump*rho_slurry*Cp_slurry,eps)
T_slurry_discharge_inst =
  T_slurry_sand
  + delta_T_mill
  - k_cool_pipe*max(T_slurry_sand-T_amb,0)

F325_discharge=F325_discharge_prev+(dt/max(tau_mill_residence,eps))*(F325_discharge_inst-F325_discharge_prev)
Liberation_fe_discharge=Liberation_fe_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_fe_discharge_inst-Liberation_fe_discharge_prev)
Liberation_gangue_discharge=Liberation_gangue_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_gangue_discharge_inst-Liberation_gangue_discharge_prev)
T_slurry_discharge=T_slurry_discharge_prev+(dt/max(tau_mill_residence,eps))*(T_slurry_discharge_inst-T_slurry_discharge_prev)
WI_discharge=WI_mill
```

### 6.4 塔磨 DCS 变量

| DCS | 实际父节点 | 公式 | 特征准入 |
|---|---|---|---|
| `agg_tm_motor_current` | `WI`, `F325_sand`, `C_mill`, `mu_slurry`, 返砂负荷 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_feed_flow` | 泵频、液位、矿浆密度 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_pump_freq` | 液位/压力控制 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_pump_current` | 泵频、流量、密度、黏度、扬程 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_pool_level` | 入流、泵出流、返砂 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_pool_valve_setpoint` | 浓度/液位控制 | 具体公式见第 10.3 节 | DCS |
| `MC1_FET503_AI` | 水阀、公共水压 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_sand_valve_setpoint` | 沉砂浓度、返砂负荷 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_sand_valve_feedback` | 执行器 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_sand_water_flow` | 沉砂水阀、水压 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_reducer_oil_temp` | 功率、冷却 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_reducer_outlet_temp` | 油温、循环流量 | 具体公式见第 10.3 节 | DCS |
| `MC1_TM204_HDZC_1_WD_AI` | 轴承负荷、功率、故障 | 具体公式见第 10.3 节 | DCS |
| `MC1_TM206_HDZC_2_WD_AI` | 轴承负荷、功率、故障 | 具体公式见第 10.3 节 | DCS |
| `MC1_TM204_ZDJ_DZ_A_WD_AI` | 电机电流、散热 | 具体公式见第 10.3 节 | DCS |
| `MC1_TM206_ZDJ_DZ_B_WD_AI` | 电机电流、散热 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_cyclone_overflow_pool_level` | 溢流流量、泵出流 | 具体公式见第 10.3 节 | DCS |
| `agg_tm_overflow_pump_current` | 溢流泵频、流量、密度 | 具体公式见第 10.3 节 | DCS |

推荐新增：

```text
agg_tm_cyclone_feed_pressure 具体公式见第 10.3 节
```

该列必须使用 `rho_slurry`，而 `rho_slurry` 必须由矿物组分密度计算，不能固定为常数密度。

## 7. 浮选因果模型

### 7.1 必须模拟的实际因果关系

```text
浮选给矿 TFe/r_carb/r_sil/Liberation_gangue/F325/f25/C/clay
  -> 药剂需求、pH 缓冲、Ca2+、矿浆黏度、疏水负荷
  -> 药剂泵频、pH、气量、泡沫高度、电机电流、泵电流
  -> 脉石浮出、铁损失、夹带、精选精矿 TFe
```

### 7.2 浮选前浓缩

浓缩机不能完全抹平上游信息。浓度控制可以压制 `C`，但密度、黏度、电流、底流流量仍必须保留矿质投影。

```text
dM_NT_solid/dt=M_in_solid-M_under_solid-M_over_solid
dV_NT_water/dt=Q_in_water-Q_under_water-Q_over_water
L_NT=(M_NT_solid/rho_solid_mix+V_NT_water)/A_NT
C_under_sp=clip(C_nom+Kbed*(L_NT-L_ref)+Kload*(M_in-M_ref),C_min,C_max)
C_under=ZOH(C_under,C_under_sp,tau_C)
rho_under=rho_slurry(C_under,rho_solid_mix)
T_under=T_NT_in-k_cool_NT*max(T_NT_in-T_amb,0)
mu_under=mu_slurry(C_under,clay,f25,r_sil,T_under)
I_NT=I0+kM*M_solid+kmu*mu_under+kbed*bed_mass
```

DCS：

```text
fx_nt{s}_underflow_density 按第 10.4 节 `rho_under -> x_phys -> x_lpf -> x_dcs` 展开
fx_nt{s}_motor_current 按第 10.4 节 `I_NT -> x_phys -> x_lpf -> x_dcs` 展开
```

### 7.3 药剂控制

药剂频率禁止 AR 名义漂移。必须按难选性和泡沫状态反馈：

```text
floatability_difficulty =
  w_carb*r_carb
  + w_sil*r_sil
  + w_fine*f25
  + w_coarse*(1-F325)
  + w_low_lib*(1-Liberation_gangue)
  + w_density*abs(C-C_opt)
  + w_clay*clay

froth_error = h_ref-h_froth_sensor
selectivity_proxy =
  q_pH*exp(-((pH-pH_opt)/sigma_pH)^2)
  + q_lib*Liberation_gangue
  - q_Ca*Ca2_effect
  - q_slime*f25

dose_need_TD_rough =
  d0_td_r
  + Kload_td*M_feed_solid
  + Kdiff_td*floatability_difficulty
  + Kfroth_td*froth_error
  + operator_trim_td
  + PRBS_TD

dose_need_TD_clean =
  d0_td_c
  + Kproxy_td*(quality_proxy_ref-quality_proxy_s)
  + Kdiff_clean*floatability_difficulty
  + operator_trim_td_clean

dose_need_DF_K6 =
  d0_k6
  + Kslime_k6*f25
  + Ksil_k6*r_sil
  + Kcarb_k6*r_carb
  + Kselect_k6*(selectivity_ref-selectivity_proxy)

f_j_sp=dose_to_freq(dose_need_j,M_feed_solid)
f_j=sat_act(f_j_sp,f_min_j,f_max_j,tau_j)
Q_j_ml_s=max(k_pump_j*f_j*health_j+noise,0)
dose_j_kg_t=Q_j_ml_s*3.6*rho_j_kg_L*active_j/max(M_feed_solid_tph,eps)
```

DCS：

```text
fx_s{s}_{td_rough,td_clean,k6_rough,naoh,cao}_freq 按第 10.4 节 `f_j -> x_lpf -> x_dcs` 展开
fx_s{s}_{td_rough,td_clean,k6_rough,naoh,cao}_curr 按第 10.4 节 `I_drug_j_phys -> x_lpf -> x_dcs` 展开
fx_s{s}_k6_level 按第 10.4 节 `L_k6 -> x_lpf -> x_dcs` 展开
```

### 7.4 NaOH/CaO/pH/Ca2+

NaOH 和 CaO 必须拆开：

```text
pH_sp=clip(pH_nom
  + Kcarb_sp*(r_carb-r_carb_ref)
  + Ksil_sp*(r_sil-r_sil_ref)
  + operator_trim_pH
  + PRBS_pH,
  pH_min,pH_max)

dose_need_naoh=d0_naoh+Kp_pH*(pH_sp-pH_sensor)+Kbuf_naoh*buffer_capacity+Kflow_naoh*M_feed_solid
dose_need_cao=d0_cao+Kcarb_cao*r_carb+Ksil_cao*r_sil+Kbuf_cao*buffer_capacity

OH_effect=k_naoh_oh*dose_naoh_kg_t+k_cao_oh*dose_cao_kg_t
Ca2_effect=k_cao_ca*dose_cao_kg_t
pH_ss=pH_base+k_pH*log1p(OH_effect/max(buffer_capacity,eps))
pH=ZOH(pH,pH_ss,tau_pH)+process_noise

E_Ca2_sil=1+a_Ca_sil*sigmoid((Ca2_effect-Ca_sil0)/s_Ca_sil)
E_Ca2_carb=1+a_Ca_carb*sigmoid((Ca2_effect-Ca_carb0)/s_Ca_carb)
```

DCS：

```text
fx_s{s}_ph 按第 10.4 节 `pH -> x_lpf -> x_dcs` 展开
```

### 7.5 气量和泡沫控制

气量必须由泡沫、负荷和矿质代理驱动：

```text
hydrophobic_load =
  M_froth_gangue
  + M_froth_fe_sil
  + M_froth_fe_carb
  + k_fe_froth*(M_froth_fe_mag+M_froth_fe_hem)

Q_air_sp=clip(Q_air_nom
  + Kh*(h_ref-h_froth_sensor)
  + Kload*(M_feed_solid-M_ref)
  + Khydro*(hydrophobic_load-hydro_ref)
  + Kdensity*(C-C_ref)
  + operator_trim_air
  + PRBS_air,
  Q_air_min,Q_air_max)

u_bv=sat_act(valve_from_air_sp(Q_air_sp,P_blower,P_cell),0.1,0.9,tau_bv)
Q_air=C_orifice*u_bv*sqrt(max(P_blower-P_cell,0))
```

泡沫高度：

```text
scraper_speed = clip(
  scraper_nom+K_scrape_P*max(h_froth-h_scrape_ref,0),
  speed_min,speed_max)

froth_stability =
  s0
  + s_TD*dose_TD
  + s_K6*dose_DF_K6
  + s_f25*f25
  + s_C*C
  + s_Ca*Ca2_effect
  + s_lib*Liberation_gangue
  + s_clay*clay

h_ss=k_h*Q_air*hydrophobic_load*froth_stability/max(k_collapse+k_scrape*scraper_speed,eps)
h_froth=ZOH(h_froth,clip(h_ss,0,h_max),tau_froth)
```

泡沫故障规则：

```text
fx_s{s}_{c}_froth_h =
  if event_froth_fault_{s,c}=1: fault_value
  else: 按第 10.4 节 `h_froth -> x_lpf -> x_dcs` 展开

必须同时输出 event_froth_fault_{s,c} 或在评估中可识别故障窗口。
禁止让 -21 等故障值混入正常窗口评估。
```

### 7.6 液位、流量、停留时间

液位是流量平衡，不是随机漂移：

```text
gas_holdup=clip(k_gas*Q_air*(1+k_mu_gas*max(mu_slurry-mu_ref,0)),0,gas_holdup_max)
L_cell_aerated=L_cell/max(1-gas_holdup,eps)
u_lv_sp=clip(u0+Kp_L*(L_sp-L_cell_aerated_lag)+Ki_L*int(L_sp-L_cell_aerated_lag),0,1)
u_lv_fb=sat_act(u_lv_sp,0,1,tau_lv)
Q_out_cell=Cv_lv*u_lv_fb*sqrt(max(L_cell,0))
V_pulp_actual=A_cell*max(L_cell,0)
tau_stage_h=V_pulp_actual/max(Q_out_cell,eps)
Q_froth_cell = sum_j(froth_j)/max(rho_froth_mix,eps)
dL_cell/dt=(Q_in_cell-Q_out_cell-Q_froth_cell)/A_cell
```

DCS：

```text
fx_s{s}_{c}_level 按第 10.4 节 `L_cell_aerated -> x_lpf -> x_dcs` 展开
fx_s{s}_{c}_level_valve_sp 按第 10.4 节 `u_lv_sp -> x_lpf -> x_dcs` 展开
fx_s{s}_{c}_level_valve_fb 按第 10.4 节 `u_lv_fb -> x_lpf -> x_dcs` 展开
```

### 7.7 浮选速率和组分分流

必须加入 `Liberation_gangue`：

```text
entrainment_factor =
  e0
  + e_f25*f25
  + e_clay*clay
  + e_C*C
  + e_mu*max(mu_slurry-mu_ref,0)

dose_TD_effective=dose_TD_effective_prev+(dt/max(tau_adsorption_TD,eps))*(dose_TD-dose_TD_effective_prev)
dose_DF_K6_effective=dose_DF_K6_effective_prev+(dt/max(tau_adsorption_K6,eps))*(dose_DF_K6-dose_DF_K6_effective_prev)

E_collector=sigmoid(a1*(dose_TD_effective-dose_low))*sigmoid(a2*(dose_high-dose_TD_effective))
E_depressant=sigmoid(kK6*(dose_DF_K6_effective-dose_K6_ref))
E_pH=exp(-((pH-pH_opt)/sigma_pH)^2)
E_air=sigmoid(k1*(Q_air-Q_low))*sigmoid(k2*(Q_high-Q_air))
E_density=exp(-((C-C_opt)/sigma_C)^2)
E_size=sigmoid(k_size*(F325-F325_min))
E_lib_g=0.25+0.75*Liberation_gangue
E_mu=exp(-k_mu_float*(mu_slurry-mu_ref))

k_float_gangue=k0_g*E_collector*E_pH*E_air*E_density*E_size*E_lib_g*E_mu
k_float_sil=k_float_gangue*(1+a_sil*r_sil)*E_Ca2_sil
k_float_carb=k_float_gangue*(1+a_carb*r_carb)*E_Ca2_carb
k_float_fe_mag=k0_mag*(1-E_depressant)*entrainment_factor
k_float_fe_hem=k0_hem*(1-E_depressant)*entrainment_factor

lip_clearance=L_cell+h_froth-H_lip_reference
R_froth_zone=clip(
  sigmoid(k_lip*lip_clearance)*h_froth/max(h_froth_target,eps),
  0,1)

grade_cell_j=M_cell_j_prev/max(M_cell_solid_prev,eps)
Q_out_solid=Q_out_cell*rho_slurry*C
R_j=clip(1-exp(-k_float_j*tau_stage_h),0,Rmax_j)*R_froth_zone
froth_j_rate=R_j*M_cell_j_prev/max(tau_stage_h,eps)+entrainment_j_rate
tail_j_rate=Q_out_solid*grade_cell_j
dM_cell_j/dt=feed_j_rate-froth_j_rate-tail_j_rate
M_cell_j=M_cell_j_prev+dt*dM_cell_j/dt

froth_j=froth_j_rate*dt
tail_or_conc_j=tail_j_rate*dt
```

拓扑：

```text
rougher_feed=flo_feed+cleaner_tail_prev+scav1_conc_prev
rougher_froth -> cleaner_feed
rougher_tail -> scav1_feed
cleaner_froth -> final_conc
cleaner_tail -> rougher_feed_next
scav1_froth -> rougher_feed_next
scav1_tail -> scav2_feed
scav2_froth -> scav1_feed_next
scav2_tail -> scav3_feed
scav3_froth -> scav2_feed_next
scav3_tail -> final_tail
```

最终标签：

```text
y_fx_xin_s_true=TFe(final_conc_s)
y_fx_xin_s=clip(y_fx_xin_s_true+N(0,sigma_y),0,1)
```

`close_final_products` 只能用于轻微质量闭合，禁止过度裁剪导致上游 DCS 效应被抹掉。

### 7.8 浮选 DCS 变量模板

槽变量，`s in {1,2}`, `c in {cx1,cx2,cx3,jx,sx1,sx2,sx3}`：

| DCS 模板 | 实际父节点 | 公式 | 特征 |
|---|---|---|---|
| `fx_s{s}_{c}_froth_h` | 疏水负荷、气量、药剂、粒度、解离、Ca2+ | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_level` | 真实液位、气量、气含率、矿浆黏度 | 具体公式见第 10.4 节 `L_cell_aerated` | DCS |
| `fx_s{s}_{c}_level_valve_sp` | 表观液位控制器 | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_level_valve_fb` | 阀门执行器 | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_air_flow` | 气量设定、蝶阀、鼓风机压力 | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_air_sp` | 泡沫/负荷控制 | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_bv_pos` | 气阀执行器 | 具体公式见第 10.4 节 | DCS |
| `fx_s{s}_{c}_motor_curr` | 密度、黏度、气量、负荷 | 具体公式见第 10.4 节 | DCS |

药剂变量：

| DCS 模板 | 实际父节点 | 公式 | 特征 |
|---|---|---|---|
| `fx_s{s}_td_rough_freq` | 粗选 TD 需求、给矿量、难选性、泡沫偏差、PRBS/操作员调整 | 具体公式见第 10.4 节 `dose_need_TD_rough -> f_j` | DCS |
| `fx_s{s}_td_rough_curr` | TD 粗选泵频、药剂黏度、供药压力、泵健康 | 具体公式见第 10.4 节 `I_drug_j_phys` | DCS |
| `fx_s{s}_td_clean_freq` | 精选 TD 需求、滞后质量代理、难选性、操作员调整 | 具体公式见第 10.4 节 `dose_need_TD_clean -> f_j` | DCS |
| `fx_s{s}_td_clean_curr` | TD 精选泵频、药剂黏度、供药压力、泵健康 | 具体公式见第 10.4 节 `I_drug_j_phys` | DCS |
| `fx_s{s}_k6_rough_freq` | DF/K6 需求、f25、r_sil、r_carb、选择性代理 | 具体公式见第 10.4 节 `dose_need_DF_K6 -> f_j` | DCS |
| `fx_s{s}_k6_rough_curr` | K6 泵频、药剂黏度、供药压力、泵健康 | 具体公式见第 10.4 节 `I_drug_j_phys` | DCS |
| `fx_s{s}_naoh_freq` | pH 偏差、缓冲能力、给矿量 | 具体公式见第 10.4 节 `dose_need_naoh -> f_j` | DCS |
| `fx_s{s}_naoh_curr` | NaOH 泵频、药剂黏度、供药压力、泵健康 | 具体公式见第 10.4 节 `I_drug_j_phys` | DCS |
| `fx_s{s}_cao_freq` | r_carb、r_sil、缓冲能力、Ca2+ 需求 | 具体公式见第 10.4 节 `dose_need_cao -> f_j` | DCS |
| `fx_s{s}_cao_curr` | CaO 泵频、药剂黏度、供药压力、泵健康 | 具体公式见第 10.4 节 `I_drug_j_phys` | DCS |

其他浮选 DCS：

| DCS 模板 | 实际父节点 | 公式 | 特征 |
|---|---|---|---|
| `fx_nt{s}_motor_current` | 浓缩机固体负荷、床层质量、底流黏度 | 具体公式见第 10.4 节 `I_NT_s` | DCS |
| `fx_nt{s}_underflow_density` | 浮选前浓缩底流浓度、组分固体密度 | 具体公式见第 10.4 节 `rho_under_s` | DCS |
| `fx_s{s}_ph` | NaOH/CaO 单耗、缓冲能力、pH 动态 | 具体公式见第 10.4 节 `pH_s` | DCS |
| `fx_s{s}_k6_level` | K6 消耗、补加事件、药箱截面积 | 具体公式见第 10.4 节 `L_k6_s` | DCS |
| `fx_s{s}_tk{k}_temp` | 第 k 搅拌槽蒸汽阀、环境、搅拌功率、药剂流量 | 具体公式见第 10.4 节 `T_tank_{s,k}` | DCS |
| `fx_s{s}_tk{k}_mixer_curr` | 第 k 搅拌槽浓度、矿浆黏度 | 具体公式见第 10.4 节 `I_mixer_phys_{s,k}` | DCS |
| `fx_s{s}_tk{k}_steam_sp` | 第 k 搅拌槽温控器 | 具体公式见第 10.4 节 `u_steam_sp_{s,k}` | DCS |
| `fx_s{s}_tk{k}_steam_fb` | 第 k 蒸汽阀执行器 | 具体公式见第 10.4 节 `u_steam_fb_{s,k}` | DCS |
| `fx_s{s}_pool{k}_level` | 第 k 泵池入流、泵出流、槽段拓扑 | 具体公式见第 10.4 节 `L_pool_{s,k}` | DCS |
| `fx_s{s}_pool{k}_pump_freq` | 第 k 泵池液位控制器 | 具体公式见第 10.4 节 `f_pool_{s,k}` | DCS |
| `fx_s{s}_pool{k}_pump_curr` | 第 k 泵频、流量、密度、黏度、扬程 | 具体公式见第 10.4 节 `I_pool_phys_{s,k}` | DCS |
| `fx_blower{b}_pressure` | 第 b 鼓风机转速、母管压力、分担气量、风机健康 | 具体公式见第 10.4 节 `P_blower_pressure_b` | DCS |
| `fx_ah5_power` | 1 系列槽电机、泵、药剂泵、鼓风分摊、辅机功率 | 具体公式见第 10.4 节 `P_series1` | DCS |
| `fx_ah6_power` | 2 系列槽电机、泵、药剂泵、鼓风分摊、辅机功率 | 具体公式见第 10.4 节 `P_series2` | DCS |
| `fx_s1_ft1701` | 总给矿流量、系列分配、1 系列 1701 支路阻力 | 具体公式见第 10.4 节 `Q_ft_s1_1701_phys` | DCS |
| `fx_s1_ft1702` | 总给矿流量、系列分配、1 系列 1702 支路阻力 | 具体公式见第 10.4 节 `Q_ft_s1_1702_phys` | DCS |
| `fx_s2_ft2701` | 总给矿流量、系列分配、2 系列 2701 支路阻力 | 具体公式见第 10.4 节 `Q_ft_s2_2701_phys` | DCS |
| `fx_s2_ft2702` | 总给矿流量、系列分配、2 系列 2702 支路阻力 | 具体公式见第 10.4 节 `Q_ft_s2_2702_phys` | DCS |

## 8. 过程化验设计

过程化验是输出，不是 DCS。生成规则：

```text
if sample_time(var):
  lab_sample=100*true_value_at_sample_point+N(0,sigma_sampling)+N(0,sigma_assay)
  report_time=sample_time+report_delay
else:
  lab_var=NaN
```

训练可用值：

```text
lab_feature(t)=last_reported_value(report_time<=t)
```

### 8.1 可选上游 lab

可以作为历史报出特征：

```text
lab_1_eryi_tfe, lab_1_eryi_f200
lab_2_eryi_tfe, lab_2_eryi_f200
lab_3_eryi_tfe, lab_3_eryi_f200
lab_mag_wm_conc_tfe, lab_mag_wm_tail_tfe
lab_mag_hm_conc_tfe, lab_mag_hm_tail_tfe
lab_mag_sw_conc_tfe, lab_mag_sw_tail_tfe
lab_mag_mixed_conc_tfe
lab_mag_tube_conc_tfe, lab_mag_tube_yield
lab_tm_feed_f325
lab_tm_discharge_f325
lab_tm_overflow_f325
lab_tm_overflow_tfe
lab_tm_overflow_conc
lab_tm_sand_f325
lab_flo_feed_tfe_s1/s2
lab_flo_feed_f325_s1/s2
```

注意：`lab_flo_feed_*` 是浮选给矿样，必须按报出时刻使用，不可使用当前未报出值。

### 8.2 默认禁止 lab

```text
lab_flo_conc_tfe_s1/s2
lab_flo_tail_tfe_s1/s2
lab_flo_rough_conc_tfe_s1/s2
lab_flo_rough_tail_tfe_s1/s2
lab_flo_clean_tail_tfe_s1/s2
lab_flo_scav*_*
lab_flo_final_conc_yield_s1/s2
lab_flo_final_conc_recovery_s1/s2
```

这些属于浮选内部、近最终或最终结果，默认禁止作为主软测量输入。

## 9. 特征目录

```text
DCS-only =
  STEP1_COLUMNS + STEP2_COLUMNS + STEP3_COLUMNS
  - {y_fx_xin1,y_fx_xin2}

allowed_upstream_lab =
  boundary lab + magnetic lab + tower-mill lab + lab_flo_feed_*
  with report_time <= prediction_time

forbidden =
  y_fx_xin*
  _x_*
  lab_flo_conc/tail/rough/clean/scav/final_*
  any current unreported lab
```

单位：

```text
y_fx_xin1=0.67 表示 67%
lab_*_tfe=67 表示 67%
内部 TFe=0.67
```

## 10. DCS 具体生成公式和代理防护

本节替代前文表格中的所有 `sensor(...)` 略写。实现时必须把每个 DCS 写成：

```text
x_phys = f(allowed_parents)
x_lpf(t)=x_phys(t)+(x_lpf(t-dt)-x_phys(t))*exp(-dt/tau_sensor)
x_dcs(t)=clip(x_lpf(t)+bias+N(0,sigma),x_min,x_max)
if event_fault=1: x_dcs(t)=fault_value
```

下文输出映射中的 `meas(x_phys)` 不是新的略写公式，而是表示必须逐列代入上面三行测量方程。例如：

```text
agg_tm_motor_current = meas(I_tm_phys)
```

在代码和参数表中必须展开为：

```text
agg_tm_motor_current_lpf(t)
  = I_tm_phys(t)
    + (agg_tm_motor_current_lpf(t-dt)-I_tm_phys(t))*exp(-dt/tau_tm_motor_current_sensor)

agg_tm_motor_current_raw(t)
  = agg_tm_motor_current_lpf(t)
    + bias_tm_motor_current
    + N(0,sigma_tm_motor_current^2)

agg_tm_motor_current(t)
  = if event_tm_motor_current_fault(t)=1
    then fault_value_tm_motor_current(t)
    else clip(agg_tm_motor_current_raw(t),I_tm_motor_min,I_tm_motor_max)
```

其他所有 `meas(...)` 输出同理展开；不允许在设计实现中只保留 `meas` 或 `sensor` 函数名而不列父节点和物理量。

### 10.1 显著目标代理禁止规则

任何 DCS 的父节点禁止包含：

```text
y_fx_xin1, y_fx_xin2
y_fx_xin*_true
_x_TFe_circuit_s1/s2
_x_flo_final_conc_*_tfe
_x_flo_final_tail_*_tfe
lab_flo_conc_tfe_s1/s2
lab_flo_tail_tfe_s1/s2
lab_flo_rough_*
lab_flo_clean_*
lab_flo_scav*
lab_flo_final_*
future lab values
```

当前隐藏给矿品位也不能直接作为操作员控制器输入。若现场确实会参考品位，只能通过以下滞后可用代理：

```text
quality_proxy_s(t) =
  w1*ffill_reported(lab_tm_overflow_tfe, report_time<=t)
  + w2*ffill_reported(lab_mag_mixed_conc_tfe, report_time<=t)
  + w3*online_load_proxy(t)
  + w4*online_froth_proxy(t)
```

其中：

```text
online_load_proxy = standardized(tm_motor_current_lag, cyclone_pressure_lag, feed_flow_lag)
online_froth_proxy = standardized(froth_h_lag, air_flow_lag, reagent_freq_lag)
```

`quality_proxy_s` 不能使用当前或未来的最终浮选产品信息。任一单个 DCS 变量如果在正常窗口中对 `y_fx_xin*` 的单变量 R2 超过 0.9，或者与 `y_fx_xin*` 的最大滞后相关绝对值超过 0.95，必须判定为疑似目标代理，回查其父节点和公式。

允许 DCS 与目标有中等相关，但必须来自多段间接路径：

```text
矿质/负荷 -> 控制需求/设备负荷 -> DCS
矿质/负荷 -> 浮选速率 -> y
```

禁止路径：

```text
y 或 final_conc_tfe -> DCS
```

### 10.2 磁选 DCS 具体公式

```text
magnetic_difficulty =
  w_low_mag*clip(r_mag_ref-r_mag,0,1)
  + w_low_lib*(1-Liberation_fe)
  + w_coarse*(1-F200)
  + w_load*(Q_feed-Q_ref)/max(Q_ref,eps)
  + w_harmful*(r_carb+r_sil)

I_exc_sp = clip(I_nom+Kdiff_I*magnetic_difficulty-Kmag_I*(r_mag-r_mag_ref)+operator_trim_I+PRBS_mag_I,I_min,I_max)
I_exc = I_exc_sp+(I_exc_prev-I_exc_sp)*exp(-dt/tau_exc_act)

R_coil = R0_coil*(1+alpha_Cu*(T_coil-T_ref))
V_exc_phys = R_coil*I_exc
P_coil_loss = I_exc^2*R_coil
Q_cooling_water = k_pipe_cooling*sqrt(max(water_pressure,0))
T_coil_ss = T_amb + k_loss_coil*P_coil_loss - k_cool_coil*Q_cooling_water
T_coil = T_coil_ss+(T_coil_prev-T_coil_ss)*exp(-dt/tau_coil)

clog_buildup =
  c0
  + c_clay*clay
  + c_f25*f25
  + c_C*C
  + c_load*Q_feed/max(Q_ref,eps)
clog_wash =
  c_flush_Q*Q_flush_prev/max(Q_flush_ref,eps)
  + c_pul_clog*f_pul_prev/max(f_pul_ref,eps)
matrix_clog = clip(matrix_clog_prev+dt*(clog_buildup-clog_wash),0,1)
f_pul_sp = clip(f_pul_nom+Kcoarse_pul*(1-F325)+Kclay_pul*clay+Kslime_pul*f25+Kload_pul*(Q_feed-Q_ref)/max(Q_ref,eps),f_pul_min,f_pul_max)
f_ring_sp = clip(f_ring_nom+Kclog_ring*matrix_clog+Kcoarse_ring*(1-F200),f_ring_min,f_ring_max)
f_pul = f_pul_sp+(f_pul_prev-f_pul_sp)*exp(-dt/tau_pul_act)
f_ring = f_ring_sp+(f_ring_prev-f_ring_sp)*exp(-dt/tau_ring_act)

M_conc_solid = sum_j(conc_j)
Q_conc_water = Q_feed_water*clip(k_w0+k_w_clog*matrix_clog,0.05,0.3)
Q_conc = M_conc_solid/rho_solid_mix+Q_conc_water
dL_mag/dt = (Q_feed-Q_tail-Q_conc)/A_mag
u_tail_total_sp = clip(u_tail_nom+K_L_tail*(L_mag-L_mag_sp),0,1)
split_tail_1 = clip(split_tail_1_nom+K_asym_tail*(matrix_clog-matrix_clog_ref)+operator_trim_tail_split,0.25,0.75)
u_tail_1_sp = clip(u_tail_total_sp*split_tail_1/split_tail_1_nom,0,1)
u_tail_2_sp = clip(u_tail_total_sp*(1-split_tail_1)/(1-split_tail_1_nom),0,1)
u_tail = u_tail_1_sp+(u_tail_prev-u_tail_1_sp)*exp(-dt/tau_tail_valve)
u_tail_2 = u_tail_2_sp+(u_tail_2_prev-u_tail_2_sp)*exp(-dt/tau_tail_valve)
specific_gravity = rho_slurry/max(rho_water,eps)
Q_tail_1 = Cv_tail1*u_tail*sqrt(max(L_mag,0)/max(specific_gravity,eps))
Q_tail_2 = Cv_tail2*u_tail_2*sqrt(max(L_mag,0)/max(specific_gravity,eps))
Q_tail = Q_tail_1+Q_tail_2

u_blowdown_phys = clip(u_bd_nom+Kclog_bd*matrix_clog+Ktimer_bd*event_bd_timer,0,1)
N_flush_open = clip(round(N_flush_base+Kclog_flush_N*matrix_clog+Kload_flush_N*Q_feed/max(Q_ref,eps)),N_flush_min,N_flush_max)
u_flush_sp = clip(
  u_flush_nom
  + Kclog_flush_u*matrix_clog
  + Kload_flush_u*(Q_feed-Q_ref)/max(Q_ref,eps),
  0,1)
u_flush = u_flush_sp+(u_flush_prev-u_flush_sp)*exp(-dt/tau_flush_valve)
Q_flush = Cv_flush*u_flush*sqrt(max(water_pressure,0))*N_flush_open
P_flush_phys = max(water_pressure-k_flush_Q*Q_flush-k_flush_open*N_flush_open,0)
I_ring_motor_phys = I0_ring+kf_ring*f_ring+krho_ring*rho_slurry+kclog_ring_I*matrix_clog+kQ_ring*Q_feed/max(Q_ref,eps)
V_ring_motor_phys = grid_voltage-k_drop_ring*I_ring_motor_phys
```

测量输出：

```text
agg_mag_excit_current = meas(I_exc)
agg_mag_excit_voltage = meas(V_exc_phys)
agg_mag_coil_temp = meas(T_coil)
agg_mag_pulsation_freq = meas(f_pul)
agg_mag_ring_freq = meas(f_ring)
agg_mag_level = meas(L_mag)
agg_mag_tailings_valve1 = meas(u_tail)
agg_mag_tailings_valve2 = meas(u_tail_2)
agg_mag_blowdown_valve = meas(u_blowdown_phys)
agg_mag_flush_water_pressure = meas(P_flush_phys)
agg_mag_motor_current_rc = meas(I_ring_motor_phys)
agg_mag_motor_voltage_rc = meas(V_ring_motor_phys)
```

其中 `meas(x)` 必须按第 3 节测量方程展开。

### 10.3 塔磨 DCS 具体公式

```text
tau_cyc_pool = max(L_pool*A_pool/max(Q_pump_prev,eps),min_tau_cyc_pool)
C_feed_in = (M_mag_conc_solid+M_tm_discharge_solid_prev)/max(M_mag_conc_wet+M_tm_discharge_wet_prev+M_water_add,eps)
F325_feed_in = (M_mag_conc_solid*F325_mag_conc+M_tm_discharge_solid_prev*F325_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
Liberation_fe_feed_in = (M_mag_conc_solid*Liberation_fe_mag_conc+M_tm_discharge_solid_prev*Liberation_fe_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
Liberation_gangue_feed_in = (M_mag_conc_solid*Liberation_gangue_mag_conc+M_tm_discharge_solid_prev*Liberation_gangue_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
WI_feed_in = (M_mag_conc_solid*WI_mag_conc+M_tm_discharge_solid_prev*WI_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)
T_slurry_feed_in =
  (M_wet_mag_conc*Cp_slurry_mag*T_slurry_mag_conc
   + M_wet_tm_discharge*Cp_slurry_tm*T_slurry_discharge_prev)
  / max(M_wet_mag_conc*Cp_slurry_mag+M_wet_tm_discharge*Cp_slurry_tm,eps)

C_feed = C_feed_prev+(dt/max(tau_cyc_pool,eps))*(C_feed_in-C_feed_prev)
F325_feed = F325_feed_prev+(dt/max(tau_cyc_pool,eps))*(F325_feed_in-F325_feed_prev)
Liberation_fe_feed = Liberation_fe_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_fe_feed_in-Liberation_fe_feed_prev)
Liberation_gangue_feed = Liberation_gangue_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_gangue_feed_in-Liberation_gangue_feed_prev)
WI_feed = WI_feed_prev+(dt/max(tau_cyc_pool,eps))*(WI_feed_in-WI_feed_prev)
T_slurry_feed = T_slurry_feed_prev+(dt/max(tau_cyc_pool,eps))*(T_slurry_feed_in-T_slurry_feed_prev)

rho_feed = rho_slurry(C_feed,rho_solid_mix)
mu_feed = mu_slurry(C_feed,clay,f25,r_sil,T_slurry_feed)

dL_pool/dt = (Q_in+Q_return_sand+Q_water-Q_pump)/A_pool
P_cyc_lag = delay(P_cyc,L_pump_pressure)
f_pump_sp = clip(f0+K_L*(L_pool-L_sp)+K_P*(P_sp-P_cyc_lag)+K_Qff*Q_in,f_min,f_max)
f_pump = f_pump_sp+(f_pump_prev-f_pump_sp)*exp(-dt/tau_pump_act)
Q_pump = k_pump*f_pump*(1-exp(-max(L_pool,0)/max(L_min_safe,eps)))*health_pump
P_cyc = clip(kP*rho_feed*(Q_pump/max(N_cyc_on,1))^2,P_min,P_max)
I_pump_phys = I0_pump+kf_pump*f_pump^2+kQ_pump*Q_pump+krho_pump*rho_feed+kmu_pump*mu_feed+kP_pump*P_cyc

u_water_sp = clip(u_water_nom+K_C_water*(C_sp-C_feed)+K_L_water*(L_sp-L_pool),0,1)
u_water = u_water_sp+(u_water_prev-u_water_sp)*exp(-dt/tau_water_valve)
Q_water_phys = Cv_water*u_water*sqrt(max(water_pressure,0))

circulating_load_lag = delay(circulating_load,L_sand_control)
u_sand_sp = clip(u_sand_nom+K_C_sand*(C_sand-C_sand_sp)+K_CL_sand*(circulating_load_lag-CL_ref)+PRBS_sand,0,1)
u_sand = u_sand_sp+(u_sand_prev-u_sand_sp)*exp(-dt/tau_sand_valve)
Q_sand_water_phys = Cv_sand*u_sand*sqrt(max(water_pressure,0))

d50 = d50_ref*(P_ref/max(P_cyc,eps))^aP*(C_feed/C_ref)^aC*(mu_feed/mu_ref)^amu
alpha_ov = clip(
  sigmoid(kF*(F325_feed-F325_ref)+kP*(P_cyc-P_ref)-kC*(C_feed-C_ref)-kmu*(mu_feed-mu_ref)),
  0,1)

M_tm_overflow_solid = feed_solid*alpha_ov
M_tm_sand_solid = feed_solid-M_tm_overflow_solid
M_sand = M_tm_sand_solid
alpha_ov_water = clip(alpha_ov*k_water_split,0,1)
M_tm_overflow_water = feed_water*alpha_ov_water
M_tm_sand_water = feed_water-M_tm_overflow_water
Q_overflow = M_tm_overflow_solid/rho_solid_mix + M_tm_overflow_water/rho_water
rho_overflow = (M_tm_overflow_solid+M_tm_overflow_water)/max(Q_overflow,eps)
Q_tm_overflow = Q_overflow
rho_tm_overflow = rho_overflow
M_overflow = M_tm_overflow_solid

F325_overflow = clip(F325_feed*k_fine_enrich/max(alpha_ov,eps),F325_feed,1.0)
Liberation_fe_overflow = clip(Liberation_fe_feed*k_lib_fe_enrich,Liberation_fe_feed,1.0)
Liberation_gangue_overflow = clip(Liberation_gangue_feed*k_lib_g_enrich,Liberation_gangue_feed,1.0)
F325_sand = clip((F325_feed-F325_overflow*alpha_ov)/max(1-alpha_ov,eps),0,F325_feed)
Liberation_fe_sand = clip((Liberation_fe_feed-Liberation_fe_overflow*alpha_ov)/max(1-alpha_ov,eps),0,Liberation_fe_feed)
Liberation_gangue_sand = clip((Liberation_gangue_feed-Liberation_gangue_overflow*alpha_ov)/max(1-alpha_ov,eps),0,Liberation_gangue_feed)
T_slurry_overflow = T_slurry_feed-k_cool_cyc*max(T_slurry_feed-T_amb,0)
T_tm_overflow = T_slurry_overflow
T_slurry_sand = T_slurry_feed-k_cool_sand*max(T_slurry_feed-T_amb,0)
WI_sand = WI_feed

inst_circ_load = M_sand/max(M_overflow,eps)
circulating_load = clip(inst_circ_load,0.0,5.0)
M_mill_water_in = M_tm_sand_water+Q_sand_water_phys*rho_water
C_mill = M_sand/max(M_sand+M_mill_water_in,eps)
WI_mill = WI_sand
# WI_mill 必须来自泵池/旋流器 Stream 的时间传递，禁止直接读取入口边界 WI_i(t)。

grind_difficulty =
  kWI*(WI_mill-WI_ref)
  + kcoarse*(1-F325_sand)
  + kC*(C_mill-C_opt)^2
  + kmu*(mu_feed-mu_ref)
  + kCL*(circulating_load-CL_ref)
P_mech_ss = P_idle+P_media+kM*M_sand*(1+grind_difficulty)
P_mech = P_mech_ss+(P_mech_prev-P_mech_ss)*exp(-dt/tau_P)
I_tm_phys = P_mech/(sqrt(3)*V_motor*pf*eta)

E_spec = P_mech/max(M_sand,eps)
F325_discharge_inst = clip(F325_sand+kE*log1p(E_spec/max(WI_mill,eps))-k_over*f25,0,1)
Liberation_fe_discharge_inst = clip(Liberation_fe_sand+k_lib_fe*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_fe_sand),0,1)
Liberation_gangue_discharge_inst = clip(Liberation_gangue_sand+k_lib_g*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_gangue_sand),0,1)
delta_T_mill = P_mech*k_heat_conv/max(Q_pump*rho_feed*Cp_slurry,eps)
T_slurry_discharge_inst = T_slurry_sand+delta_T_mill-k_cool_pipe*max(T_slurry_sand-T_amb,0)
F325_discharge = F325_discharge_prev+(dt/max(tau_mill_residence,eps))*(F325_discharge_inst-F325_discharge_prev)
Liberation_fe_discharge = Liberation_fe_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_fe_discharge_inst-Liberation_fe_discharge_prev)
Liberation_gangue_discharge = Liberation_gangue_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_gangue_discharge_inst-Liberation_gangue_discharge_prev)
T_slurry_discharge = T_slurry_discharge_prev+(dt/max(tau_mill_residence,eps))*(T_slurry_discharge_inst-T_slurry_discharge_prev)
WI_discharge = WI_mill

f_oil_pump_sp = clip(f_oil_nom+K_oil_T*max(T_oil-T_oil_sp,0)+K_oil_P*(P_mech-P_ref)/max(P_ref,eps),f_oil_min,f_oil_max)
f_oil_pump = f_oil_pump_sp+(f_oil_pump_prev-f_oil_pump_sp)*exp(-dt/tau_oil_pump)
oil_flow = k_oil_pump*f_oil_pump*health_oil_pump
u_oil_cooler_sp = clip(u_oil_cooler_nom+K_cool_T*(T_oil-T_oil_sp),0,1)
u_oil_cooler = u_oil_cooler_sp+(u_oil_cooler_prev-u_oil_cooler_sp)*exp(-dt/tau_oil_cooler)
oil_cooling_flow = k_oil_cooler*u_oil_cooler*sqrt(max(cooling_water_pressure,0))
T_oil_ss = T_amb+kP_oil*P_mech-kcool_oil*oil_cooling_flow
T_oil = T_oil_ss+(T_oil_prev-T_oil_ss)*exp(-dt/tau_oil)
T_oil_out = T_oil-k_oil_delta*oil_flow+k_oil_heat*P_mech
T_bearing1 = T_amb+kbrg1*P_mech+kb_mu1*mu_feed+event_bearing1_fault*delta_fault
T_bearing2 = T_amb+kbrg2*P_mech+kb_mu2*mu_feed+event_bearing2_fault*delta_fault
T_stator_A_ss = T_amb+k_heat_A*I_tm_phys^2
T_stator_B_ss = T_amb+k_heat_B*I_tm_phys^2
T_stator_A = T_stator_A_prev+(dt/max(tau_thermal_A,eps))*(T_stator_A_ss-T_stator_A_prev)
T_stator_B = T_stator_B_prev+(dt/max(tau_thermal_B,eps))*(T_stator_B_ss-T_stator_B_prev)

dL_ov_pool/dt = (Q_overflow-Q_ov_pump)/A_ov_pool
f_ov_pump_sp = clip(f_ov_nom+K_ov_L*(L_ov_pool-L_ov_sp),f_ov_min,f_ov_max)
Q_ov_pump = k_ov*f_ov_pump_sp*sqrt(max(L_ov_pool,0))
I_ov_pump_phys = I0_ov+kf_ov*f_ov_pump_sp^2+kQ_ov*Q_ov_pump+krho_ov*rho_overflow
```

测量输出：

```text
agg_tm_cyclone_feed_pressure = meas(P_cyc)
agg_tm_cyclone_feed_flow = meas(Q_pump)
agg_tm_cyclone_pump_freq = meas(f_pump)
agg_tm_cyclone_pump_current = meas(I_pump_phys)
agg_tm_cyclone_pool_level = meas(L_pool)
agg_tm_cyclone_pool_valve_setpoint = meas(u_water_sp)
MC1_FET503_AI = meas(Q_water_phys)
agg_tm_cyclone_sand_valve_setpoint = meas(u_sand_sp)
agg_tm_cyclone_sand_valve_feedback = meas(u_sand)
agg_tm_cyclone_sand_water_flow = meas(Q_sand_water_phys)
agg_tm_motor_current = meas(I_tm_phys)
agg_tm_reducer_oil_temp = meas(T_oil)
agg_tm_reducer_outlet_temp = meas(T_oil_out)
MC1_TM204_HDZC_1_WD_AI = meas(T_bearing1)
MC1_TM206_HDZC_2_WD_AI = meas(T_bearing2)
MC1_TM204_ZDJ_DZ_A_WD_AI = meas(T_stator_A)
MC1_TM206_ZDJ_DZ_B_WD_AI = meas(T_stator_B)
agg_tm_cyclone_overflow_pool_level = meas(L_ov_pool)
agg_tm_overflow_pump_current = meas(I_ov_pump_phys)
```

### 10.4 浮选 DCS 具体公式

浮选控制器不能读取当前最终精矿品位。药剂和气量控制使用 `quality_proxy_s`、矿石难选性、泡沫状态和负荷：

```text
s in {1,2}
c in {cx1,cx2,cx3,jx,sx1,sx2,sx3}
k in {1,2,3}
b in {1,2}
j in {td_rough,td_clean,k6_rough,naoh,cao}
```

浮选前浓缩机：

```text
Q_NT_in_s = split_NT_s*Q_tm_overflow_delayed
M_NT_in_solid_s = split_NT_s*M_tm_overflow_solid_delayed
M_NT_in_water_s = split_NT_s*M_tm_overflow_water_delayed
T_NT_in_s = T_tm_overflow_delayed-k_cool_to_NT*max(T_tm_overflow_delayed-T_amb,0)

dM_NT_solid_s/dt = M_NT_in_solid_s-M_NT_under_solid_s-M_NT_over_solid_s
dV_NT_water_s/dt = Q_NT_in_water_s-Q_NT_under_water_s-Q_NT_over_water_s
L_NT_s = (M_NT_solid_s/rho_solid_mix_s+V_NT_water_s)/A_NT_s

C_under_sp_s = clip(C_NT_nom+Kbed_NT*(L_NT_s-L_NT_ref)+Kload_NT*(M_NT_in_solid_s-M_NT_ref),C_NT_min,C_NT_max)
C_under_s = C_under_sp_s+(C_under_s_prev-C_under_sp_s)*exp(-dt/tau_NT_C)
rho_under_s = rho_slurry(C_under_s,rho_solid_mix_s)
T_under_s = T_NT_in_s-k_cool_NT*max(T_NT_in_s-T_amb,0)
mu_under_s = mu_slurry(C_under_s,clay_s,f25_s,r_sil_s,T_under_s)

Q_NT_under_s = k_NT_under*u_NT_under_s*sqrt(max(L_NT_s,0))
M_NT_under_solid_s = Q_NT_under_s*rho_under_s*C_under_s
M_NT_under_water_s = Q_NT_under_s*rho_under_s*(1-C_under_s)
bed_mass_s = M_NT_solid_s-M_NT_solid_ref
I_NT_s = I0_NT+kM_NT*M_NT_under_solid_s+kmu_NT*mu_under_s+kbed_NT*max(bed_mass_s,0)
```

质量代理和难选性：

```text
quality_proxy_s =
  w_tm_lab*ffill_reported(lab_tm_overflow_tfe)
  + w_mag_lab*ffill_reported(lab_mag_mixed_conc_tfe)
  + w_load*standardize(agg_tm_motor_current_lag)
  + w_pressure*standardize(agg_tm_cyclone_feed_pressure_lag)
  + w_froth*standardize(mean_froth_h_lag)

floatability_difficulty =
  w_carb*r_carb
  + w_sil*r_sil
  + w_fine*f25
  + w_coarse*(1-F325)
  + w_low_lib*(1-Liberation_gangue)
  + w_density*abs(C-C_opt)
  + w_clay*clay
```

药剂：

```text
dose_need_TD_rough_s = d0_td_r+Kload_td*M_feed_solid_s+Kdiff_td*floatability_difficulty_s+Kfroth_td*(h_ref-mean_c(h_froth_lag_{s,c}))+operator_trim_td_s+PRBS_TD_s
dose_need_TD_clean_s = d0_td_c+Kproxy_td*(quality_proxy_ref-quality_proxy_s)+Kdiff_clean*floatability_difficulty_s+operator_trim_td_clean_s
dose_need_DF_K6_s = d0_k6+Kslime_k6*f25_s+Ksil_k6*r_sil_s+Kcarb_k6*r_carb_s+Kselect_k6*(selectivity_ref-selectivity_proxy_s)

dose_need_{s,td_rough}=dose_need_TD_rough_s
dose_need_{s,td_clean}=dose_need_TD_clean_s
dose_need_{s,k6_rough}=dose_need_DF_K6_s
f_{s,j}_sp = clip(a_freq_j+b_freq_j*dose_need_{s,j}*M_feed_solid_s,f_min_j,f_max_j)
f_{s,j} = f_{s,j}_sp+(f_{s,j}_prev-f_{s,j}_sp)*exp(-dt/tau_j_act)
Q_{s,j}_ml_s = max(k_pump_j*f_{s,j}*health_{s,j},0)
I_drug_j_phys_{s,j} = I0_j+kf_j*f_{s,j}+kvis_j*reagent_viscosity_{s,j}+kpress_j*reagent_supply_pressure_j

dose_TD_effective_s = dose_TD_effective_prev_s+(dt/max(tau_adsorption_TD_s,eps))*(dose_TD_s-dose_TD_effective_prev_s)
dose_DF_K6_effective_s = dose_DF_K6_effective_prev_s+(dt/max(tau_adsorption_K6_s,eps))*(dose_DF_K6_s-dose_DF_K6_effective_prev_s)
```

K6 药箱：

```text
dL_k6_s/dt = (Q_k6_refill_s-Q_k6_consumption_s)/A_k6
Q_k6_consumption_s = k_k6_pump*f_k6_rough_s
event_k6_refill_s = 1 if L_k6_s<L_refill_low else 0
Q_k6_refill_s = event_k6_refill_s*Q_refill_nom
```

pH：

```text
buffer_capacity_s=b0+b_carb*r_carb_s+b_sil*r_sil_s+b_clay*clay_s+b_C*C_s+b_flow*M_feed_solid_s
pH_sp_s=clip(pH_nom+Kcarb_sp*(r_carb_s-r_carb_ref)+Ksil_sp*(r_sil_s-r_sil_ref)+operator_trim_pH_s+PRBS_pH_s,pH_min,pH_max)
dose_need_naoh_s=d0_naoh+Kp_pH*(pH_sp_s-pH_lag_s)+Kbuf_naoh*buffer_capacity_s+Kflow_naoh*M_feed_solid_s
dose_need_cao_s=d0_cao+Kcarb_cao*r_carb_s+Ksil_cao*r_sil_s+Kbuf_cao*buffer_capacity_s
dose_need_{s,naoh}=dose_need_naoh_s
dose_need_{s,cao}=dose_need_cao_s
OH_effect_s=k_naoh_oh*dose_naoh_kg_t_s+k_cao_oh*dose_cao_kg_t_s
Ca2_effect_s=k_cao_ca*dose_cao_kg_t_s
pH_ss_s=pH_base+k_pH*log1p(OH_effect_s/max(buffer_capacity_s,eps))
pH_s=pH_ss_s+(pH_prev_s-pH_ss_s)*exp(-dt/tau_pH)
```

气量、鼓风机和泡沫：

```text
hydrophobic_load_{s,c}=M_froth_gangue_lag_{s,c}+M_froth_fe_sil_lag_{s,c}+M_froth_fe_carb_lag_{s,c}+k_fe_froth*(M_froth_fe_mag_lag_{s,c}+M_froth_fe_hem_lag_{s,c})
Q_air_sp_{s,c}=clip(Q_air_nom_c+Kh_c*(h_ref_c-h_froth_lag_{s,c})+Kload_c*(M_feed_solid_s-M_ref)+Khydro_c*(hydrophobic_load_{s,c}-hydro_ref_c)+Kdensity_c*(C_s-C_ref)+operator_trim_air_{s,c}+PRBS_air_{s,c},Q_air_min_c,Q_air_max_c)

P_header_sp = clip(P_header_nom+Kair_header*(sum_{s,c}(Q_air_sp_{s,c})-Q_air_total_ref)+Kvalve_header*(u_bv_ref-mean_{s,c}(u_bv_{s,c})),P_header_min,P_header_max)
Q_air_total = sum_{s,c}(Q_air_{s,c})
d(air_filter_fouling)/dt = k_dust*Q_air_total-event_filter_clean*cleaning_rate_filter
air_filter_fouling = clip(air_filter_fouling_prev+dt*d(air_filter_fouling)/dt,0,1)
header_resistance = R_header0*(1+k_header_dust*air_filter_fouling+k_header_valve*mean(1-u_bv))
blower_load_share_b = blower_on_b*blower_capacity_b/max(sum_b(blower_on_b*blower_capacity_b),eps)
Q_blower_b = blower_load_share_b*Q_air_total
blower_speed_sp_b = clip(speed_nom_b+KP_header_b*(P_header_sp-P_header)+KQ_blower_b*(Q_blower_b-Q_blower_ref_b),speed_min_b,speed_max_b)
blower_speed_b = blower_speed_sp_b+(blower_speed_prev_b-blower_speed_sp_b)*exp(-dt/tau_blower_speed_b)
P_blower_curve_b = clip(a_fan_b*blower_speed_b^2-b_fan_b*Q_blower_b^2, P_blower_pressure_min_b, P_blower_pressure_max_b)
P_header_ss = clip(weighted_mean_b(P_blower_curve_b, blower_load_share_b)-header_resistance*Q_air_total^2, P_header_min, P_header_max)
P_header = P_header_ss+(P_header_prev-P_header_ss)*exp(-dt/tau_header_pressure)
P_blower_pressure_b = clip(P_header+k_blower_discharge_drop_b*Q_blower_b^2, P_blower_pressure_min_b, P_blower_pressure_max_b)
DeltaP_blower_Pa_b = 1e6*max(P_blower_pressure_b-P_amb_pressure,0)
P_blower_shaft_kW_b = Q_blower_b*DeltaP_blower_Pa_b/max(eta_fan_b,eps)/1000
I_blower_phys_b = 1000*P_blower_shaft_kW_b/max(sqrt(3)*V_blower_b*pf_blower_b*eta_blower_motor_b,eps)

P_cell_{s,c}=P_amb_pressure+rho_slurry_s*g*L_cell_{s,c}/1e6+k_froth_pressure*h_froth_{s,c}
u_bv_sp_{s,c}=clip(k_air_valve_c*Q_air_sp_{s,c}/sqrt(max(P_header-P_cell_{s,c},eps)),0.1,0.9)
u_bv_{s,c}=u_bv_sp_{s,c}+(u_bv_prev_{s,c}-u_bv_sp_{s,c})*exp(-dt/tau_bv_c)
Q_air_{s,c}=C_orifice_c*u_bv_{s,c}*sqrt(max(P_header-P_cell_{s,c},0))
gas_holdup_{s,c}=clip(
  k_gas_c*Q_air_{s,c}*(1+k_mu_gas_c*max(mu_slurry_s-mu_ref,0)),
  0,gas_holdup_max_c)
L_cell_aerated_{s,c}=L_cell_{s,c}/max(1-gas_holdup_{s,c},eps)

scraper_speed_{s,c}=clip(
  scraper_nom_c+K_scrape_P_c*max(h_froth_{s,c}-h_scrape_ref_c,0),
  speed_min_c,speed_max_c)
froth_stability_{s,c}=s0_c+s_TD_c*dose_TD_effective_s+s_K6_c*dose_DF_K6_effective_s+s_f25_c*f25_s+s_C_c*C_s+s_Ca_c*Ca2_effect_s+s_lib_c*Liberation_gangue_s+s_clay_c*clay_s
h_ss_{s,c}=k_h_c*Q_air_{s,c}*hydrophobic_load_{s,c}*froth_stability_{s,c}/max(k_collapse_c+k_scrape_c*scraper_speed_{s,c},eps)
h_froth_{s,c}=h_ss_{s,c}+(h_froth_prev_{s,c}-h_ss_{s,c})*exp(-dt/tau_froth_c)
```

液位、泵池、流量：

```text
Q_in_cell_{s,cx1}=Q_feed_s
Q_in_cell_{s,cx2}=Q_out_cell_{s,cx1}
Q_in_cell_{s,cx3}=Q_out_cell_{s,cx2}
Q_in_cell_{s,jx}=Q_rougher_froth_s
Q_in_cell_{s,sx1}=Q_rougher_tail_s
Q_in_cell_{s,sx2}=Q_scav1_tail_s
Q_in_cell_{s,sx3}=Q_scav2_tail_s

u_lv_sp_{s,c}=clip(u0_c+Kp_L_c*(L_sp_c-L_cell_aerated_lag_{s,c})+Ki_L_c*int_L_error_{s,c},0,1)
u_lv_fb_{s,c}=u_lv_sp_{s,c}+(u_lv_fb_prev_{s,c}-u_lv_sp_{s,c})*exp(-dt/tau_lv_c)
Q_out_cell_{s,c}=Cv_lv_c*u_lv_fb_{s,c}*sqrt(max(L_cell_{s,c},0))
V_pulp_actual_{s,c}=A_cell_c*max(L_cell_{s,c},0)
tau_stage_h_{s,c}=V_pulp_actual_{s,c}/max(Q_out_cell_{s,c},eps)
lip_clearance_{s,c}=L_cell_{s,c}+h_froth_{s,c}-H_lip_reference_c
R_froth_zone_{s,c}=clip(
  sigmoid(k_lip_c*lip_clearance_{s,c})*h_froth_{s,c}/max(h_froth_target_c,eps),
  0,1)

E_collector_{s,c}=sigmoid(a1_c*(dose_TD_effective_s-dose_low_c))*sigmoid(a2_c*(dose_high_c-dose_TD_effective_s))
E_depressant_{s,c}=sigmoid(kK6_c*(dose_DF_K6_effective_s-dose_K6_ref_c))
E_pH_{s,c}=exp(-((pH_s-pH_opt_c)/sigma_pH_c)^2)
E_air_{s,c}=sigmoid(k1_c*(Q_air_{s,c}-Q_air_low_c))*sigmoid(k2_c*(Q_air_high_c-Q_air_{s,c}))
E_density_{s,c}=exp(-((C_s-C_opt_c)/sigma_C_c)^2)
E_size_{s,c}=sigmoid(k_size_c*(F325_s-F325_min_c))
E_lib_g_{s,c}=0.25+0.75*Liberation_gangue_s
E_mu_{s,c}=exp(-k_mu_float_c*(mu_slurry_s-mu_ref))
entrainment_factor_{s,c}=e0_c+e_f25_c*f25_s+e_clay_c*clay_s+e_C_c*C_s+e_mu_c*max(mu_slurry_s-mu_ref,0)

k_float_gangue_{s,c}=k0_g_c*E_collector_{s,c}*E_pH_{s,c}*E_air_{s,c}*E_density_{s,c}*E_size_{s,c}*E_lib_g_{s,c}*E_mu_{s,c}
k_float_sil_{s,c}=k_float_gangue_{s,c}*(1+a_sil_c*r_sil_s)*E_Ca2_sil_s
k_float_carb_{s,c}=k_float_gangue_{s,c}*(1+a_carb_c*r_carb_s)*E_Ca2_carb_s
k_float_fe_mag_{s,c}=k0_mag_c*(1-E_depressant_{s,c})*entrainment_factor_{s,c}
k_float_fe_hem_{s,c}=k0_hem_c*(1-E_depressant_{s,c})*entrainment_factor_{s,c}

for j in {gangue,fe_sil,fe_carb,fe_mag,fe_hem}:
  grade_cell_j_{s,c}=M_cell_j_prev_{s,c}/max(M_cell_solid_prev_{s,c},eps)
  Q_out_solid_{s,c}=Q_out_cell_{s,c}*rho_slurry_s*C_s
  R_j_{s,c}=clip(1-exp(-k_float_j_{s,c}*tau_stage_h_{s,c}),0,Rmax_j_c)*R_froth_zone_{s,c}
  froth_j_rate_{s,c}=R_j_{s,c}*M_cell_j_prev_{s,c}/max(tau_stage_h_{s,c},eps)+entrainment_j_rate_{s,c}
  tail_j_rate_{s,c}=Q_out_solid_{s,c}*grade_cell_j_{s,c}
  dM_cell_j_{s,c}/dt=feed_j_rate_{s,c}-froth_j_rate_{s,c}-tail_j_rate_{s,c}
  M_cell_j_{s,c}=M_cell_j_prev_{s,c}+dt*dM_cell_j_{s,c}/dt
  froth_j_{s,c}=froth_j_rate_{s,c}*dt
  tail_j_{s,c}=tail_j_rate_{s,c}*dt

Q_froth_cell_{s,c}=sum_j(froth_j_{s,c})/max(rho_froth_mix_{s,c},eps)
dL_cell_{s,c}/dt=(Q_in_cell_{s,c}-Q_out_cell_{s,c}-Q_froth_cell_{s,c})/A_cell_c

M_feed_sp=clip(M_feed_nom-KWI_feed*(WI-WI_ref)-Ktm_feed*(I_tm_phys-I_tm_ref)-Kfroth_feed*max(h_froth-h_high,0)-Kpool_feed*max(L_pool-L_high,0)+operator_trim_feed+PRBS_feed_rate,M_feed_min,M_feed_max)
Q_feed_meter_phys = slurry_flow_from_mass(M_feed_sp,C,rho_slurry)
split_s1_total = clip(split_s1_nom+Ksplit_s1*(L_pool_s2-L_pool_s1)+operator_trim_split_s1,0.35,0.65)
Q_feed_s1_total = split_s1_total*Q_feed_meter_phys
Q_feed_s2_total = (1-split_s1_total)*Q_feed_meter_phys
split_s1_meter1 = clip(split_meter_nom+Kpipe_s1*(pipe_resistance_s1_2-pipe_resistance_s1_1)+N(0,sigma_split_meter),0.40,0.60)
split_s2_meter1 = clip(split_meter_nom+Kpipe_s2*(pipe_resistance_s2_2-pipe_resistance_s2_1)+N(0,sigma_split_meter),0.40,0.60)
Q_ft_s1_1701_phys = Q_feed_s1_total*split_s1_meter1
Q_ft_s1_1702_phys = Q_feed_s1_total*(1-split_s1_meter1)
Q_ft_s2_2701_phys = Q_feed_s2_total*split_s2_meter1
Q_ft_s2_2702_phys = Q_feed_s2_total*(1-split_s2_meter1)

Q_in_pool_{s,1}=Q_cleaner_tail_s+Q_scav1_conc_s
Q_in_pool_{s,2}=Q_scav2_conc_s+Q_scav3_conc_s
Q_in_pool_{s,3}=Q_final_tail_s
dL_pool_{s,k}/dt=(Q_in_pool_{s,k}-Q_pump_pool_{s,k})/A_pool_k
f_pool_sp_{s,k}=clip(f_pool_nom_k+Kpool_L_k*(L_pool_{s,k}-L_pool_sp_k),f_pool_min_k,f_pool_max_k)
f_pool_{s,k}=f_pool_sp_{s,k}+(f_pool_prev_{s,k}-f_pool_sp_{s,k})*exp(-dt/tau_pool_pump_k)
Q_pump_pool_{s,k}=k_pool_pump_k*f_pool_{s,k}*sqrt(max(L_pool_{s,k},0))*health_pool_pump_{s,k}
I_pool_phys_{s,k}=I0_pool_k+kf_pool_k*f_pool_{s,k}^2+kQ_pool_k*Q_pump_pool_{s,k}+krho_pool_k*rho_slurry_s+kmu_pool_k*mu_slurry_s+kH_pool_k*H_pool_k
```

温度、蒸汽和功率：

```text
reagent_viscosity_{s,j}=mu_reagent0_j*exp(kT_reagent_j*(T_ref-T_tank_{s,tank_of(j)}))
u_steam_sp_{s,k}=clip(u_steam_nom_k+KT_steam_k*(T_tank_sp_k-T_tank_{s,k}),0,1)
u_steam_fb_{s,k}=u_steam_sp_{s,k}+(u_steam_fb_prev_{s,k}-u_steam_sp_{s,k})*exp(-dt/tau_steam_k)
reagent_heat_load_{s,k}=sum_j(tank_map_{k,j}*Q_{s,j}_ml_s*Cp_reagent_j*(T_reagent_in_j-T_tank_{s,k}))
I_mixer_phys_{s,k}=I_idle_mixer_k+k_C_mixer_k*C_s+k_mu_mixer_k*mu_slurry_s
mixer_power_{s,k}=sqrt(3)*V_mixer_k*I_mixer_phys_{s,k}*pf_mixer_k*eta_mixer_k/1000
T_tank_ss_{s,k}=T_amb+ksteam_k*u_steam_fb_{s,k}+kreagent_k*reagent_heat_load_{s,k}+kmix_tank_k*mixer_power_{s,k}-kloss_tank_k*(T_tank_{s,k}-T_amb)
T_tank_{s,k}=T_tank_ss_{s,k}+(T_tank_prev_{s,k}-T_tank_ss_{s,k})*exp(-dt/tau_tank_k)

I_cell_motor_phys_{s,c}=I0_cell_c+krho_cell_c*rho_slurry_s+kmu_cell_c*mu_slurry_s+kair_cell_c*Q_air_{s,c}+kload_cell_c*M_solid_s
P_cell_motor_{s,c}=sqrt(3)*V_cell_motor*I_cell_motor_phys_{s,c}*pf_cell*eta_cell/1000
P_pool_pump_{s,k}=sqrt(3)*V_pool_pump*I_pool_phys_{s,k}*pf_pool*eta_pool/1000
P_drug_pump_{s,j}=sqrt(3)*V_drug_pump*I_drug_j_phys_{s,j}*pf_drug*eta_drug/1000
P_blower_power_b=sqrt(3)*V_blower_b*I_blower_phys_b*pf_blower_b/1000
P_blower_power_total=sum_b(P_blower_power_b)
blower_power_share1 = P_blower_power_total*Q_air_total_s1/max(Q_air_total,eps)
blower_power_share2 = P_blower_power_total*Q_air_total_s2/max(Q_air_total,eps)
sum_cell_power_s1=sum_c(P_cell_motor_{1,c})
sum_cell_power_s2=sum_c(P_cell_motor_{2,c})
sum_pool_power_s1=sum_k(P_pool_pump_{1,k})
sum_pool_power_s2=sum_k(P_pool_pump_{2,k})
sum_drug_power_s1=sum_j(P_drug_pump_{1,j})
sum_drug_power_s2=sum_j(P_drug_pump_{2,j})
P_aux_series1 = 50.0
P_aux_series2 = 50.0
P_series1=sum_cell_power_s1+sum_pool_power_s1+sum_drug_power_s1+blower_power_share1+P_aux_series1
P_series2=sum_cell_power_s2+sum_pool_power_s2+sum_drug_power_s2+blower_power_share2+P_aux_series2
```

测量输出：

```text
fx_s{s}_{c}_froth_h=meas(h_froth_{s,c}) unless event_froth_fault_{s,c}=1
fx_s{s}_{c}_level=meas(L_cell_aerated_{s,c})
fx_s{s}_{c}_level_valve_sp=meas(u_lv_sp_{s,c})
fx_s{s}_{c}_level_valve_fb=meas(u_lv_fb_{s,c})
fx_s{s}_{c}_air_flow=meas(Q_air_{s,c})
fx_s{s}_{c}_air_sp=meas(Q_air_sp_{s,c})
fx_s{s}_{c}_bv_pos=meas(u_bv_{s,c})
fx_s{s}_{c}_motor_curr=meas(I_cell_motor_phys_{s,c})
fx_s{s}_{drug}_freq=meas(f_{s,drug})
fx_s{s}_{drug}_curr=meas(I_drug_j_phys_{s,drug})
fx_s{s}_ph=meas(pH_s)
fx_s{s}_k6_level=meas(L_k6_s)
fx_nt{s}_underflow_density=meas(rho_under_s)
fx_nt{s}_motor_current=meas(I_NT_s)
fx_blower{b}_pressure=meas(P_blower_pressure_b)
fx_s1_ft1701=meas(Q_ft_s1_1701_phys)
fx_s1_ft1702=meas(Q_ft_s1_1702_phys)
fx_s2_ft2701=meas(Q_ft_s2_2701_phys)
fx_s2_ft2702=meas(Q_ft_s2_2702_phys)
fx_s{s}_pool{k}_level=meas(L_pool_{s,k})
fx_s{s}_pool{k}_pump_freq=meas(f_pool_{s,k})
fx_s{s}_pool{k}_pump_curr=meas(I_pool_phys_{s,k})
fx_s{s}_tk{k}_temp=meas(T_tank_{s,k})
fx_s{s}_tk{k}_mixer_curr=meas(I_mixer_phys_{s,k})
fx_s{s}_tk{k}_steam_sp=meas(u_steam_sp_{s,k})
fx_s{s}_tk{k}_steam_fb=meas(u_steam_fb_{s,k})
fx_ah5_power=meas(P_series1)
fx_ah6_power=meas(P_series2)
```

所有 `meas` 必须按第 3 节测量方程展开，且故障事件必须保留 `event_*` 标志供正常窗口剔除。

## 11. 开环与闭环

闭环用于模拟真实生产：

```text
矿质变化 -> 控制需求 -> 控制设定 -> 执行器 -> 工艺响应 -> DCS
```

开环用于因果识别：

```text
PRBS_TD, PRBS_NaOH, PRBS_CaO, PRBS_air, PRBS_water, PRBS_feed_rate, PRBS_mag_I
```

开环扰动只能进入设定值或外生边界，不能直接进入标签。

## 12. 验收设计

### 11.1 因果路径验收

每次实现后必须做阶跃或 PRBS 检查：

```text
r_carb ↑ -> buffer_capacity ↑ -> NaOH/CaO 需求 ↑ -> pH/Ca2 变化 -> 脉石浮选速率变化 -> y 变化
r_sil ↑ -> DF_K6/CaO/泡沫负荷变化 -> froth_h/air/dose 变化 -> y 变化
WI ↑ -> 塔磨电流 ↑ -> F325/Liberation 滞后变化 -> 浮选响应 -> y 变化
clay ↑ -> mu_slurry ↑ -> 搅拌电流/泵电流 ↑ -> 分级/泡沫变化 -> y 变化
F325 ↓ -> TD/气量/泡沫/浮选速率响应 -> y 变化
M_feed ↑ -> 液位/泵频/气量/药剂需求/停留时间变化 -> y 变化
```

如果这些路径在 DCS 上不可检出，则实现失败。

### 11.2 模型分层验收

必须报告：

```text
DCS-only
DCS + allowed upstream lab
DCS + allowed upstream lab + lag window
upstream-lab-only
all-lab-only
single-variable leakage check
current-time vs lag-window
open-loop vs closed-loop
normal-window vs fault-window
persistence baseline
train/test drift
```

健康标准：

```text
DCS-only R2 不应长期为负，也不应接近 0.99
目标范围约 0.3-0.7，允许按场景调整
时间窗口应优于单时刻
allowed upstream lab 应提升性能
all-lab-only 若远强，必须确认不是 lab_flo 泄漏
任一单变量 R2 > 0.9 判定为疑似泄漏
```

### 11.3 DCS 观测链专项验收

```text
控制变量不得与矿质/负荷代理完全无关。
正常窗口泡沫高度不得被故障值主导。
塔磨电流必须对 WI/F325/返砂负荷有滞后响应。
浮选电机电流必须对 C/clay/f25/mu 有响应。
旋流器压力必须使用矿物组分密度。
药剂泵频必须对难选性和泡沫状态有响应。
pH 必须对 buffer_capacity 和 NaOH/CaO 响应。
```

## 13. 代码重构路线

### 阶段 1：补齐物料状态

```text
Stream 增加 rho_solid_mix, mu_slurry, buffer_capacity, hydrophobic_potential
所有模块使用组分密度计算矿浆密度
所有隐藏状态保留但不进入训练特征
```

### 阶段 2：磁选控制重写

```text
I_exc/f_pul/f_ring 不再 AR 漂移
由 r_mag, Liberation, F200/F325, clay, f25, load, matrix_clog 驱动
```

### 阶段 3：塔磨观测链增强

```text
P_mech/I_tm 加强 WI/F325/C/mu/返砂负荷路径
新增或显式输出 cyclone feed pressure
压力和密度使用矿物组分密度
```

### 阶段 4：浮选控制重写

```text
药剂/pH/气量/泡沫/液位/泵池全部按本文控制律重写
Liberation_gangue 进入浮选速率和泡沫稳定性
故障值与正常信号分离
```

### 阶段 5：评估和泄漏闸门

```text
实现自动化 causal path check
实现 feature catalog
实现 lab reported-time 特征生成
实现 forbidden column guard
```

## 14. 最终结论

本设计承认并修正旧系统的核心缺陷：旧系统让隐藏物料状态和 lab 承载了大部分质量信息，而 DCS 没有形成足够强、足够真实的因果观测链。

v4 的目标是让工厂真实存在的因果关系尽量被模拟：

```text
矿质变化不是只改变 hidden true value，
而是必须改变设备负荷、控制需求、执行器状态、泡沫、pH、电流、流量、液位等 DCS。
```

只有这样，生成数据才适合“基于因果推断的精矿品位软测量”。
