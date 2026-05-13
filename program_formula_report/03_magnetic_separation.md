# 磁选段数学关系

来源：`sim/layers/mag_sep.py`、`sim/config.py`、公共工具。

## 励磁与线圈热

励磁电压 AR(1)：

```text
xi_V_exc,k = phi_V_exc*xi_V_exc,k-1 + N(0,sigma_V_exc)
V_exc = V_nom + xi_V_exc
agg_mag_excit_voltage = V_exc + N(0,0.5*sigma_V_exc)
```

线圈电阻、电流、焦耳热：

```text
R_coil = R0_coil*(1 + alpha_Cu*(T_coil - T0_coil))
I_exc = V_exc/R_coil
Q_joule = I_exc^2 * R_coil
```

线圈温度用前向欧拉热模型：

```text
dT/dt = (Q_joule - k_cool_coil*(T_coil - T_amb))/tau_thermal_coil
T_coil,k+1 = T_coil,k + dt*dT/dt + N(0,sigma_T_coil)
```

DCS 电流和温度：

```text
agg_mag_excit_current = I_exc + N(0,sigma_I_exc)
agg_mag_coil_temp = T_coil + N(0,sigma_T_coil)
```

## 弱磁选

弱磁精矿品位：

```text
g_wmag = clip(_x_d1*k_wm_Fe/(1 + k_wm_Si*(1-_x_d1)), 0, 1)
```

弱磁铁作业回收率：

```text
beta_wm = clip(beta_wm0*(1 - k_wm_f25*_x_f25_ball), 0.01, 0.99)
```

弱磁给矿含铁量：

```text
m_Fe_ball = _x_d1 * _x_m_ball
```

弱磁精矿量：

```text
m_wm_conc = beta_wm*m_Fe_ball/g_wmag,  若 g_wmag > 0.01
m_wm_conc = 0,                         否则
m_wm_conc = clip(m_wm_conc, 0, _x_m_ball)
```

弱磁尾矿量与品位：

```text
m_wm_tail = _x_m_ball - m_wm_conc
g_wm_tail = (m_Fe_ball - beta_wm*m_Fe_ball)/m_wm_tail,  若 m_wm_tail > 0.01
g_wm_tail = 0,                                          否则
g_wm_tail = clip(g_wm_tail, 0, 1)
```

## 强磁前浓缩滞后

程序把弱磁尾矿作为前浓缩输出目标，使用一阶欧拉：

```text
m_conc_out,k+1 = m_conc_out,k + (dt/tau_conc)*(m_wm_tail - m_conc_out,k)
m_conc_out = max(m_conc_out, 0)
```

## 转环/脉动频率

```text
xi_f_ring,k = phi_ring*xi_f_ring,k-1 + N(0,sigma_ring)
f_ring = f_ring_mean + xi_f_ring

xi_f_pul,k = phi_pul*xi_f_pul,k-1 + N(0,sigma_pul)
f_pul = f_pul_mean + xi_f_pul
```

输出：

```text
agg_mag_ring_freq = f_ring
agg_mag_pulsation_freq = f_pul
```

## 强磁归一化力竞争

磁场：

```text
B = mu0_N_over_l * I_exc
```

粒径代理：

```text
dp = dp_ref*sqrt(max(1 - _x_f25_ball, 0.01))
```

矿浆流速：

```text
m_conc_kg_s = m_conc_out*1000/3600
v_base = m_conc_kg_s/(rho_conc_kg_m3*A_cross*(1-f_matrix))
ring_factor = 1 + k_ring_v*(f_ring - f_ring_mean)/max(f_ring_mean,0.01)
v_slurry = max(v_base*ring_factor, 1e-6)
```

强磁力竞争量：

```text
force_balance = (B/B_nom)^2 / ((v_slurry/v_nom)*(dp/dp_nom)^2)
force_balance = max(force_balance, 1e-9)
beta_strong = sigmoid(lambda_s*log(force_balance) + bias_s)
```

