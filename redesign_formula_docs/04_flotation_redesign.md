# 浮选段与最终精矿品位重新设计

版本：v0.1  
范围：新1#、新2#浮选系统的浮选前浓缩、加药、pH、粗选、精选、三段扫选、泡沫、泵池、电气变量、最终精矿和浮选过程化验。老浮选系统不进入本段机理仿真；若存在公用上游或公用药剂/水系统影响，只作为边界扰动或公用资源状态处理。

## 现有问题

现有最终精矿品位模型集中为：

```text
TFe_ss = f(g_ov_del, Q_TD, pH)
TFe_circuit = first_order(TFe_ss)
y_fx_xin = TFe_circuit + bias + lab_noise
```

并且泡沫高度用 `1 - TFe_circuit` 反推硅含量。这会导致：

1. 加药频率和 pH 成为最终品位的强直接代理。
2. 泡沫高度含有目标信息回写。
3. 浮选槽液位、泵池、鼓风机、温度、K6 液位等变量大多是装饰性相关。
4. 矿物组成、粒度、浓度、浮选时间、充气量、回流等工厂关键路径没有成为最终品位的主因。

## 工厂依据

- 浮选作业是一粗一精三扫的阴离子反浮选，选别效果受给矿性质、矿物组成、粒度、浮选药剂、浮选时间、浮选浓度、充气量等影响。
- 调试中考查了浮给、浮精、浮尾、粗精、粗尾、精尾、中矿、一扫精/尾、二扫精/尾、三扫精等流程样。
- 新系统浮给品位平均约 45.36%，浮精约 67.28%，浮尾约 29.14%。
- 浮选试验显示：碳酸铁和硅酸铁高、粒度粗、解离度低时，选别提质难度大；粒度较细、解离较好时，精矿品位可达 67.6% 左右。
- 闭路试验中不同药剂制度精矿品位接近，但尾矿品位和收率不同，说明药剂不是单调越多越好。

## 改动点

| 编号 | 改动点 | 原因 |
|---|---|---|
| F1 | 用槽级组分浓度状态替代系列级 `TFe_circuit` | 避免最终品位集中公式 |
| F2 | 浮选速率由药剂、pH、气量、粒度、浓度、矿物组成共同决定 | 符合工厂报告 |
| F3 | 建立一粗一精三扫和回流 | 支持流程样和滞后相关 |
| F4 | 泡沫高度由疏水脉石负荷、气量、起泡/捕收、刮泡和液位生成 | 去除品位反推泡沫 |
| F5 | 药剂按 g/t 给矿和浓度计算单耗 | 让处理量和泵频对品位产生间接影响 |
| F6 | 过程化验直接输出，无化验滞后 | 满足日常指标跟踪需求 |

## 输入状态

来自塔磨/浮选前浓缩：

```text
M_feed_solid
G_feed
F325_feed
Liberation_feed
C_feed
Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue
```

碳酸铁、硅酸铁和低解离度会增加浮选难度：

```text
difficulty = w_carb*r_carb + w_sil*r_sil + w_coarse*(1-F325_feed) + w_lowlib*(1-Liberation_feed)
```

## 单步数据流

为便于实现，第一版建议使用“段级 CSTR + 上一步回流”的顺序：

```text
1. 读取塔磨溢流延迟量 TMOverflow_delayed
2. 更新浮选前浓缩机水固平衡，得到浮选给矿
3. 按新1#、新2#系列分配给矿量和组分
4. 根据给矿量、药剂泵频率计算各药剂 g/t 单耗
5. 更新 pH、气量、液位、泡沫和泵池状态
6. 用上一时刻回流量组成 rougher_feed
7. 依次计算粗选、精选、一扫、二扫、三扫组分分配
8. 将本步回流写入回流缓冲，精选泡沫作为最终精矿
9. 生成系列/段级传感器状态
10. 由 `DCSOutputAdapter` 生成 DCS 输出列、过程化验和 `y_fx_xin1/2`
```

每个系列状态：

```text
S_flo_s = {
  NT_solid, NT_water, C_under,
  pH, dose_j,
  stage_inventory_j[rougher, cleaner, scav1, scav2, scav3],
  L_stage, h_froth_stage, Q_air_stage,
  recycle_cleaner_tail, recycle_scav1_conc, recycle_scav2_conc, recycle_scav3_conc,
  final_conc, final_tail
}
```

