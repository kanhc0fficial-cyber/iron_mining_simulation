# 塔磨与三次分级段重新设计

版本：v0.1  
范围：混磁精矿进入三次分级、塔磨再磨、旋流器溢流进入浮选前浓缩的数学模型。

## 现有问题

现有塔磨段把混磁精品位延迟后直接传给浮选，粒度模型较弱：

```text
m_mag_delayed = delay(_x_m_mag)
g_mag_delayed = delay(_x_g_mag)
_x_g_ov = g_mag_delayed
_x_f325_ov = f325_ov_base + k_f325*(P_mech/P_rated) + noise
```

不足：

1. 塔磨只改变粒度，不改变解离度和浮选可选性。
2. 旋流器分级没有把给矿压力、开动台数、浓度、返砂比对粒度的影响完整表达出来。
3. 塔磨负荷、泵池液位、泵电流、给矿压力与最终品位相关性偏弱。
4. 工厂报告强调三次分级粒度、浓度、压力、处理量、开机台数波动对浮选有直接影响，现有公式体现不足。

## 工厂依据

- 混磁精矿进入三次旋流器分级，沉砂进塔磨再磨，塔磨排矿返回三次旋流器闭路。
- 三次分级溢流粒度 `-325目` 目标 90%-95%，工艺要求可按 `>=92.5%`。
- 调试期间三次分级溢流 `-325目` 为 83.65%-94.77%，平均 89.51%。
- 塔磨给矿 `-325目` 平均 55.18%，排矿平均 63.72%，提高 8.54 个百分点，低于设计预期。
- 给矿压力 0.01-0.25 MPa，处理量 550-1300 m3/h，旋流器开动台数 4-11 台，泵池液位不稳、泵喘气和泵电流偏高会影响稳定运行。

## 改动点

| 编号 | 改动点 | 原因 |
|---|---|---|
| T1 | 显式维护粒度分布 `F200/F325/f25/d80` | 支持过程化验和浮选可选性 |
| T2 | 塔磨磨矿速率由能量、负荷、浓度、可磨性共同决定 | 对应报告中处理量、浓度和可磨性影响 |
| T3 | 旋流器分级由压力、开台数、浓度、粒度决定 | 对应现场压力和开台数波动 |
| T4 | 返砂比闭路动态影响塔磨负荷 | 让泵流量、电流、功率与粒度形成滞后相关 |
| T5 | 输出浮给过程化验变量 | 支持后续浮选段和日常指标跟踪 |

## 输入状态

来自磁选：

```text
M_mag_solid
G_mag
Fe_mag/Fe_hem/Fe_carb/Fe_sil/Gangue
F325_mag
Liberation_mag
C_mag
WI
```

若短期实现仍只有 `_x_m_mag`、`_x_g_mag`，可先用经验分布补全组分，但推荐按磁选新设计传递隐藏组分。

## 单步数据流

每个仿真步按以下顺序更新，避免变量之间出现代数环：

```text
1. 读取延迟后的磁选混磁精矿 MagOut_delayed
2. 读取上一时刻塔磨排矿返回 TMReturn_delayed
3. 更新给矿泵池水固平衡和泵频
4. 计算旋流器给矿流量、浓度、压力、开动台数
5. 按分级公式拆分溢流和沉砂
6. 更新塔磨功率、排矿粒度、排矿返回缓冲
7. 计算进入浮选的溢流隐藏量
8. 生成塔磨/三次分级 DCS 与过程化验
```

核心状态向量：

```text
S_tm = {
  L_pool, f_pump, cavitation,
  N_cyc_on, P_cyc, alpha_over, circulating_load,
  d80_sand, F325_sand, d80_discharge, F325_discharge,
  C_feed, C_over, C_sand, C_mill,
  P_mech, T_bearing, T_stator, T_reducer
}
```

## 泵池与给矿稳定性

混磁精矿和旋流器沉砂返回进入给矿泵池：

```text
Q_mag_in = wet_volume(MagOut_delayed)
Q_sand_return = delay(Q_tm_discharge, tau_tm_return)

u_pool_water = clip(u0_water + Kp_water*(L_pool_sp - L_pool_meas), 0, 1)
Q_pool_water = C_v_water*u_pool_water*sqrt(max(P_water,0))

Q_pool_in = Q_mag_in + Q_sand_return + Q_pool_water
C_pool = (M_mag_solid + M_sand_return_solid) / max(M_mag_wet + M_sand_return_wet + water_mass(Q_pool_water), eps)

f_pump_sp = clip(f_pump0 + Kp_pump*(L_pool - L_pool_sp), f_pump_min, f_pump_max)
f_pump = ZOH(f_pump, f_pump_sp, tau_f_pump) + N(0,sigma_f_pump)

Q_pump = k_pump*f_pump*sqrt(max(L_pool,0))*(1 - k_cav_loss*cavitation)
dL_pool/dt = (Q_pool_in - Q_pump)/A_pool
L_pool,k+1 = clip(L_pool,k + dt*dL_pool/dt, 0, L_pool_max)
```

