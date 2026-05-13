# 浮选段数学关系

来源：`sim/layers/flotation.py`、`sim/config.py`、公共工具。

## 段间时滞与总流量

塔磨溢流质量流量和品位先入缓冲，再取 `delay_steps_tm` 步前值：

```text
m_ov_del = delay(_x_m_ov, delay_steps_tm)
g_ov_del = delay(_x_g_ov, delay_steps_tm)
```

每系列名义总体积流量：

```text
Q_total_s = m_ov_del*1000/rho_ov/3600
```

## 浮选前浓缩机

底流浓度向目标值 ZOH 收敛：

```text
phi_NT = exp(-dt/max(tau_NT,1))
rho_NT,k+1 = rho_NT_target + (rho_NT,k - rho_NT_target)*phi_NT
```

固体质量分数代理：

```text
c_mass_nom = (rho_ov - 1000)/(2700 - 1000) * (2700/rho_ov)
m_solid_s = m_ov_del*c_mass_nom
```

浓缩机电流：

```text
I_NT = I_NT0 + k_NT_I*m_solid_s + N(0,sigma_NT_I)
```

## 加药量与加药泵

开环模式为 PRBS：

```text
若 U(0,1) < p_prbs_switch:
    prbs_state = 1 - prbs_state
Q_TD = Q_TD_prbs_high, 若 prbs_state=1
Q_TD = Q_TD_prbs_low,  若 prbs_state=0
```

闭环/正常模式为 AR(1)：

```text
Q_TD,k+1 = Q_TD_nom + phi_drug*(Q_TD,k - Q_TD_nom) + N(0,5*sigma_drug_f)
Q_TD,k+1 = clip(Q_TD,k+1, Q_TD_min, Q_TD_max)
```

五种加药泵名义频率向量：

```text
f_noms = [f_td_rough_nom, f_td_clean_nom, f_k6_rough_nom, f_naoh_nom, f_cao_nom]
```

泵频率目标：

```text
Q_TD_ratio = Q_TD/Q_TD_nom
f_target = f_noms*Q_TD_ratio
```

泵频率 AR(1)：

```text
f_drug,k+1 = phi_drug*f_drug,k + (1-phi_drug)*f_target + N(0,sigma_drug_f)
f_drug,k+1 = clip(f_drug,k+1, 1, 60)
```

泵电流：

```text
I_drug = clip(I_drug0 + k_drug_If*f_drug + N(0,sigma_drug_I), 0.5, 20)
```

## pH 动力学

NaOH 泵频率为 `f_drug[:,3]`：

```text
pH_ss = pH_nom + 0.5*(f_naoh/f_naoh_nom - 1) - k_pH_d2*(_x_d2 - 0.018)
pH_ss = clip(pH_ss, 8.0, 11.5)
```

pH 一阶响应并加噪：

```text
pH_k+1 = pH_ss + (pH_k - pH_ss)*exp(-dt/max(tau_pH,1)) + N(0,sigma_pH)
pH_k+1 = clip(pH_k+1, 8.0, 11.5)
```

DCS pH：

```text
fx_s1_ph = pH_1 + N(0,0.02)
fx_s2_ph = pH_2 + N(0,0.02)
```

## TFe 精矿品位核心模型

对每个系列：

```text
dQ = Q_TD - Q_TD_nom
dpH = pH - pH_nom
```

Fe 回收率：

```text
eta_Fe = clip(eta_Fe0 + k_eta_Fe*dQ, 0.50, 1.0)
```

Si 去除率：

```text
R_Si = clip(R_Si0 + k_R_Si*dQ + k_R_Si_pH*dpH, 0.0, 1.0)
```

给矿品位限幅：

```text
g = clip(g_ov_del, 0.01, 0.99)
```

浓缩到精矿中的 Fe 和 Si 代理量：

```text
Fe_conc = eta_Fe*g
Si_conc = (1 - R_Si)*(1 - g)
```

稳态精矿 TFe：

```text
TFe_ss = Fe_conc/max(Fe_conc + Si_conc, 1e-9)
```

回路动态：

```text
phi_flo = exp(-dt/max(tau_flo,1))
TFe_circuit,k+1 = TFe_ss + (TFe_circuit,k - TFe_ss)*phi_flo
```

隐藏量：

```text
_x_TFe_circuit_s1 = TFe_circuit[0]
_x_TFe_circuit_s2 = TFe_circuit[1]
_x_Q_TD_s1 = Q_TD[0]
_x_Q_TD_s2 = Q_TD[1]
_x_g_ov_del = g_ov_del
```

## 浮选槽液位和串联流

液位阀设定：

```text
u_lv_sp = clip(u_lv_nom + Kp_lv*(L_sp - L_cells), 0, 1)
```

阀反馈一阶执行：

```text
tau_act = max(tau_act_lv, dt)
u_lv_fb,k+1 = u_lv_fb,k + (dt/tau_act)*(u_lv_sp - u_lv_fb,k)
u_lv_fb,k+1 = clip(u_lv_fb,k+1, 0, 1)
```

槽出流：

```text
Q_out_pulp = C_v_lv*u_lv_fb*sqrt(max(L_cells,0))
```

串联入流：

```text
Q_in_cell[:,0] = Q_total_s
Q_in_cell[:,c] = Q_out_pulp[:,c-1], c=1..6
```

液位 ODE：

```text
dL/dt = (Q_in_cell - Q_out_pulp)/A_cell
L_cells,k+1 = clip(L_cells,k + dt*dL/dt, 0, 5)
```

