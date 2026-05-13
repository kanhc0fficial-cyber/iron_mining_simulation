# 全流程可实现数据流与公式总规格

版本：v0.1  
用途：把各模块的状态量、数据流、公式和输出约束串成一条可实现路线。本文是实现时的总入口，模块细节见 `00` 到 `04`。

## 仿真范围

本系统仿真范围：

```text
入口边界：破碎和球磨后的结果
  -> 弱磁
  -> 强磁前浓缩
  -> 强磁
  -> 扫强磁
  -> 混磁精矿
  -> 塔磨与三次分级
  -> 浮选前浓缩
  -> 一粗一精三扫反浮选
  -> 最终精矿/尾矿
```

不在范围内：

```text
破碎机内部
一段球磨内部
二段球磨内部
球磨 DCS
破碎/球磨设备电流、功率、轴承温度等
```

入口边界仍可输出 `二溢` 类过程化验，因为它是本系统的输入样，而不是本系统内部模拟出来的球磨结果。

## 全局单位约定

建议内部统一用：

```text
质量流量：t/h
体积流量：m3/h
品位/浓度/粒级含量：0-1
化验输出百分数：0-100
时间步长：dt，默认 60 s
```

换算：

```text
wet_mass = solid_mass / max(C_mass, eps)
water_mass = wet_mass - solid_mass
slurry_density = wet_mass / max(solid_mass/rho_solid + water_mass/rho_water, eps)
Q_slurry_m3h = wet_mass / max(slurry_density, eps)
```

## 全流程状态对象

```text
BoundaryOut = {
  line[1..3],
  M_solid, M_water, C, TFe,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  F200, F325, f25, d80, WI, clay
}

MagOut = {
  wm_conc, wm_tail,
  hm_feed, hm_conc, hm_tail,
  sw_conc, sw_tail,
  mixed_conc,
  states_mag
}

TMOut = {
  cyclone_overflow, cyclone_sand, tm_discharge,
  F325_over, liberation_over,
  states_tm
}

FloOut = {
  flo_feed,
  rougher_conc, rougher_tail,
  cleaner_conc, cleaner_tail,
  scav1_conc, scav1_tail,
  scav2_conc, scav2_tail,
  scav3_conc, final_tail,
  y_fx_xin1, y_fx_xin2,
  states_flo
}
```

每个物料对象统一包含：

```text
Stream = {
  M_solid, M_water, C,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  TFe, F200, F325, f25, d80, Liberation, WI, clay
}
```

总铁：

```text
Fe_total = Fe_mag + Fe_hem + Fe_carb + Fe_sil
TFe = Fe_total / max(M_solid, eps)
```

## 单步调度顺序

```text
1. BoundaryGenerator.step
2. MagSepSystem.step(BoundaryOut)
3. TowerMillSystem.step(MagOut.mixed_conc)
4. FlotationSystem.step(TMOut.cyclone_overflow)
5. ProcessLabSampler.step(BoundaryOut, MagOut, TMOut, FloOut)
6. DCSOutputAdapter.step(BoundaryOut, MagOut, TMOut, FloOut, lab_*, y_*)
7. Writer.step(DCSFrame, lab_*, y_*)
```

注意：

- `ProcessLabSampler` 不延迟报出化验；只按采样时刻写入。
- 工艺物料本身仍可以有设备停留时间和段间时滞。
- `lab_*` 默认不作为 DCS 特征。
- 工艺模块内部不读取最终 `agg_*` 聚合列。`agg_*` 只由 `DCSOutputAdapter` 在输出阶段生成，用于兼容旧列名和训练特征。

## 入口边界公式

见 `02_boundary_feed_redesign.md`。实现最低要求：

```text
BoundaryOut = generate_boundary_lines()
BoundaryOut.aggregate = mass_weighted_sum(line[1..3])
```

必须提供给磁选：

```text
M_solid, M_water, C, TFe,
Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
F200, F325, f25, d80, WI, clay
```

## 磁选公式主线

弱磁：

```text
R_wm_mag = clip(R0_wm_mag * E_lib * E_C_wm * E_load_wm * E_dist_wm, 0, Rmax_wm_mag)
R_wm_hem = clip(R0_wm_hem * E_lib^a * E_C_wm * E_load_wm, 0, Rmax_wm_hem)
R_wm_carb = clip(R0_wm_carb * E_ent_wm, 0, Rmax_wm_carb)
R_wm_sil = clip(R0_wm_sil * E_ent_wm, 0, Rmax_wm_sil)
```

强磁前浓缩：

```text
C_hm_feed = ZOH(C_hm_feed, C_hm_feed_ss(L_pre,Q_under,disturb), tau_C)
hm_feed = thicken(wm_tail, C_hm_feed)
```

强磁：

```text
B_eff = B_raw(I_exc) * thermal_derate(T_coil)
capture_j = sigmoid(a0_j + aB_j*log(B_eff/B_ref) - av_j*log(v/v_ref)
                    + aL_j*log(Liberation/L_ref) + aC_j*log(E_C_hm))
R_hm_j = capture_j * E_pulse * E_ring * E_level * E_matrix
```

