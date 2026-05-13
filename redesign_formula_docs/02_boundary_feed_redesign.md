# 仿真入口边界与上游扰动重新设计

版本：v0.2  
范围：只设计进入本仿真系统的边界输入。破碎、一段球磨、二段球磨及其内部 DCS 不在本仿真范围内。  
边界含义：仿真从“破碎和球磨结果”开始，入口默认是给入弱磁前的二次分级溢流/二溢等价流。

## 关键修正

上一版把三条磨矿线、球磨能耗和球磨电流写得像内部仿真模块，这是不合适的。本版改为“边界发生器”：

- 不模拟破碎机、球磨机、一次/二次旋流器内部机理。
- 只生成它们已经作用后的结果：流量、浓度、粒度、TFe、矿物组成、可磨性/可选性代理。
- 如果需要 `1#二溢/2#二溢/3#二溢` 过程化验，只把它们视为入口边界的三路线样，不代表本系统仿真球磨设备。
- 上游扰动仍要有慢变、相关、批次性，因为真实矿石性质会持续影响磁选、塔磨和浮选。

## 入口数据流

```text
上游边界发生器
  -> 入口三路线 post_ball_line[i]
  -> 汇总为 mag_feed
  -> 磁选段
  -> 塔磨/三次分级
  -> 浮选
  -> 最终精矿与过程化验
```

入口三路线 `i=1..3` 的状态：

```text
M_wet_i      # 湿矿量，t/h
C_i          # 固体质量浓度，0-1
G_i          # TFe，0-1
F200_i       # -200目含量，0-1
F325_i       # -325目含量，0-1
f25_i        # -25um 细泥比例，0-1
d80_i        # 等价 d80，m
r_mag_i      # 磁铁矿铁占总铁比例
r_hem_i      # 赤褐铁矿铁占总铁比例
r_carb_i     # 碳酸铁中铁占总铁比例
r_sil_i      # 硅酸铁中铁占总铁比例
WI_i         # 下游再磨难度代理，不用于模拟球磨
clay_i       # 泥化/黏土代理
```

## 慢变矿石扰动

用慢变矿石状态驱动入口结果，而不是逐步独立白噪声：

```text
z_ore = [G_base, r_mag, r_hem, r_carb, r_sil, WI, clay]^T

若 U(0,1) < p_block_switch:
    z_target = draw_block()

z_ore,k+1 = z_ore,k + (dt/tau_blend)*(z_target - z_ore,k) + L_ore * eps_k
eps_k ~ N(0, I)
```

其中 `L_ore` 是相关扰动的 Cholesky 矩阵。建议相关方向：

- `G_base` 与 `r_mag` 可正相关。
- `r_carb`、`r_sil` 与浮选难度正相关。
- `WI` 高时下游塔磨更难磨，入口 `F200/F325` 可略低。
- `clay` 高时 `f25` 和夹带风险升高。

组分比例归一化：

```text
[r_mag, r_hem, r_carb, r_sil] = normalize_clip([r_mag_raw, r_hem_raw, r_carb_raw, r_sil_raw])
```

## 三路线入口公式

三路线只是边界结果，不代表内部球磨模型。每条线有共同扰动和线间偏差：

```text
a_i,k        = availability_i,k                         # 0/1 或 0-1
xi_M_c,k+1   = phi_Mc*xi_M_c,k + N(0,sigma_Mc)
xi_M_i,k+1   = phi_Mi*xi_M_i,k + N(0,sigma_Mi)
xi_G_i,k+1   = phi_Gi*xi_G_i,k + N(0,sigma_Gi)
xi_C_i,k+1   = phi_Ci*xi_C_i,k + N(0,sigma_Ci)

M_wet_i = a_i * clip(M_wet_nom_i + xi_M_c + xi_M_i, M_wet_min_i, M_wet_max_i)
C_i     = clip(C_nom + xi_C_i + k_C_load*(M_wet_i-M_wet_nom_i), C_min, C_max)
G_i     = clip(G_base + xi_G_i + k_G_mag*(r_mag-r_mag_ref) - k_G_dilute*clay, G_min, G_max)
```

固体和铁量：

```text
M_solid_i = M_wet_i * C_i
M_water_i = M_wet_i - M_solid_i
Fe_total_i = M_solid_i * G_i

Fe_mag_i  = Fe_total_i * r_mag_i
Fe_hem_i  = Fe_total_i * r_hem_i
Fe_carb_i = Fe_total_i * r_carb_i
Fe_sil_i  = Fe_total_i * r_sil_i
Gangue_i  = max(M_solid_i - Fe_total_i, 0)
```

## 粒度边界公式

入口粒度直接作为上游结果生成。推荐先生成 `F200_i`，再由 Rosin-Rammler 关系反算 `d80_i`，避免写成球磨内部能耗模型。

```text
eta_size_i,k+1 = phi_size*eta_size_i,k + N(0,sigma_size)

logit_F200_i = logit(F200_nom)
             - k_WI*(WI_i-WI_ref)
             - k_load_size*(M_wet_i-M_wet_nom_i)
             - k_clay_size*clay_i
             + eta_size_i

F200_i = clip(sigmoid(logit_F200_i), F200_min, F200_max)
```