泵喘气/液位不稳状态：

```text
cavitation = sigmoid(k_cav*(L_cav_low - L_pool)) * sigmoid(k_Q*(Q_pump - Q_safe))
flow_instability = clip(a_L*abs(dL_pool/dt) + a_cav*cavitation + noise, 0, 1)
```

说明：`P_water` 由公共水压边界 `_x_d4` 或循环水压力状态给出，不从塔磨溢流品位反推。

## 旋流器组模型

开动组数和单组旋流器台数：

```text
N_cyc_need = ceil(Q_pump / Q_cyc_unit_target)
N_cyc_on_sp = clip(N_cyc_need + operator_margin, N_cyc_min, N_cyc_max)
N_cyc_on = rate_limited_integer(N_cyc_on_prev, N_cyc_on_sp, max_switch_per_step)
```

压力：

```text
rho_feed = slurry_density(C_pool)
q_unit = Q_pump / max(N_cyc_on,1)
P_cyc = clip(k_P*rho_feed*q_unit^2*(1 + k_nozzle*wear_or_block), P_min, P_max)
```

分级切割粒径：

```text
d50_c = d50_ref
      * (P_ref/max(P_cyc,P_min))^a_P
      * (C_feed/C_ref)^a_C
      * (1 + k_over*max(Q_pump/Q_cap - 1, 0))
      * (1 + k_inst*flow_instability)
```

进入溢流的粒级概率：

```text
P_over(d) = 1 / (1 + (d/d50_c)^sharpness)
```

用简化矩量表达：

```text
F325_feed = mixed_f325(MagOut_delayed, TMReturn_delayed)
d80_feed = mixed_d80(MagOut_delayed, TMReturn_delayed)

F325_over = clip(F325_feed
                 + k_class*(P_cyc-P_ref)
                 - k_C*(C_pool-C_ref)
                 - k_Q*max(Q_pump/Q_cap-1,0)
                 - k_inst*flow_instability,
                 0, 1)

alpha_over = clip(alpha0
                  + k_alpha_P*(P_cyc-P_ref)
                  - k_alpha_C*(C_pool-C_ref)
                  - k_alpha_d*(d80_feed-d80_ref)
                  - k_alpha_inst*flow_instability,
                  alpha_min, alpha_max)
```

## 塔磨磨矿模型

塔磨处理旋流器沉砂。先计算浓度、负荷与功率，再计算磨矿速率：

```text
M_sand_solid = (1 - alpha_over) * M_cyc_feed_solid
Q_sand = (1 - alpha_over) * Q_pump
Q_sand_water = C_v_sand*u_sand_water*sqrt(max(P_water,0))
C_mill = M_sand_solid / max(M_sand_solid + water_solid_equivalent(Q_sand_water), eps)

P_mech_ss = P0
          + k_M*M_sand_solid
          + k_WI*WI
          + k_C*(C_mill - C_opt)^2
          + k_fine*(1 - F325_sand)
          + k_inst*flow_instability

P_mech = ZOH(P_mech, clip(P_mech_ss, 0, P_rated*1.15), tau_power) + N(0,sigma_P)
E_spec = P_mech / max(M_sand_solid, eps)
rho_effect = exp(-((C_mill - C_mill_opt)/sigma_C_mill)^2)
load_effect = exp(-k_load*max(M_sand_solid/M_cap - 1, 0)^2)

k_grind = k0 * E_spec / max(WI, eps) * rho_effect * load_effect
```

粒度更新：

```text
d80_discharge = d80_sand * exp(-k_grind * tau_mill)
F325_discharge = rr_F325(d80_discharge)
Liberation_discharge = clip(Liberation_sand + k_lib*(F325_discharge - F325_sand), 0, 1)
```

温度和电流可继续沿用现有热模型，但输入应来自 `P_mech`、负荷和环境，而不是独立装饰噪声。

## 闭路质量平衡

旋流器溢流进入浮选前浓缩，沉砂进入塔磨：

```text
M_over_solid = alpha_over * M_cyc_feed_solid
M_sand_solid = (1 - alpha_over) * M_cyc_feed_solid

M_tm_discharge_solid(t+tau_mill) = M_sand_solid(t)
```

沉砂返回会提升泵池负荷：

```text
circulating_load = M_sand_solid / max(M_over_solid, eps)
```

校准目标：

- 返砂比约 2.12-5.00，可随压力、浓度、开台数波动。
- 溢流 `-325目` 平均约 89.51%，正常应覆盖 83.65%-94.77%。
- 良好工况下可达到 92%-95%。

## 品位与组分传递

塔磨和旋流器不应凭空改变总铁质量，但可以改变解离度和不同粒级中组分分布：

```text
Fe_j_over = split_by_classification(Fe_j_feed, size_distribution_j, P_over)
G_over = sum_j Fe_j_over / max(M_over_solid, eps)
```