## 浮选前浓缩

浮选前浓缩应输出底流浓度和流量，而不是固定目标：

```text
dM_solid_NT/dt = M_ov_solid - M_under_solid - M_over_solid
dV_water_NT/dt = Q_ov_water - Q_under_water - Q_over_water
L_NT = (M_solid_NT/rho_solid + V_water_NT) / A_NT

C_under_ss = clip(C_under_target
                  + k_bed*(L_NT-L_ref)
                  - k_Q*(Q_under-Q_ref)
                  - k_inst*underflow_instability,
                  C_min, C_max)
C_under = ZOH(C_under, C_under_ss, tau_NT_C)

f_under_sp = clip(f_under0 + Kp_NT*(L_NT-L_NT_sp), f_under_min, f_under_max)
Q_under = k_under*f_under_sp*sqrt(max(L_NT,0))
M_under_solid = Q_under * rho_slurry(C_under) * C_under
```

进入浮选每系列：

```text
M_feed_solid_s = split_s * M_under_solid
Q_feed_s = slurry_flow(M_feed_solid_s, C_under)
```

DCS 浓缩机电流：

```text
I_NT = I0 + k_M*M_solid_NT + k_torque*C_under + k_bed*L_NT + noise
```

## 药剂单耗与 pH

药剂泵频率先转成流量，再转成 g/t 给矿：

```text
f_drug_j_sp = operator_or_controller(feed_rate=M_feed_solid_s,
                                     difficulty=difficulty,
                                     mode=scenario)
f_drug_j = ZOH(f_drug_j, f_drug_j_sp, tau_drug_pump) + N(0,sigma_f_drug)
Q_drug_j = max(k_pump_j * f_drug_j * health_j + N(0,sigma_Q_drug), 0)
dose_j = Q_drug_j * rho_drug_j * active_j / max(M_feed_solid_s, eps)
```

需要的主要药剂：

- NaOH：调 pH。
- 淀粉/抑制剂：抑制铁矿物。
- CaO：调浆和钙离子环境。
- 捕收剂：捕收硅酸盐/碳酸盐等脉石。
- K6 或其他药剂箱：按实际变量命名保留。

pH 用缓冲容量表达：

```text
alkalinity_in = k_naoh*dose_naoh + k_cao*dose_cao
buffer_capacity = b0 + b_carb*r_carb + b_sil*r_sil + b_C*C_under
pH_ss = pH_base + k_pH*log1p(alkalinity_in/max(buffer_capacity, eps))
pH = ZOH(pH, pH_ss, tau_pH) + noise
```

这样 pH 仍可预测浮选状态，但不再直接决定最终 TFe。

## 浮选槽级状态

每个槽维护：

```text
L_i, h_froth_i
M_water_i
M_Fe_mag_i, M_Fe_hem_i, M_Fe_carb_i, M_Fe_sil_i, M_gangue_i
C_i
```

每段槽可聚合成粗选、精选、一扫、二扫、三扫。为了实现难度可控，第一版可用“段级 CSTR”：

```text
stage in {rougher, cleaner, scav1, scav2, scav3}
```

段级入流组分用向量表示：

```text
X_stage = [Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue, Water]^T
```

## 反浮选速率

反浮选目标是让脉石/含硅碳酸盐进入泡沫，铁矿物留在槽底成为精矿。定义各组分进入泡沫的速率：

```text
k_float_gangue = k0_g
  * E_collector(dose_collector)
  * E_pH(pH)
  * E_air(Q_air)
  * E_froth(dose_frother)
  * E_size(F325_feed)
  * E_density(C_i)

k_float_sil = k_float_gangue * (1 + a_sil*r_sil)
k_float_carb = k_float_gangue * (1 + a_carb*r_carb)
k_float_Fe = k0_Fe
  * (1 - E_depressant(dose_starch))
  * entrainment_factor
```

非单调药剂效应：

```text
E_collector(dose) = sigmoid(a*(dose-dose_low)) * sigmoid(b*(dose_high-dose))
E_pH(pH) = exp(-((pH-pH_opt)/sigma_pH)^2)
E_air(Q_air) = sigmoid(k1*(Q_air-Q_low)) * sigmoid(k2*(Q_high-Q_air))
E_density(C) = exp(-((C-C_opt)/sigma_C)^2)
```

