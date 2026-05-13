# 选矿仿真系统 v2 完整设计规格

版本：v2.0-draft  
定位：这是后续重构的唯一施工图。`redesign_formula_docs/00~06` 只作为推导和附录参考。  
目标：生成更接近真实工厂机理的 DCS 时序、过程化验时序和最终精矿品位标签，避免目标信息反写到 DCS 特征。

## 1. 结论与可行性

本设计可以实现，但不建议一次性“大爆炸式”替换全部代码。推荐按“入口边界 -> 物料流结构 -> 磁选 -> 塔磨 -> 浮选 -> 化验输出 -> 校准”的顺序分阶段重构。

可行性判断：

- 现有工程已经按 `DisturbanceLayer -> BallMillInput -> MagSepSystem -> TowerMillSystem -> FlotationSystem` 分层，天然适合逐层替换。
- 现有 `_x_*` 隐藏量和 DCS bus 机制可以保留，只需扩展隐藏状态和 writer。
- 复杂度主要来自“组分质量平衡”和“浮选回流”，可以先用段级 CSTR 和上一时刻回流实现，避免代数环。
- 过程化验不设置报出滞后，工程实现简单；只需要采样调度和噪声模型。

主要风险：

- 参数较多，需要分模块校准，不能只靠一次全局调参。
- 部分现场化验点位尚未确认，例如 `粗细溢`、`29米*`、`38米`，这些列应先配置为可禁用或待确认映射。
- 浮选段从系列级 TFe 公式升级为段级组分平衡后，短期内需要更多中间调试输出。

## 2. 仿真范围

本系统从破碎和球磨后的结果开始，不模拟破碎和球磨内部设备。

仿真范围：

```text
入口边界，默认等价于弱磁给矿/二次分级溢流结果
  -> 弱磁
  -> 强磁前浓缩
  -> 强磁
  -> 扫强磁
  -> 混磁精矿
  -> 三次分级与塔磨闭路
  -> 浮选前浓缩
  -> 一粗一精三扫反浮选
  -> 最终精矿、浮选尾矿、过程化验
```

明确不在仿真范围：

```text
破碎机内部
一段球磨内部
二段球磨内部
球磨 DCS
破碎/球磨设备电流、功率、轴承温度
```

因此，`1#二溢/2#二溢/3#二溢` 可以作为入口边界化验样输出，但不能解释为仿真内部球磨模型的结果。

## 3. 设计目标

### 3.1 数据集目标

生成三类数据：

1. DCS 过程变量：用于软测量特征。
2. 过程化验变量：用于流程状态跟踪、多任务标签、数据质检，不默认进入 DCS 特征。
3. 最终精矿品位标签：`y_fx_xin1/2`，不设置化验报出滞后。

### 3.2 机理目标

最终精矿品位应由以下路径共同决定：

```text
入口矿石性质、粒度、浓度、矿物组成
  -> 磁选回收和混磁精矿组成
  -> 塔磨解离、三次分级粒度、返砂负荷
  -> 浮选给矿浓度、粒度、药剂单耗、pH、气量、停留时间、回流
  -> 精选精矿 TFe
```

DCS 对品位的预测性应来自真实中间路径，例如：

```text
泵频/液位/压力/电流/气量/药剂频率
  -> 流量、浓度、停留时间、能耗、夹带、浮选速率
  -> 品位变化
```

禁止：

```text
最终品位或当前目标
  -> 反推出泡沫高度、液位、泵电流、加药量等 DCS 特征
```

## 4. 全局单位与工具函数

内部单位：

| 类别 | 内部单位 |
|---|---|
| 质量流量 | t/h |
| 体积流量 | m3/h |
| 品位、浓度、粒级含量 | 0-1 |
| 化验输出 | 百分数，0-100 |
| 时间步长 | `dt`，默认 60 s |

基础函数：

```text
clip(x,a,b)=min(max(x,a),b)
sigmoid(x)=1/(1+exp(-x))
ZOH(x, x_ss, tau)=x_ss + (x-x_ss)*exp(-dt/max(tau,eps))
```

矿浆换算：

```text
M_wet = M_solid / max(C, eps)
M_water = M_wet - M_solid
V_slurry = M_solid/rho_solid + M_water/rho_water
rho_slurry = M_wet / max(V_slurry, eps)
Q_slurry = V_slurry
```