若暂不建分组粒度，可近似：

```text
Fe_j_over = alpha_over_j * Fe_j_feed
alpha_over_j = alpha_over * (1 + k_j_size*(fineness_j - fineness_mean))
```

碳酸铁/硅酸铁在细粒中可能更易进入溢流，从而影响浮选。

## 输出

进入浮选：

```text
_x_m_ov = wet_mass(M_over_solid, C_over)
_x_g_ov = G_over
_x_f325_ov = F325_over
_x_liberation_ov = Liberation_over
_x_fe_carb_frac_ov = Fe_carb_over / max(sum_j Fe_j_over, eps)
_x_fe_sil_frac_ov = Fe_sil_over / max(sum_j Fe_j_over, eps)
_x_C_ov = C_over
```

过程化验：

```text
lab_tm_feed_f325
lab_tm_discharge_f325
lab_tm_overflow_f325
lab_tm_overflow_tfe
lab_tm_overflow_conc
lab_tm_sand_f325
```

## DCS 变量生成公式

塔磨 DCS 不从 `_x_g_ov` 或最终精矿品位反推。它们由流量、液位、浓度、压力、功率、负荷、温度状态生成。

### 给矿泵池与旋流器

```text
tm_pool_level = L_pool + b_L_pool + N(0,sigma_L_pool)
tm_cyclone_feed_flow = max(Q_pump + k_dL*dL_pool/dt + N(0,sigma_Q_feed), 0)
tm_cyclone_feed_pressure = P_cyc + b_P_cyc + N(0,sigma_P_cyc)
tm_cyclone_feed_density = rho_feed + N(0,sigma_rho_feed)
tm_cyclone_feed_conc = C_pool + N(0,sigma_C_feed)
tm_cyclone_open_count = N_cyc_on
tm_cyclone_pump_freq = f_pump + N(0,sigma_f_pump_dcs)
```

泵电流：

```text
H_pump = max(H0 - H1*Q_pump^2, 0)
P_pump = rho_feed*g*H_pump*Q_pump/max(eta_pump, eps)
I_pump = P_pump/(sqrt(3)*V_pump*cos_phi_pump)
       + k_cav_I*cavitation
       + k_inst_I*flow_instability

tm_cyclone_pump_current = I_pump + N(0,sigma_I_pump)
```

### 塔磨主机

```text
tm_motor_power = P_mech + N(0,sigma_P_dcs)
tm_motor_current = P_mech*1000/(sqrt(3)*V_line*cos_phi_motor) + N(0,sigma_I_motor)
tm_mill_feed_conc = C_mill + N(0,sigma_C_mill_dcs)
tm_sand_water_valve = u_sand_water + N(0,sigma_u)
```

温度：

```text
T_bearing_ss = T_amb + k_bearing*P_mech + k_load_T*max(M_sand_solid/M_cap-1,0)
T_bearing = ZOH(T_bearing, T_bearing_ss, tau_bearing) + N(0,sigma_T_state)
tm_bearing_temp = T_bearing + N(0,sigma_T_dcs)

I_motor_true = P_mech*1000/(sqrt(3)*V_line*cos_phi_motor)
T_stator_ss = T_coolant + k_stator*I_motor_true^2
T_stator = ZOH(T_stator, T_stator_ss, tau_stator)
tm_stator_temp = T_stator + N(0,sigma_T_dcs)

P_loss_red = P_mech*(1-eta_reducer)/max(eta_reducer, eps)
T_reducer_ss = T_amb + k_reducer*P_loss_red
T_reducer = ZOH(T_reducer, T_reducer_ss, tau_reducer)
tm_reducer_temp = T_reducer + N(0,sigma_T_dcs)
```

### 溢流泵池

```text
dL_ov/dt = (Q_over - Q_ov_pump)/A_ov_pool
Q_ov_pump = Q_ov_nom * 1[L_ov > L_ov_low]
L_ov,k+1 = clip(L_ov,k + dt*dL_ov/dt, 0, L_ov_max)

tm_overflow_pool_level = L_ov + N(0,sigma_L_ov)
tm_overflow_pump_current = I_ov0*1[L_ov>L_ov_low] + k_ov_Q*Q_ov_pump*rho_over + N(0,sigma_I_ov)
```

如果现有代码列名是 `agg_tm_*`，实现时只需把上面的语义变量映射回现有列名，例如：

```text
agg_tm_cyclone_feed_flow      <- tm_cyclone_feed_flow
agg_tm_cyclone_pump_current   <- tm_cyclone_pump_current
agg_tm_motor_current          <- tm_motor_current
```

## 泄漏约束

塔磨 DCS 变量如泵池液位、泵频、给矿压力、塔磨功率和电流可以通过负荷、粒度和浓度与最终品位相关，但不得由浮选精矿品位或 `_x_g_ov` 反向生成。