## 强磁精矿与尾矿

强磁精矿品位：

```text
g_strong = clip(g_wm_tail*k_s_Fe/(1 + k_s_Si*(1-g_wm_tail)), g_wm_tail, 1)
```

强磁精矿量：

```text
m_strong_conc = beta_strong*g_wm_tail*m_conc_out/g_strong, 若 g_strong>0.01 且 m_conc_out>0.01
m_strong_conc = 0,                                        否则
m_strong_conc = clip(m_strong_conc, 0, m_conc_out)
```

强磁尾矿：

```text
m_strong_tail = m_conc_out - m_strong_conc
m_Fe_tail_strong = g_wm_tail*m_conc_out - g_strong*m_strong_conc
g_strong_tail = max(m_Fe_tail_strong/m_strong_tail, 0), 若 m_strong_tail>0.01
g_strong_tail = 0,                                      否则
```

## 扫强磁

扫强磁精矿品位：

```text
g_sweep = clip(g_strong_tail*k_sw_Fe/(1+k_sw_Si*(1-g_strong_tail)), g_strong_tail, 1)
```

扫强磁精矿量：

```text
m_sweep_conc = beta_sweep_Fe*g_strong_tail*m_strong_tail/g_sweep, 若 g_sweep>0.01 且 m_strong_tail>0.01
m_sweep_conc = 0,                                           否则
m_sweep_conc = clip(m_sweep_conc, 0, m_strong_tail)
```

## 混磁精矿隐藏输出

```text
_x_m_mag = m_wm_conc + m_strong_conc + m_sweep_conc
```

```text
_x_g_mag =
  (g_wmag*m_wm_conc + g_strong*m_strong_conc + g_sweep*m_sweep_conc)/_x_m_mag,
  若 _x_m_mag > 0.01
_x_g_mag = 0, 否则
_x_g_mag = clip(_x_g_mag, 0, 1)
```

## 磁选液位与阀门

入流：

```text
Q_in = m_conc_out*1000/3600/rho_conc_kg_m3
```

液位测量：

```text
b_L,k = b_L,k-1 + N(0,sigma_b_level)
L_meas = L + b_L,k + N(0,sigma_L_level)
```

PID 调用方式比较特别：

```text
u_v = PID.step(setpoint=L_meas, measurement=L_setpoint)
u_v1 = clip(u_v, 0, 1)
u_v2 = clip(u_v - 1, 0, 1)
```

出流：

```text
Q_tail = C_v_mag*(u_v1+u_v2)*sqrt(max(L,0))
Q_over = k_conc_mag*max(L - L_overflow_mag, 0)
Q_out = Q_tail + Q_over
```

液位 ODE：

```text
dL/dt = (Q_in - Q_out)/A_tank_mag
L_k+1 = clip(L_k + dt*dL/dt, 0, L_overflow_mag+0.5)
agg_mag_level = L_k+1 + b_L + N(0,sigma_L_level)
```

## 排污、水压、电机

周期排污阀：

```text
t_mod = (t*dt) mod T_blow
u_blow = u_blow_on, 若 t_mod < dt_blow
u_blow = 0,         否则
agg_mag_blowdown_valve = u_blow + N(0,sigma_blow)
```

冲矿水压：

```text
P_flush = _x_d4 - k_pipe*Q_flush^2*1e-3
agg_mag_flush_water_pressure = P_flush + N(0,sigma_P_flush)
```

主电机电流：

```text
I_motor = I_motor_0 + k_mf*_x_m_ball + k_mr*f_ring + k_mm*beta_strong*_x_m_ball
agg_mag_motor_current_rc = I_motor + N(0,sigma_I_motor)
```

电网电压：

```text
xi_Vgrid,k = phi_Vgrid*xi_Vgrid,k-1 + N(0,sigma_Vgrid)
V_motor = V_motor_nom + xi_Vgrid
agg_mag_motor_voltage_rc = V_motor + N(0,sigma_V_motor)
```