品位：

```text
Fe_total = Fe_mag + Fe_hem + Fe_carb + Fe_sil
TFe = Fe_total / max(M_solid, eps)
```

粒度换算，Rosin-Rammler 简化：

```text
F(x; d80, n) = clip(1 - exp(-(x/max(d80,d_min))^n), 0, 1)
F200 = F(75e-6; d80, n_rr)
F325 = F(45e-6; d80, n_rr)
f25  = F(25e-6; d80, n_rr)
```

## 5. 核心数据结构

### 5.1 Stream

所有物料流都使用同一结构：

```text
Stream = {
  M_solid, M_water, C,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  TFe,
  F200, F325, f25, d80,
  Liberation,
  WI,
  clay
}
```

其中：

- `Fe_mag`：磁铁矿中铁质量。
- `Fe_hem`：赤褐铁矿中铁质量。
- `Fe_carb`：碳酸铁中铁质量。
- `Fe_sil`：硅酸铁中铁质量。
- `Gangue`：不含铁脉石质量。
- `Liberation`：解离度/可选性代理。
- `WI`：下游再磨难度代理，只影响塔磨和粒度，不代表仿真球磨内部。

### 5.2 模块输出

```text
BoundaryOut = {
  line[1..3]: Stream,
  mixed: Stream,
  water_pressure
}

MagOut = {
  wm_conc, wm_tail,
  hm_feed, hm_conc, hm_tail,
  sw_conc, sw_tail,
  mixed_conc,
  states,
  dcs
}

TMOut = {
  cyclone_feed, cyclone_overflow, cyclone_sand,
  tm_discharge,
  states,
  dcs
}

FloOut = {
  feed,
  rougher_conc, rougher_tail,
  cleaner_conc, cleaner_tail,
  scav1_conc, scav1_tail,
  scav2_conc, scav2_tail,
  scav3_conc, final_tail,
  y_fx_xin1, y_fx_xin2,
  states,
  dcs
}
```

## 6. 单步调度

```text
BoundaryGenerator.step(t)
MagSepSystem.step(BoundaryOut.mixed)
TowerMillSystem.step(MagOut.mixed_conc)
FlotationSystem.step(TMOut.cyclone_overflow)
ProcessLabSampler.step(BoundaryOut, MagOut, TMOut, FloOut)
Writer.step(DCS, lab_*, y_*)
```

时滞规则：

- 化验报出不设置滞后。
- 工艺物料可设置设备停留时间和段间时滞。
- 段间时滞使用环形缓冲，先写入还是先读取必须在代码中统一。推荐“先读取延迟值，再写入当前值”，语义更直观。

## 7. 入口边界发生器

### 7.1 慢变矿石状态

```text
z_ore = [G_base, r_mag, r_hem, r_carb, r_sil, WI, clay]^T

if U(0,1) < p_block_switch:
    z_target = draw_block()

z_ore,k+1 = z_ore,k + (dt/tau_blend)*(z_target-z_ore,k) + L_ore*eps
eps ~ N(0,I)
[r_mag,r_hem,r_carb,r_sil] = normalize_clip(...)
```

### 7.2 三路线入口

三路线是入口结果，不是球磨内部模型。

```text
a_i = availability_i
M_wet_i = a_i * clip(M_nom_i + xi_M_common + xi_M_i, M_min_i, M_max_i)
C_i = clip(C_nom + xi_C_i + k_C_load*(M_wet_i-M_nom_i), C_min, C_max)
G_i = clip(G_base + xi_G_i + k_G_mag*(r_mag-r_mag_ref) - k_G_clay*clay, G_min, G_max)
```

粒度：

```text
logit_F200_i = logit(F200_nom)
             - k_WI*(WI-WI_ref)
             - k_load_size*(M_wet_i-M_nom_i)
             - k_clay_size*clay
             + eta_size_i

F200_i = clip(sigmoid(logit_F200_i), F200_min, F200_max)
d80_i = 75e-6 / max((-ln(1-F200_i))^(1/n_rr), eps)
F325_i = F(45e-6; d80_i, n_rr)
f25_i = F(25e-6; d80_i, n_rr)
```