说明：

- 捕收剂不足时硅去除不够；过量时夹带、泡沫黏滞或选择性变差。
- pH 不在合适范围时，选择性下降。
- 气量不足浮不上，气量过大夹带铁矿物。
- 浓度过低浮选时间和碰撞效率差，过高黏度大、夹带重。

## 浮选时间和处理量

每段停留时间：

```text
tau_stage = V_stage * C_i / max(Q_stage, eps)
```

段回收概率：

```text
R_float_j_stage = 1 - exp(-k_float_j_stage * tau_stage)
```

处理量增大时，`tau_stage` 变短，粗尾/浮尾品位应升高；这对应工厂报告中处理量和运行台数影响浮选效果。

## 段级质量平衡

每段：

```text
entrainment_j = E_ent_stage * M_feed_j
E_ent_stage = clip(e0
                   * (Q_air_stage/Q_air_ref)^a_air
                   * (h_froth_stage/h_ref)^a_h
                   * (C_stage/C_ref)^a_C
                   * (1 + a_slime*f25),
                   0, E_ent_max)

M_froth_j = R_float_j_stage * M_feed_j + entrainment_j
M_tail_j = M_feed_j - M_froth_j
```

拓扑：

```text
rougher_feed = flotation_feed + cleaner_tail + scav1_conc
rougher_froth -> cleaner_feed
rougher_tail -> scav1_feed
cleaner_froth -> final_concentrate
cleaner_tail -> rougher_feed
scav1_froth -> rougher_feed
scav1_tail -> scav2_feed
scav2_froth -> scav1_feed or rougher_feed
scav2_tail -> scav3_feed
scav3_froth -> scav2_feed
scav3_tail -> final_tail
```

第一版实现可用上一步回流量作为本步输入，避免代数环；后续可用 Gauss-Seidel 迭代。

## 泡沫高度

泡沫不再由 `TFe_circuit` 反推。每槽泡沫生成：

```text
hydrophobic_load = M_froth_gangue + M_froth_sil + M_froth_carb + k_fe*M_froth_Fe
froth_stability = s0 + s_col*dose_collector + s_frother*dose_frother + s_slime*f25 + s_C*C_i

h_ss = k_h * Q_air * hydrophobic_load * froth_stability
       / max(k_collapse + k_scrape*omega_scraper + k_wash*wash_water, eps)

h_froth = ZOH(h_froth, clip(h_ss,0,h_max), tau_froth)
```

DCS 泡沫高度：

```text
fx_s*_cx*_froth_h = h_froth + sensor_noise + occasional_fault
```

这样泡沫高度通过浮选负荷和脉石浮出量与品位相关，但没有目标回写。

## 液位、阀门、泵池、鼓风机

液位影响停留时间和夹带：

```text
u_lv_sp_i = clip(u_lv0 + Kp_lv*(L_i-L_sp), 0, 1)
u_lv_i = ZOH(u_lv_i, u_lv_sp_i, tau_lv_act)
Q_pulp_out_i = C_v_lv*u_lv_i*sqrt(max(L_i,0))
Q_froth_water_i = k_fw*h_froth_i*Q_air_i

dL_i/dt = (Q_in_i - Q_pulp_out_i - Q_froth_water_i)/A_i
L_i,k+1 = clip(L_i,k + dt*dL_i/dt, 0, L_i_max)
entrainment_factor = e0 * Q_air^a * h_froth^b * (1 + k_L*max(L_i-L_ref,0))
```

鼓风机压力与气量：

```text
Q_air_i = C_orifice*u_bv_i*sqrt(max(P_blower - P_cell_i,0))
P_blower = blower_curve(speed_blower, sum(Q_air_i)) + noise
```

泵池：

```text
dL_pool/dt = (Q_in_pool - Q_pump_pool)/A_pool
Q_pump_pool = k_pump*f_pump*sqrt(max(L_pool,0))*(1-k_cav*cavitation)
```

这些 DCS 变量通过停留时间、气量、夹带和处理量间接影响品位。

## DCS 变量生成公式

浮选 DCS 变量不得从 `TFe_conc`、`y_fx_xin` 或任何过程化验品位反推。下列公式给出第一版可实现口径。