等价粒度：

```text
d80_i = 75e-6 / max((-ln(1-F200_i))^(1/n_rr), eps)
F325_i = clip(1 - exp(-(45e-6/max(d80_i,d_min))^n_rr), 0, 1)
f25_i  = clip(1 - exp(-(25e-6/max(d80_i,d_min))^n_rr), 0, 1)
```

校准目标：

- 二溢/弱磁入口 `-200目` 通常在 75%-80% 左右，允许日常样出现 81%-83% 这样的偏细值。
- 二溢浓度可覆盖工厂报告中 19.06%-41.74% 的调试范围，均值可按 30%-34% 校准；若模拟设计良好工况，可收窄到 23%-27%。

## 汇总到磁选入口

```text
M_solid = sum_i M_solid_i
M_wet   = sum_i M_wet_i
Fe_j    = sum_i Fe_j_i, j in {mag, hem, carb, sil}
Fe_total = sum_j Fe_j
Gangue = sum_i Gangue_i

_x_m_ball = M_wet
_x_d1 = Fe_total / max(M_solid, eps)
_x_d2 = (Fe_carb + Fe_sil) / max(Fe_total, eps)
_x_d3 = WI_ref / max(weighted_mean(WI_i, M_solid_i), eps)
_x_d80_ball = weighted_mean(d80_i, M_solid_i)
_x_f25_ball = weighted_mean(f25_i, M_solid_i)
_x_rho_ball = slurry_density(M_solid, M_water)

_x_ball_fe_mag_frac  = Fe_mag  / max(Fe_total, eps)
_x_ball_fe_hem_frac  = Fe_hem  / max(Fe_total, eps)
_x_ball_fe_carb_frac = Fe_carb / max(Fe_total, eps)
_x_ball_fe_sil_frac  = Fe_sil  / max(Fe_total, eps)
_x_ball_f200 = weighted_mean(F200_i, M_solid_i)
_x_ball_f325 = weighted_mean(F325_i, M_solid_i)
_x_ball_C = M_solid / max(M_wet, eps)
```

说明：

- 变量名可暂时沿用 `_x_m_ball`、`_x_d80_ball` 等，以减少代码改动；但文档语义应理解为“仿真入口边界”，不是球磨仿真输出。
- 不应新增球磨电流、球磨功率等 DCS 输出，除非未来明确把球磨纳入仿真范围。

## 过程化验样点口径

图中的过程化验样点需要分成“已确认口径”和“待确认口径”。

### 默认已确认

根据工厂报告，“二次分级溢流产品给入弱磁”，因此 `二溢` 默认可映射为仿真入口边界：

```text
lab_1_eryi_f200 = 100*F200_1 + assay_noise
lab_1_eryi_tfe  = 100*G_1 + assay_noise
lab_2_eryi_f200 = 100*F200_2 + assay_noise
lab_2_eryi_tfe  = 100*G_2 + assay_noise
lab_3_eryi_f200 = 100*F200_3 + assay_noise
lab_3_eryi_tfe  = 100*G_3 + assay_noise
```

### 待确认

`粗细溢`、`29米1#`、`29米2#`、`29米3#`、`29米4#`、`38米` 的实际取样位置不能仅凭截图确定。设计上不强行绑定到球磨后或塔磨后，而是使用配置：

```text
lab_sample_point_map = {
  "cuxiyi": "boundary_mixed" | "tm_overflow" | "manual_disabled",
  "29m_1":  "tm_cyclone_group_1_overflow" | "manual_disabled",
  "29m_2":  "tm_cyclone_group_2_overflow" | "manual_disabled",
  "29m_3":  "tm_cyclone_group_3_overflow" | "manual_disabled",
  "29m_4":  "tm_cyclone_group_4_overflow" | "manual_disabled",
  "38m":    "tm_overflow_mixed" | "manual_disabled"
}
```

默认策略：

- 未确认前，输出这些列可以保留但填 `NaN`，或用 `lab_unverified_*` 前缀避免误用。
- 确认取样口后，再绑定到对应隐藏状态。

### 磁性铁、亚铁、碳酸铁

如果 `粗细溢` 映射到入口混合样：

```text
lab_cuxiyi_tfe = 100 * _x_d1 + noise
lab_cuxiyi_mag_fe = 100 * Fe_mag / max(M_solid, eps) + noise
lab_cuxiyi_carb_fe = 100 * Fe_carb / max(M_solid, eps) + noise
lab_cuxiyi_feo = 100 * (k_feo_mag*Fe_mag + k_feo_carb*Fe_carb) / max(M_solid, eps) + noise
```

如果映射到塔磨后，则同式使用塔磨溢流中的 `Fe_mag_ov`、`Fe_carb_ov`、`M_solid_ov`。

## 与后续模块的实现接口

边界发生器每步写入：

```text
BoundaryOut = {
  wet_mass, solid_mass, water_mass, concentration,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  TFe, F200, F325, f25, d80,
  WI, clay,
  line_states[1..3]
}
```

磁选段从 `BoundaryOut` 读取组分质量、浓度、粒度和矿石难度代理。塔磨和浮选不再需要猜测上游矿物组成。