组分：

```text
M_solid_i = M_wet_i*C_i
M_water_i = M_wet_i-M_solid_i
Fe_total_i = M_solid_i*G_i
Fe_mag_i = Fe_total_i*r_mag_i
Fe_hem_i = Fe_total_i*r_hem_i
Fe_carb_i = Fe_total_i*r_carb_i
Fe_sil_i = Fe_total_i*r_sil_i
Gangue_i = max(M_solid_i-Fe_total_i,0)
```

汇总：

```text
BoundaryOut.mixed = mass_weighted_sum(line[1..3])
```

校准目标：

- 入口 TFe 约 30%-33%。
- 二溢 `-200目` 通常约 75%-80%，可出现 81%-83%。
- 入口浓度覆盖调试中的较宽波动，必要时按场景收窄。

## 8. 磁选段

### 8.1 弱磁

影响因子：

```text
E_C_wm = exp(-((C_feed-0.25)/sigma_C_wm)^2)
load_wm = Q_feed/max(N_wm_on*Q_wm_unit,eps)
E_load_wm = exp(-k_over*max(load_wm-1,0)^2)
maldist = clip(maldist0 + k_slime*f25 + k_C*max(C_feed-0.25,0) + noise, 0, 1)
E_dist_wm = 1-k_dist*maldist
E_lib = Liberation
```

回收：

```text
R_wm_mag  = clip(R0_wm_mag  * E_lib * E_C_wm * E_load_wm * E_dist_wm, 0, Rmax_wm_mag)
R_wm_hem  = clip(R0_wm_hem  * E_lib^a * E_C_wm * E_load_wm, 0, Rmax_wm_hem)
R_wm_carb = clip(R0_wm_carb * E_ent_wm, 0, Rmax_wm_carb)
R_wm_sil  = clip(R0_wm_sil  * E_ent_wm, 0, Rmax_wm_sil)
R_wm_gangue = E_ent_wm
```

分流：

```text
wm_conc_j = R_wm_j * feed_j
wm_tail_j = feed_j - wm_conc_j
```

### 8.2 强磁前浓缩

```text
dM_pre_solid/dt = M_wm_tail_solid - M_under_solid - M_over_solid
dV_pre_water/dt = Q_wm_tail_water - Q_under_water - Q_over_water
L_pre = (M_pre_solid/rho_solid + V_pre_water)/A_pre

f_under = clip(f0 + Kp*(L_pre-L_sp), f_min, f_max)
Q_under = k_under*f_under*sqrt(max(L_pre,0))

C_under_ss = clip(C_target + k_bed*(L_pre-L_ref) - k_Q*(Q_under-Q_ref), C_min, C_max)
C_under = ZOH(C_under, C_under_ss, tau_C_under)
hm_feed = thicken(wm_tail, C_under)
```

### 8.3 强磁

```text
B_raw = B_max*(1-exp(-I_exc/I_ref))
thermal_derate = clip(1-k_T*max(T_coil-T_ref,0), derate_min, 1)
B_eff = B_raw*thermal_derate

v_matrix = Q_hm_feed/max(N_hm_on*A_matrix*porosity,eps)
E_C_hm = exp(-((C_hm_feed-0.45)/sigma_C_hm)^2)
E_pulse = exp(-((f_pul-f_pul_opt)/sigma_pul)^2)
E_ring = exp(-((f_ring-f_ring_opt)/sigma_ring)^2)
E_level = sigmoid(k_L*(L_hm-L_low))
```

```text
capture_j = sigmoid(a0_j
                  + aB_j*log(B_eff/B_ref)
                  - av_j*log(v_matrix/v_ref)
                  + aL_j*log(Liberation/L_ref)
                  + aC_j*log(max(E_C_hm,eps)))

R_hm_j = clip(capture_j*E_pulse*E_ring*E_level*E_matrix, 0, Rmax_hm_j)
```

### 8.4 扫强磁

扫强磁使用同样形式，但浓度最佳点改为约 0.195，目标是进一步降低尾矿品位：