新增聚合口径：浮选内部不提前把新1#和新2#聚合，也不把槽段状态提前压成一个全厂 `agg_fx_*`。每个新系列先维护自己的浓缩、药剂、气量、液位、泡沫、泵池和段级组分状态；最终 DCS 列由 `DCSOutputAdapter` 输出。

推荐内部状态：

```text
series[s in {new1,new2}].feed_thickener
series[s].reagent_pump[NaOH, DF_K6, CaO, TD_rougher, TD_cleaner]
series[s].stage[rougher, cleaner, scav1, scav2, scav3]
series[s].sump[]
series[s].final_conc
series[s].final_tail
```

推荐输出适配：

```text
DCSOutputAdapter:
  fx_new1_feed_flow, fx_new2_feed_flow
  fx_new1_ph, fx_new2_ph
  fx_new1_naoh_pump_flow, fx_new2_naoh_pump_flow
  fx_new1_df_k6_pump_flow, fx_new2_df_k6_pump_flow
  fx_new1_cao_pump_flow, fx_new2_cao_pump_flow
  fx_new1_td_rougher_pump_flow, fx_new2_td_rougher_pump_flow
  fx_new1_td_cleaner_pump_flow, fx_new2_td_cleaner_pump_flow
```

具体是否再输出某些 `agg_fx_*` 兼容列，由输出适配层配置，不进入浮选速率公式。

### 加药系统

```text
fx_s{n}_drug_{j}_freq = f_drug_j + N(0,sigma_f_drug_dcs)
fx_s{n}_drug_{j}_current = I_drug0_j
                             + k_fI_j*f_drug_j
                             + k_QI_j*Q_drug_j*rho_drug_j
                             + N(0,sigma_I_drug)

L_k6,k+1 = clip(L_k6,k
                + dt*(Q_k6_fill - sum_s Q_drug_k6_s)/A_k6
                + N(0,sigma_L_k6_state),
                L_k6_min, L_k6_max)
fx_k6_level = L_k6 + N(0,sigma_L_k6_dcs)
```

### pH 和浮选前浓缩

```text
fx_s{n}_ph = pH_s + N(0,sigma_pH_dcs)
fx_s{n}_nt_underflow_conc = C_under_s + N(0,sigma_C_under_dcs)
fx_s{n}_nt_current = I_NT_s + N(0,sigma_I_NT_dcs)
```

### 浮选槽液位、阀门、气量和泡沫

```text
fx_s{n}_{stage}_level = L_stage + b_L_stage + N(0,sigma_L_stage)
fx_s{n}_{stage}_lv_valve = u_lv_stage + N(0,sigma_u_lv)
fx_s{n}_{stage}_butterfly_valve = u_bv_stage + N(0,sigma_u_bv)
fx_s{n}_{stage}_air_flow = Q_air_stage + N(0,sigma_Q_air_dcs)
fx_s{n}_{stage}_froth_h = h_froth_stage + N(0,sigma_h_froth)
```

泡沫高度的真实状态由脉石浮出量、气量、药剂和刮泡生成，不使用精矿品位：

```text
hydrophobic_load_stage = M_froth_gangue + M_froth_sil + M_froth_carb + k_fe*M_froth_Fe
h_froth_stage = ZOH(h_froth_stage, h_ss_stage, tau_froth)
```

### 浮选机电机、电力和温度

```text
rho_stage = slurry_density(C_stage)
mu_stage = mu0 * exp(k_mu_C*C_stage + k_mu_slime*f25)

I_FXJ_stage = I0_FXJ
            + k_rho_I*(rho_stage-rho_ref)
            + k_mu_I*(mu_stage-mu_ref)
            + k_air_I*Q_air_stage
            + N(0,sigma_I_FXJ)

fx_s{n}_{stage}_motor_current = I_FXJ_stage
```

搅拌/药剂槽温度：

```text
u_steam_sp = clip(u_steam0 + Kp_T*(T_sp - T_tank), 0, 1)
u_steam = ZOH(u_steam, u_steam_sp, tau_steam_act)
T_tank_ss = T_amb + k_steam*u_steam*(T_steam-T_tank) - k_loss*(T_tank-T_amb)
T_tank = ZOH(T_tank, T_tank_ss, tau_tank) + N(0,sigma_T_tank_state)

fx_s{n}_tank_temp = T_tank + N(0,sigma_T_tank_dcs)
fx_s{n}_steam_valve = u_steam + N(0,sigma_u_steam)
```