扫强磁：

```text
R_sw_j = sigmoid(b0_j + bB_j*log(B_sw/B_ref) - bv_j*log(v_sw/v_ref)
                 + bC_j*log(E_C_sw) + bL_j*log(Liberation/L_ref))
```

混磁精矿：

```text
mixed_conc = wm_conc + hm_conc + sw_conc
```

## 塔磨公式主线

```text
pool_in = mixed_conc_delayed + tm_discharge_return + water
Q_pump = k_pump*f_pump*sqrt(L_pool)*(1-k_cav*cavitation)
P_cyc = k_P*rho_feed*(Q_pump/N_cyc_on)^2
alpha_over = f(P_cyc, C_feed, d80_feed, instability)
F325_over = f(F325_feed, P_cyc, C_feed, Q_pump, instability)

P_mech = ZOH(P_mech, P0+k_M*M_sand+k_WI*WI+k_C*(C_mill-C_opt)^2+k_fine*(1-F325_sand), tau_P)
k_grind = k0*(P_mech/M_sand)/WI*E_C*E_load
d80_discharge = d80_sand*exp(-k_grind*tau_mill)
```

塔磨内部状态由 `L_pool, f_pump, Q_pump, P_cyc, P_mech, temperatures` 等生成。最终 `agg_tm_*` DCS 列由 `DCSOutputAdapter` 读取这些状态后输出，详见 `03_tower_mill_redesign.md` 和 `07_dcs_output_aggregation_draft.md`。

## 浮选公式主线

```text
dose_j = Q_drug_j*rho_drug_j*active_j / max(M_feed_solid, eps)
pH = ZOH(pH, pH_base + k_pH*log1p(alkalinity/buffer_capacity), tau_pH)

k_float_gangue = k0_g * E_collector(dose_collector) * E_pH(pH) * E_air(Q_air) * E_size(F325) * E_density(C)
k_float_sil = k_float_gangue*(1+a_sil*r_sil)
k_float_carb = k_float_gangue*(1+a_carb*r_carb)
k_float_Fe = k0_Fe*(1-E_depressant(dose_starch))*entrainment_factor

R_float_j_stage = 1 - exp(-k_float_j_stage*tau_stage)
M_froth_j = R_float_j_stage*M_feed_j + entrainment_j
M_tail_j = M_feed_j - M_froth_j
```

最终精矿：

```text
final_conc = cleaner_froth
y_fx_xin_s = 100*TFe(final_conc_s) + N(0,sigma_lab)
```

不设置化验报出滞后；采样时刻以外可为 `NaN`。

## DCS 生成总原则

每个 DCS 变量必须满足：

```text
DCS = sensor(true_equipment_state, drift, noise, optional_fault)
```

其中 `true_equipment_state` 必须来自模块内部的设备/系列/段级状态，而不是已经聚合后的 `agg_*` 输出列。推荐的实现分层为：

```text
Process model:
  Stream + DeviceGroupState + FlotationSeriesState

Sensor model:
  sensor(device_state, drift, noise, fault)

DCSOutputAdapter:
  sensor values -> raw-like DCS columns / agg_* compatibility columns
```

`DCSOutputAdapter` 是单向的：它读工艺状态并写输出列，不把输出列回写给磁选、塔磨或浮选公式。

允许路径：

```text
矿石性质/粒度/浓度/流量
  -> 设备负荷/液位/气量/药剂单耗/停留时间
  -> 选别结果
  -> 最终品位
```

禁止路径：

```text
最终品位或过程化验品位
  -> 反推 DCS

最终 agg_* 聚合列
  -> 回流参与分选、分级、磨矿或浮选公式
```

因此，在机理公式中应使用：

```text
hm_unit[i].I_exc
sw_unit[i].I_exc
train[k].Q_feed
fx_series[s].stage[rougher].Q_air
```

而不是：

```text
agg_mag_excit_current
agg_tm_cyclone_feed_flow
agg_fx_air_flow
```

## 过程化验输出公式

```text
if sample_time(var):
    lab_var = 100*true_fraction_at_sample_point + N(0,sigma_assay) + N(0,sigma_sampling)
else:
    lab_var = NaN
```

待确认样点：

```text
if sample_point_map[var] == "manual_disabled":
    lab_var = NaN
else:
    lab_var = sample(mapped_stream)
```

## 是否达到设计目标的判断标准

实现后应检查：

1. 单变量 DCS 不应过强预测 `y_fx_xin1/2`，尤其是药剂频率、pH、泡沫高度。
2. 多变量时间窗口应能通过浓度、负荷、气量、药剂单耗、粒度和上游矿物组成间接预测品位。
3. 过程化验变量应能解释流程状态，但默认不进入 DCS 特征。
4. 磁选、塔磨、浮选的均值和波动范围应贴近工厂报告中的考查结果。
5. 改变上游碳酸铁/硅酸铁、粒度或浓度，应沿流程产生可解释滞后影响。