```text
E_C_sw = exp(-((C_sw_feed-0.195)/sigma_C_sw)^2)
R_sw_j = sigmoid(b0_j + bB_j*log(B_sw/B_ref) - bv_j*log(v_sw/v_ref)
                 + bC_j*log(max(E_C_sw,eps)) + bL_j*log(Liberation/L_ref))
```

### 8.5 混磁精矿

```text
mixed_conc = wm_conc + hm_conc + sw_conc
```

磁选 DCS：

```text
agg_mag_excit_current = I_exc + noise
agg_mag_excit_voltage = V_exc + noise
agg_mag_coil_temp = T_coil + noise
agg_mag_ring_freq = f_ring + noise
agg_mag_pulsation_freq = f_pul + noise
agg_mag_level = L_hm + noise
agg_mag_flush_water_pressure = P_flush + noise
agg_mag_motor_current_rc = I0 + k_Q*Q_hm_feed + k_C*C_hm_feed + k_ring*f_ring + k_clog*matrix_clog + noise
```

## 9. 塔磨与三次分级

### 9.1 泵池和旋流器

```text
pool_in = delay(mixed_conc) + delay(tm_discharge) + water
f_pump_sp = clip(f0 + Kp*(L_pool-L_sp), f_min, f_max)
f_pump = ZOH(f_pump, f_pump_sp, tau_f)
cavitation = sigmoid(k_cav*(L_low-L_pool))*sigmoid(k_Q*(Q_pump-Q_safe))
Q_pump = k_pump*f_pump*sqrt(max(L_pool,0))*(1-k_cav_loss*cavitation)
dL_pool/dt = (Q_pool_in-Q_pump)/A_pool
```

```text
N_cyc_on = rate_limited_integer(N_prev, ceil(Q_pump/Q_unit)+margin)
P_cyc = clip(k_P*rho_feed*(Q_pump/max(N_cyc_on,1))^2, P_min, P_max)

alpha_over = clip(alpha0
                  + k_Pa*(P_cyc-P_ref)
                  - k_Ca*(C_feed-C_ref)
                  - k_da*(d80_feed-d80_ref)
                  - k_inst*instability,
                  alpha_min, alpha_max)

F325_over = clip(F325_feed
                 + k_class*(P_cyc-P_ref)
                 - k_C*(C_feed-C_ref)
                 - k_Q*max(Q_pump/Q_cap-1,0)
                 - k_inst*instability,
                 0, 1)
```

### 9.2 塔磨

```text
M_sand = (1-alpha_over)*M_cyc_feed
C_mill = calc_mill_concentration(Q_sand, Q_sand_water)

P_mech_ss = P0 + k_M*M_sand + k_WI*WI + k_C*(C_mill-C_opt)^2 + k_fine*(1-F325_sand)
P_mech = ZOH(P_mech, clip(P_mech_ss,0,1.15*P_rated), tau_P)

E_spec = P_mech/max(M_sand,eps)
k_grind = k0*E_spec/max(WI,eps)*E_C_mill*E_load
d80_discharge = d80_sand*exp(-k_grind*tau_mill)
F325_discharge = F(45e-6; d80_discharge,n_rr)
Liberation_discharge = clip(Liberation_sand+k_lib*(F325_discharge-F325_sand),0,1)
```

塔磨 DCS：

```text
agg_tm_cyclone_feed_flow = Q_pump + k_dL*dL_pool/dt + noise
tm_cyclone_feed_pressure = P_cyc + noise
agg_tm_cyclone_pump_current = pump_current(Q_pump,rho_feed,cavitation) + noise
agg_tm_motor_current = P_mech*1000/(sqrt(3)*V*cos_phi) + noise
tm_bearing_temp = ZOH(T_bearing, T_amb+k_bearing*P_mech, tau_bearing) + noise
tm_stator_temp = ZOH(T_stator, T_coolant+k_stator*I_motor^2, tau_stator) + noise
```

## 10. 浮选段

第一版实现用段级 CSTR，不直接做 16 台或 18 台槽逐槽矿物平衡。

### 10.1 浮选前浓缩