变压器/馈线功率：

```text
P_FXJ_total_s = sum_stage(I_FXJ_stage)*V_line*sqrt(3)*cos_phi/1000
P_pump_total_s = sum_pool(I_pool)*V_line*sqrt(3)*cos_phi/1000
fx_s{n}_active_power = P_FXJ_total_s + P_pump_total_s + N(0,sigma_P_active)
```

### 泵池和入矿流量

```text
f_pool_sp = clip(f_pool0 + Kp_pool*(L_pool-L_pool_sp), f_pool_min, f_pool_max)
f_pool = ZOH(f_pool, f_pool_sp, tau_pool_freq) + N(0,sigma_f_pool)
Q_pool_pump = k_pool*f_pool*sqrt(max(L_pool,0))*(1-k_cav_pool*cavitation_pool)
dL_pool/dt = (Q_pool_in-Q_pool_pump)/A_pool

fx_s{n}_pool_level = L_pool + N(0,sigma_L_pool)
fx_s{n}_pool_pump_freq = f_pool + N(0,sigma_f_pool_dcs)
fx_s{n}_pool_pump_current = I_pool0 + k_f_pool_I*f_pool^2 + k_cav_pool_I*cavitation_pool + N(0,sigma_I_pool)
fx_s{n}_feed_flow = Q_feed_s + N(0,sigma_Q_feed_dcs)
```

### 鼓风机

```text
Q_air_total = sum_s,sum_stage Q_air_stage
P_blower_ss = a0_blower + a1_blower*speed_blower^2 - a2_blower*Q_air_total^2
P_blower = ZOH(P_blower, P_blower_ss, tau_blower) + N(0,sigma_P_blower_state)

fx_blower_pressure = P_blower + N(0,sigma_P_blower_dcs)
fx_blower_current = I_blower0 + k_speed_I*speed_blower^2 + k_Qair_I*Q_air_total + N(0,sigma_I_blower)
```

## 最终精矿和标签

最终精矿来自精选泡沫：

```text
M_conc_solid = sum_j M_cleaner_froth_j
Fe_conc = Fe_mag + Fe_hem + Fe_carb + Fe_sil in cleaner_froth
TFe_conc = Fe_conc / max(M_conc_solid, eps)

y_fx_xin_s = TFe_conc_s + N(0, sigma_lab)
```

按用户要求，不设置化验报出滞后。采样间隔仍可保留：

```text
若 t 是最终精矿采样时刻:
    y_fx_xin_s = TFe_conc_s + lab_noise
否则:
    y_fx_xin_s = NaN
```

若需要完整连续真值，可另输出：

```text
_x_TFe_conc_true_s
```

## 浮选过程化验

按采样时刻直接输出：

```text
lab_flo_feed_tfe
lab_flo_feed_f325
lab_flo_conc_tfe
lab_flo_tail_tfe
lab_flo_rough_conc_tfe
lab_flo_rough_tail_tfe
lab_flo_clean_tail_tfe
lab_flo_scav1_conc_tfe
lab_flo_scav1_tail_tfe
lab_flo_scav2_conc_tfe
lab_flo_scav2_tail_tfe
lab_flo_scav3_conc_tfe
lab_flo_final_conc_yield
lab_flo_final_conc_recovery
```

校准目标：

- 新系统浮给均值约 45% 左右。
- 浮精均值约 67% 左右。
- 浮尾均值可按考查阶段落在 20%-30% 区间，并随药剂、粒度、处理量变化。
- 闭路试验中不同药剂条件可产生相近精矿品位，但尾矿品位和回收率不同。

## 泄漏与相关性检查

1. 泡沫高度、气量、液位、泵池、鼓风机、温度、K6 液位不得由 `TFe_conc` 反推。
2. 加药泵频率不能独自解释最终品位；它必须经 `dose_j = flow/feed_mass`、pH、速率和停留时间生效。
3. pH 可以是强过程变量，但不应与最终品位构成几乎单调的一步映射。
4. 粒度、碳酸铁、硅酸铁、解离度应显著影响浮选难度。
5. `lab_*` 变量可作为化验输出，但默认不进入 DCS 训练特征。