## 蝶阀、充气和泡沫层

蝶阀位置：

```text
u_bv = u_bv + N(0,sigma_bv)
u_bv = clip(0.995*u_bv + 0.005*0.5, 0.1, 0.9)
```

实际充气量：

```text
Q_air = clip(Q_air_sp + N(0,sigma_Q_air), 0, 0.05)
```

充气设定慢变：

```text
Q_air_sp = clip(
    Q_air_nom + phi_Q_air_sp*(Q_air_sp - Q_air_nom) + N(0,sigma_Q_air_sp),
    0.5*Q_air_nom,
    2.0*Q_air_nom
)
```

泡沫层以当前 TFe 估算 Si：

```text
C_Si_approx = clip(1 - TFe_circuit, 0.1, 0.9)
tau_froth = 1/max(k_col_froth + k_scrape*omega_scraper, 1e-6)
h_ss = k_gen_froth*Q_air*C_Si_approx/max(k_col_froth + k_scrape*omega_scraper, 1e-9)
h_ss = clip(h_ss, 0, 1.5)
h_froth,k+1 = h_ss + (h_froth,k - h_ss)*exp(-dt/tau_froth)
h_froth,k+1 = clip(h_froth,k+1, 0, 1.5)
```

DCS 泡沫高度加噪后以概率 `p_fault_froth` 替换为 `fault_val_froth`。

## 浮选机电机电流

延迟溢流质量估计矿浆密度：

```text
rho_slurry_est = rho_ov + (m_ov_del - m_ov_nom)*0.05
rho_deviation = rho_slurry_est - rho_ov
```

电流：

```text
I_FXJ = clip(I_FXJ0 + k_FXJ*rho_deviation + N(0,sigma_I_FXJ), 10, 50)
```

## 搅拌槽温度和蒸汽阀

蒸汽阀设定：

```text
u_TV_sp = clip(u_TV_nom + Kp_TV*(T_tk_sp - T_tanks), 0, 1)
```

阀反馈 ZOH：

```text
u_TV_fb,k+1 = u_TV_sp + (u_TV_fb,k - u_TV_sp)*exp(-dt/max(tau_TV,1))
u_TV_fb,k+1 = clip(u_TV_fb,k+1, 0, 1)
```

槽温向设定值 ZOH 收敛并加噪：

```text
T_tanks,k+1 = T_tk_sp + (T_tanks,k - T_tk_sp)*exp(-dt/max(tau_tk,1)) + N(0,sigma_T_tk)
T_tanks,k+1 = clip(T_tanks,k+1, 20, 80)
```

## 浮选泵池

每个泵池入流：

```text
Q_in_pool = Q_total_s/N_POOLS
```

泵排量：

```text
Q_pump_pool = k_pump_flo*f_pumps*sqrt(max(L_pools,0))
```

液位：

```text
dL_pool/dt = (Q_in_pool - Q_pump_pool)/A_pool_flo
L_pools,k+1 = clip(L_pools,k + dt*dL_pool/dt, 0, 5)
```

频率目标和执行：

```text
f_target_pool = clip(f_pump_flo_nom + Kp_pool_flo*(L_pools - L_pool_flo_sp),
                     f_pump_flo_min, f_pump_flo_max)
f_pumps,k+1 = f_pumps,k + (dt/30)*(f_target_pool - f_pumps,k) + N(0,sigma_f_pump_flo)
f_pumps,k+1 = clip(f_pumps,k+1, f_pump_flo_min, f_pump_flo_max)
```

泵电流：

```text
I_pool = clip(I_pump_flo0 + k_pump_flo_I*f_pumps^2 + N(0,sigma_I_pool), 1, 60)
```

## 鼓风机、K6 箱和入矿流量

鼓风机压力：

```text
P_blower,k+1 = P_blower_nom + phi_blower*(P_blower,k - P_blower_nom) + N(0,sigma_blower)
P_blower,k+1 = clip(P_blower,k+1, 10, 60)
```

K6 药箱液位：

```text
L_k6,k+1 = L_k6_init + phi_k6*(L_k6,k - L_k6_init) + N(0,sigma_L_k6)
L_k6,k+1 = clip(L_k6,k+1, 0.2, 3.0)
```

四个入矿流量计：

```text
Q_ft_i = max(Q_total_s + N(0,sigma_Q_ft), 0), i=1..4
```

## 变压器有功功率

每系列浮选机功率：

```text
P_FXJ_total = sum(I_FXJ)*380*sqrt(3)*0.85/1000
```

每系列泵功率：

```text
P_pump_total = sum(I_pool)*380*sqrt(3)*0.85/1000
```

AH5/AH6：

```text
P_AH = clip(P_FXJ_total + P_pump_total + N(0,sigma_P_AH), 100, 5000)
```

## 化验标签 `y_fx_xin1/2`

每步先将当前回路 TFe 加系列偏置写入化验缓冲：

```text
lab_buf_s.push(TFe_circuit_s + delta_s)
delta_s = [0, delta_12]
```

采样倒计时：

```text
steps_to_assay_s = steps_to_assay_s - 1
```

若到采样时刻：

```text
y_fx_xin_s = TFe_circuit_s + delta_s + N(0,sigma_lab)
steps_to_assay_s ~ randint(assay_interval_min, assay_interval_max)
tau_lab_s ~ randint(tau_lab_min, tau_lab_max)
```

否则：

```text
y_fx_xin_s = NaN
```

注意：程序当前写法是按采样时刻写入标签；`tau_lab_s` 被更新但没有用来延后写入目标值。