```text
dM_NT_solid/dt = M_ov_solid - M_under_solid - M_over_solid
dV_NT_water/dt = Q_ov_water - Q_under_water - Q_over_water
L_NT = (M_NT_solid/rho_solid+V_NT_water)/A_NT

Q_under = k_under*f_under*sqrt(max(L_NT,0))
C_under_ss = clip(C_target + k_bed*(L_NT-L_ref) - k_Q*(Q_under-Q_ref), C_min, C_max)
C_under = ZOH(C_under,C_under_ss,tau_C)
flo_feed = split_to_series(thickened_stream,C_under)
```

### 10.2 药剂和 pH

```text
f_drug_j = ZOH(f_drug_j, f_drug_sp_j, tau_drug) + noise
Q_drug_j = max(k_pump_j*f_drug_j*health_j + noise, 0)
dose_j = Q_drug_j*rho_drug_j*active_j/max(M_feed_solid,eps)

alkalinity = k_naoh*dose_naoh + k_cao*dose_cao
buffer_capacity = b0 + b_carb*r_carb + b_sil*r_sil + b_C*C_under
pH_ss = pH_base + k_pH*log1p(alkalinity/max(buffer_capacity,eps))
pH = ZOH(pH,pH_ss,tau_pH) + noise
```

### 10.3 反浮选速率

```text
E_collector = sigmoid(a1*(dose_collector-dose_low))*sigmoid(a2*(dose_high-dose_collector))
E_pH = exp(-((pH-pH_opt)/sigma_pH)^2)
E_air = sigmoid(k1*(Q_air-Q_low))*sigmoid(k2*(Q_high-Q_air))
E_density = exp(-((C-C_opt)/sigma_C)^2)
E_size = sigmoid(k_size*(F325-F325_min))

k_float_gangue = k0_g*E_collector*E_pH*E_air*E_density*E_size
k_float_sil = k_float_gangue*(1+a_sil*r_sil)
k_float_carb = k_float_gangue*(1+a_carb*r_carb)
k_float_Fe = k0_Fe*(1-E_depressant(dose_starch))*entrainment_factor
```

停留时间和分流：

```text
tau_stage = V_stage/max(Q_stage,eps)
R_float_j = 1-exp(-k_float_j*tau_stage)
M_froth_j = R_float_j*M_feed_j + entrainment_j
M_tail_j = M_feed_j-M_froth_j
```

拓扑：

```text
rougher_feed = flo_feed + cleaner_tail_prev + scav1_conc_prev
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

### 10.4 泡沫与 DCS

泡沫高度：

```text
hydrophobic_load = M_froth_gangue + M_froth_sil + M_froth_carb + k_fe*M_froth_Fe
froth_stability = s0 + s_col*dose_collector + s_frother*dose_frother + s_slime*f25 + s_C*C
h_ss = k_h*Q_air*hydrophobic_load*froth_stability/max(k_collapse+k_scrape*omega,eps)
h_froth = ZOH(h_froth,clip(h_ss,0,h_max),tau_froth)
```

气量和鼓风机：

```text
Q_air = C_orifice*u_bv*sqrt(max(P_blower-P_cell,0))
P_blower = ZOH(P_blower, a0+a1*speed^2-a2*Q_air_total^2, tau_blower) + noise
```

浮选 DCS：

```text
fx_s*_ph = pH + noise
fx_s*_drug_*_freq = f_drug + noise
fx_s*_drug_*_current = I0 + k_f*f_drug + k_Q*Q_drug*rho_drug + noise
fx_s*_*_level = L_stage + noise
fx_s*_*_air_flow = Q_air + noise
fx_s*_*_froth_h = h_froth + noise
fx_s*_*_motor_current = I0 + k_rho*(rho-rho_ref) + k_mu*(mu-mu_ref) + k_air*Q_air + noise
fx_blower_pressure = P_blower + noise
```

最终标签：

```text
y_fx_xin_s = 100*TFe(cleaner_froth_s) + N(0,sigma_lab)
```

## 11. 过程化验

采样策略：

```text
if sample_time(var):
    lab_var = 100*true_fraction_at_sample_point + N(0,sigma_assay) + N(0,sigma_sampling)
else:
    lab_var = NaN
```

默认输出：

```text
入口边界:
lab_1_eryi_f200, lab_1_eryi_tfe
lab_2_eryi_f200, lab_2_eryi_tfe
lab_3_eryi_f200, lab_3_eryi_tfe

