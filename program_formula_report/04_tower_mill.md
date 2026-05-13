# 塔磨段数学关系

来源：`sim/layers/tower_mill.py`、`sim/config.py`、公共工具。

## 段间时滞

混磁精矿量和品位先写入缓冲，再取 `delay_steps` 步前值：

```text
m_mag_delayed = delay(_x_m_mag, delay_steps)
g_mag_delayed = delay(_x_g_mag, delay_steps)
```

塔磨沉砂返回也用缓冲：

```text
Q_sand_return = delay(Q_sand, tau_mill)
```

## 给矿泵池

磁精矿入池体积流量：

```text
Q_mag_in = m_mag_delayed*1000/3600/rho_slurry_mag
```

液位测量：

```text
b_pool,k = b_pool,k-1 + N(0,sigma_b_pool)
L_meas = L_pool + b_pool,k + N(0,sigma_L_pool)
L_meas_clipped = clip(L_meas, 0, 10)
```

泵频率目标和一阶跟踪：

```text
f_target = clip(f_pump_nom + k_fb_pump*(L_pool - L_pool_setpoint), f_pump_min, f_pump_max)
f_pump,k = phi_f_pump*f_pump,k-1 + (1-phi_f_pump)*f_target + N(0,sigma_eta_f)
f_pump,k = clip(f_pump,k, f_pump_min, f_pump_max)
```

泵排量：

```text
Q_pump = k_pump*f_pump*sqrt(max(L_pool,0))
```

泵池补水阀和补水：

```text
u_pool_sp = clip(u_pool_mean + k_pool_pid*(L_pool_setpoint - L_meas_clipped), 0, 1)
Q_pool_water = max(C_v_pool*u_pool_sp*sqrt(max(_x_d4*1000,0)), 0)
```

泵池液位：

```text
dL_pool/dt = (Q_mag_in + Q_sand_return + Q_pool_water - Q_pump)/A_pool
L_pool,k+1 = clip(L_pool,k + dt*dL_pool/dt, 0, 5)
```

旋流器给矿流量 DCS：

```text
agg_tm_cyclone_feed_flow = max(Q_pump + k_Lf*dL_pool/dt + N(0,sigma_Q_feed), 0)
```

## 旋流器分级

旋流器压力：

```text
f_ratio = f_pump/max(f_pump_nom,1)
P_cyc = k_P_cyc*rho_slurry_nom*f_ratio^2
```

粒度影响：

```text
d80_effect = 1 - exp(-max(d80_sand,0)/d_ref_cyc)
```

溢流率：

```text
_x_alpha_ov = clip(alpha_0 + k_alpha_d*d80_effect - k_alpha_P*P_cyc + N(0,sigma_alpha), 0.05, 0.95)
```

溢流和沉砂体积流量：

```text
Q_ov = _x_alpha_ov * Q_pump
Q_sand = (1 - _x_alpha_ov) * Q_pump
```

沉砂湿质量流量：

```text
m_sand = Q_sand*rho_slurry_nom*3600/1000
```

## 沉砂水阀与矿浆密度

操作员间歇调整：

```text
若 t*dt - t_last_adj >= T_adj_sand:
    u_sand_sp = clip(u_sand_mean + N(0,sigma_sand_adj), 0, 1)
```

执行机构：

```text
tau_act = max(tau_act_sand, dt)
u_sand_fb,k+1 = u_sand_fb,k + (dt/tau_act)*(u_sand_sp - u_sand_fb,k)
```

沉砂水流量：

```text
Q_sand_water = max(C_v_sand*u_sand_fb*sqrt(max(_x_d4*1000,0)), 0)
```

磨内混合密度：

```text
Q_mix = max(Q_sand + Q_sand_water, 1e-9)
rho_mill = (Q_sand*rho_slurry_nom + Q_sand_water*1000)/Q_mix
```

## 塔磨功率、粒度和 -325 目

程序固定：

```text
f325_sand = f325_sand_nom
```

机械功率：

```text
P_mech_raw =
    P0_mech
  + k_ms*m_sand
  + k_md*(1 - f325_sand)
  + k_mrho*(rho_mill - rho_slurry_nom)
  + N(0,sigma_P_mech)

_x_P_mech = clip(P_mech_raw, 0, 1.1*P_rated)
```

磨矿速率和排矿粒度：

```text
m_sand_kg_s = max(m_sand*1000/3600, 0.1)
grind_rate = k_mill*_x_P_mech/(m_sand_kg_s*max(_x_d3,0.1))
d80_disch = d80_sand*exp(-grind_rate*dt)
d80_sand,k+1 = clip(d80_disch, 0.005, 2*d80_tm_init)
```

塔磨溢流 -325 目：

```text
_x_f325_ov = clip(f325_ov_base + k_f325*(_x_P_mech/P_rated) + N(0,sigma_f325), 0, 1)
```

## 电流和泵功率

塔磨主电机电流：

```text
I_motor = _x_P_mech*1000/(sqrt(3)*V_line_tm*cos_phi_motor)
agg_tm_motor_current = I_motor + N(0,sigma_I_motor_tm)
```

旋流器泵扬程、轴功率、电流：

```text
H_pump = max(a0_pump - a1_pump*Q_pump^2, 0)
P_pump_W = rho_slurry_nom*9.81*H_pump*Q_pump/eta_pump
I_pump = P_pump_W/(sqrt(3)*V_pump*cos_phi_pump)
agg_tm_cyclone_pump_current = I_pump + N(0,sigma_I_pump)
```

## 轴承、定子和减速机温度

统一 ZOH：

```text
T_k+1 = T_ss + (T_k - T_ss)*exp(-dt/tau)
```

轴承：

```text
T_ss_b1 = T_amb + k_b1_kw*_x_P_mech
T_ss_b2 = T_amb + k_b2_kw*_x_P_mech
```

DCS 值先加噪声，再以概率 `p_fault_bearing` 替换为 `fault_val_bearing`。

定子 A 相：

```text
T_ss_sA = T_coolant + k_sA_a2*I_motor^2
T_sA,k+1 = ZOH(T_sA,k, T_ss_sA, tau_sA)
```

定子 B 相：

```text
T_sB = T_sA + dT_AB + N(0,sigma_AB)
```

A/B 相 DCS 值均按 `p_fault_stator` 注入 `fault_val_stator`。

减速机：

```text
P_loss_kw = _x_P_mech*(1 - eta_red)/eta_red
T_ss_red = T_amb + k_red_kw*P_loss_kw
T_red,k+1 = ZOH(T_red,k, T_ss_red, tau_red)
T_red_out = alpha_pipe*T_red + (1-alpha_pipe)*T_amb
```

## 溢流泵池和下游隐藏量

溢流泵开停：

```text
Q_ov_pump = Q_ov_pump_nom, 若 L_ov > L_ov_low
Q_ov_pump = 0,             否则
```

液位：

```text
dL_ov/dt = (Q_ov - Q_ov_pump)/A_ov
L_ov,k+1 = clip(L_ov,k + dt*dL_ov/dt, 0, 5)
```

溢流泵电流：

```text
pump_on = 1, 若 L_ov > L_ov_low；否则 0
I_ov_pump = I_ov_0*pump_on + k_ov_I*Q_ov_pump*rho_ov/1000
```

写给浮选段的隐藏量：

```text
_x_m_ov = Q_ov*rho_ov*3600/1000
_x_g_ov = g_mag_delayed
```