磁选:
lab_mag_wm_conc_tfe, lab_mag_wm_tail_tfe
lab_mag_hm_conc_tfe, lab_mag_hm_tail_tfe
lab_mag_sw_conc_tfe, lab_mag_sw_tail_tfe
lab_mag_mixed_conc_tfe
lab_mag_tube_conc_tfe, lab_mag_tube_yield

塔磨:
lab_tm_feed_f325, lab_tm_discharge_f325
lab_tm_overflow_f325, lab_tm_overflow_tfe, lab_tm_overflow_conc

浮选:
lab_flo_feed_tfe_s1/s2, lab_flo_feed_f325_s1/s2
lab_flo_conc_tfe_s1/s2, lab_flo_tail_tfe_s1/s2
lab_flo_rough_conc_tfe_s1/s2, lab_flo_rough_tail_tfe_s1/s2
lab_flo_clean_tail_tfe_s1/s2
lab_flo_scav1/2/3_conc_tfe_s1/s2
lab_flo_scav1/2_tail_tfe_s1/s2
lab_flo_final_conc_yield_s1/s2
lab_flo_final_conc_recovery_s1/s2
```

待确认点：

```text
lab_cuxiyi_*
lab_29m_*
lab_38m_*
```

默认 `NaN` 或 `manual_disabled`。确认取样口后再绑定到入口边界或塔磨溢流。

## 12. 代码重构路线

### 阶段 0：保留现状，增加基础结构

目标：

- 新增 `Stream` 辅助结构或等价字典工具。
- 新增组分质量计算工具。
- 新增过程化验 sampler 框架。
- 不改变现有 DCS 列含义。

验收：

- 旧测试仍通过。
- 新 sampler 在未接入时不影响输出。

### 阶段 1：入口边界替换

目标：

- 将现有 `DisturbanceLayer + BallMillInput` 语义收敛为 `BoundaryGenerator`。
- 保留旧 `_x_d1/_x_m_ball/_x_d80_ball` 等字段兼容下游。
- 增加三路线入口隐藏状态和 `lab_1/2/3_eryi_*`。

验收：

- 入口 TFe、浓度、F200 范围合理。
- 不出现球磨 DCS 输出。

### 阶段 2：磁选替换

目标：

- 磁选按组分质量平衡分流。
- 输出混磁精矿组分、TFe、浓度、粒度、解离度。
- DCS 继续保持现有列名，但公式改为设备状态驱动。

验收：

- 弱精、弱尾、强精、强尾、扫强精、扫强尾、混磁精均值接近报告目标。
- 磁选 DCS 与混磁品位呈滞后弱/中相关，而非直接反推。

### 阶段 3：塔磨替换

目标：

- 建立泵池、旋流器、返砂、塔磨功率和粒度闭路。
- 输出三次分级溢流组分和 F325。

验收：

- 溢流 `-325目` 平均约 89%-92%，能覆盖 83%-95%。
- 泵池液位、给矿压力、功率、电流与负荷/粒度相关。

### 阶段 4：浮选替换

目标：

- 用段级 CSTR 替代 `TFe_ss=f(g,Q,pH)`。
- 泡沫高度改由脉石浮出量、气量、药剂、刮泡生成。
- `y_fx_xin1/2` 来自精选泡沫 TFe。

验收：

- 浮给约 45%，浮精约 67%，浮尾随工况变化。
- 药剂频率、pH、泡沫高度单变量不应形成近乎直接的目标映射。

### 阶段 5：校准与泄漏检查

检查：

```text
corr(DCS(t), y(t)) 
corr(DCS(t-lag), y(t))
单变量模型 R2
多变量时间窗口模型 R2
lab_* 与 y 的关系
```

验收标准：

- 单个强代理变量不能压倒性预测最终品位。
- 多变量滞后窗口能比单时刻变量更好。
- 改变入口粒度、碳酸铁/硅酸铁、浓度时，最终精矿出现合理滞后响应。

## 13. 是否需要保留旧 redesign 文档

建议保留，但不作为实现依据：

- `DESIGN_V2_COMPLETE.md`：实现依据。
- `00~06`：推导依据、公式来源、讨论记录。

实现时如果 `DESIGN_V2_COMPLETE.md` 与其他 redesign 文档冲突，以本文为准。

