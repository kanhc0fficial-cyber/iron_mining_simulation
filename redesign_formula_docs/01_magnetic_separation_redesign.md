# 磁选段数学模型重新设计

版本：v0.1  
范围：仅磁选段，包括弱磁、强磁前浓缩、一段强磁、扫强磁、混磁精矿输出和磁选 DCS 变量。  
本轮不修改代码，仅给出后续实现用的公式设计。

## 读取与依据

已读取：

- `program_formula_report/00_index.md`
- `program_formula_report/01_common_models.md`
- `program_formula_report/02_disturbance_and_ball_mill.md`
- `program_formula_report/03_magnetic_separation.md`
- `program_formula_report/04_tower_mill.md`
- `program_formula_report/06_design_comparison.md`
- `C:/Users/goldenwhale/Downloads/工厂生产调试报告.md`

工厂报告使用 UTF-8 读取，全文 755076 字符、3885 行，未发现替换字符 `U+FFFD`。主要依据来自报告的“流程简述”“3.1 磁选作业”“3.1.3 作业分析及建议”“4.3 流程考查中浮给物相分析”等段落。

关键工厂依据：

- 流程为“两段连续磨矿、弱磁-强磁-扫强磁、塔磨、阴离子反浮选”。
- 二次分级溢流给入 12 台弱磁，弱磁尾矿经强磁前浓缩和除渣后给入 10 台强磁，强磁尾矿给入 10 台扫强磁，三段磁精合并为混磁精矿。
- 设计及工艺要求：弱磁给矿浓度 23%-27%，给矿粒度 `-200目 >= 80%`，弱精品位 50%-52%，弱尾 24%-26%；强磁给矿浓度 42%-47%，强精 39%-41%，强尾 14%-16%；扫强磁给矿浓度 17%-22%，扫强精 30%-31%，扫强尾 7%-8%。
- 调试平均指标：二溢品位 32.02%，弱精 50.59%，弱尾 23.54%，强精 39.70%，强尾 13.77%，扫强精 30.26%，扫强尾 7.90%，混磁精 43.64%。
- 调试浓度波动明显：二溢浓度 19.06%-41.74%，平均 33.68%，对弱磁偏高；强磁给矿浓度 21.93%-40.80%，平均 30.30%，整体偏低；扫强磁平均 19.40%，基本在 17%-22% 范围。
- 现场状态问题：弱磁给矿受泡沫影响有时分布不均；强磁和扫强磁电流调整幅度较大；个别磁选机液面有时偏低；浓度波动会导致指标波动。
- 浮给物相分析指出，经过弱磁、强磁选别后，原矿中的碳酸铁在浮给中富集，富集比例约 1.29-1.93 倍，碳酸铁和硅酸铁会增加后续浮选难度。

## 现有公式问题

现有磁选段主要是“给矿 TFe 到各段精矿/尾矿 TFe 的代数分配”，设备变量只局部参与强磁回收率：

```text
g_wmag = f(_x_d1, k_wm_Fe, k_wm_Si)
beta_wm = f(_x_f25_ball)
beta_strong = sigmoid(log((B/B_nom)^2 / ((v/v_nom)*(dp/dp_nom)^2)))
g_strong = f(g_wm_tail)
g_sweep = f(g_strong_tail)
_x_g_mag = mass_weighted(g_wmag, g_strong, g_sweep)
```

主要不足：

1. 弱磁、强磁、扫强磁的品位过多由上一段品位直接代数变换得到，缺少矿物组成、解离度、浓度、处理负荷、液面、冲洗水、脉动、转环等工厂可解释路径。
2. 强磁前浓缩只是一阶滞后质量流，没有水量和浓度平衡，无法反映报告中“强磁给矿浓度整体偏低、浓度波动大”对指标的影响。
3. 弱磁只用超细粒 `_x_f25_ball` 惩罚回收率，没有体现 `-200目 >= 80%`、粗粒未解离、过细泥化、给矿分布不均的共同影响。
4. 强磁电流、脉动、转环、冲洗水压、液位、电机电流等 DCS 变量与选别指标的因果关系偏弱，不能形成真实工厂中“设备负荷和操作条件间接预测品位”的滞后相关。
5. 混磁精矿只输出总 TFe 和质量流量，未保留碳酸铁、硅酸铁、赤褐铁矿等后续浮选难度状态，导致浮选段容易把最终精矿品位集中写成少数直接变量的函数。

## 设计原则

1. 先做矿物组分平衡，再做总 TFe。品位不再由单一 TFe 代数投影得到，而由各铁矿物组分回收、夹带和水量共同形成。
2. DCS 变量只代表可观测设备状态和操作条件，不使用下游精矿品位或当前 `_x_g_mag` 反推生成。
3. 让可观测变量具有“合理但不完美”的预测性：电流、浓度、流量、液位、冲洗水、转环、脉动、设备台数通过停留时间、负荷、回收率、夹带、堵塞等路径影响混磁精矿。
4. 引入段间和设备内停留时间。品位扰动必须经过弱磁、浓缩、强磁、扫强磁等动态环节传播。
5. 按工厂报告的均值和范围校准，不凭空追求强相关。

## 总体数据流

建议磁选段内部使用隐藏状态，但 DCS 输出仍只输出工厂可测变量。

```text
仿真入口边界，默认等价于给入弱磁前的二次分级溢流:
  _x_m_ball, _x_d1, _x_d80_ball, _x_f25_ball, _x_rho_ball, _x_d2, _x_d3, _x_d4

矿物组成拆分:
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, gangue, water

弱磁:
  组分回收 + 夹带 + 给矿分布惩罚 + 粒度/浓度/负荷影响
  -> 弱磁精矿, 弱磁尾矿

强磁前浓缩:
  水固平衡 + 液位 + 底流泵 + 除渣/短路 + 停留时间
  -> 强磁给矿浓度和流量

一段强磁:
  磁场/脉动/转环/冲洗水/浓度/负荷/液位
  -> 强磁精矿, 强磁尾矿

扫强磁:
  低品位尾矿再回收 + 较低给矿浓度窗口 + 扫选电流和冲洗条件
  -> 扫强精矿, 扫强尾矿

混磁精矿:
  弱精 + 强精 + 扫强精
  -> _x_m_mag, _x_g_mag
  -> 建议新增隐藏组分 _x_fe_carb_mag, _x_fe_sil_mag, _x_liberation_mag
```

## 改动点总表

| 编号 | 改动点 | 替代现有内容 | 原因 |
|---|---|---|---|
| M1 | 引入磁选给矿矿物组分状态 | 替代只用 `_x_d1` 表示全部含铁性质 | 工厂报告说明磁赤铁矿、赤褐铁矿、碳酸铁、硅酸铁组成波动影响后续浮选，单一 TFe 无法表达可选性 |
| M2 | 用粒度解离函数同时处理粗粒和泥化 | 替代只用 `_x_f25_ball` 惩罚弱磁回收 | 报告要求弱磁给矿 `-200目 >= 80%`，粒度既影响解离也影响夹带和泥化 |
| M3 | 建立弱磁给矿浓度、负荷和分布均匀性影响 | 替代弱磁回收率基本固定 | 报告指出二溢浓度对弱磁偏高、泡沫造成给矿分布不均 |
| M4 | 强磁前浓缩改成水固平衡和变停留时间 | 替代弱磁尾矿质量一阶滞后 | 报告指出强磁给矿浓度整体偏低且波动大，这是强磁指标波动的重要路径 |
| M5 | 强磁回收率改成“捕获概率 + 冲洗保留 + 夹带”的组合 | 扩展现有单一 `force_balance -> beta_strong` | 立环高梯度强磁受磁场、电流、脉动、转环、流速、浓度、冲洗水、堵塞共同影响 |
| M6 | 扫强磁单独建模 | 替代固定 `beta_sweep_Fe` | 扫强磁给矿浓度窗口、低品位尾矿性质和扫选目标不同，不能只沿用强磁尾矿代数公式 |
| M7 | DCS 变量由设备状态生成，不由品位反推 | 约束所有 `agg_mag_*` 公式 | 保持 DCS 对品位有间接可解释预测性，避免目标信息回写 |
| M8 | 混磁输出保留隐藏组分 | 扩展 `_x_m_mag`、`_x_g_mag` | 后续浮选品位应受到碳酸铁、硅酸铁、解离度、矿浆浓度等滞后影响，而不只由药剂和 pH 决定 |

## 磁选给矿组分模型

令入口给矿湿质量为 `M_feed_wet`，固体质量为：

```text
C_feed = clip(_x_rho_ball, C_feed_min, C_feed_max)
M_feed_solid = M_feed_wet * C_feed
G_feed = clip(_x_d1, 0, 1)
M_Fe_feed = M_feed_solid * G_feed
```

其中 `C_feed` 是质量浓度。若当前代码中的 `_x_rho_ball` 已经是密度而非质量浓度，实现时需要先转换为质量浓度。

将总铁拆为四类隐藏组分：

```text
r_carb_raw = r_carb0 + k_carb_d2*(_x_d2 - d2_ref) + xi_carb
r_sil_raw  = r_sil0  + k_sil_d2 *(_x_d2 - d2_ref) + xi_sil
r_mag_raw  = r_mag0  + k_mag_g *(G_feed - G_ref) - k_mag_oxi*(_x_d2 - d2_ref) + xi_mag
r_hem_raw  = 1 - r_carb_raw - r_sil_raw - r_mag_raw

[r_mag, r_hem, r_carb, r_sil] = normalize_clip([r_mag_raw, r_hem_raw, r_carb_raw, r_sil_raw])
```

组分铁量：

```text
Fe_mag  = M_Fe_feed * r_mag
Fe_hem  = M_Fe_feed * r_hem
Fe_carb = M_Fe_feed * r_carb
Fe_sil  = M_Fe_feed * r_sil
M_gangue = M_feed_solid - M_Fe_feed
```

说明：

- `r_mag` 表示磁铁矿中铁占总铁比例，弱磁主要回收它。
- `r_hem` 表示赤褐铁矿中铁占比，强磁和扫强磁主要回收它。
- `r_carb`、`r_sil` 表示碳酸铁、硅酸铁中铁占比，它们在磁选中部分进入混磁精矿，并在浮选中增加提质难度。
- `_x_d2` 当前语义为碳酸铁扰动，应进入 `r_carb` 和 `r_sil` 的慢变状态，而不是只影响后续 pH。

## 粒度与解离模型

用 `d80` 和超细粒同时构造 `-200目` 近似、解离度和泥化惩罚：

```text
F200 = clip(1 - exp(-(75e-6 / max(d80, d80_min))^n_rr), 0, 1)
L_base = sigmoid(k_L * (F200 - 0.80))
slime_penalty = clip(1 - k_slime*_x_f25_ball, slime_min, 1)
coarse_penalty = sigmoid(k_coarse * (F200 - F200_min))
Liberation = clip(L_base * slime_penalty * coarse_penalty, 0, 1)
```

改动原因：

- 报告明确弱磁给矿粒度要求 `-200目 >= 80%`。
- 粗粒会降低解离度，过细泥化会增加夹带和恶化分选。
- 这样塔磨前的混磁精矿不仅有 TFe，还有“可磨/可浮选难度”的历史状态。

## 弱磁重新设计

### 设备与负荷

弱磁机数量上限 12 台，单机处理能力按报告取 370 m3/h。建议引入运行台数 `N_wm_on`：

```text
Q_feed = M_feed_wet * 1000 / 3600 / rho_slurry_feed
N_wm_need = ceil(Q_feed / Q_wm_unit_target)
N_wm_on = schedule_or_controller(N_wm_need, 3, 12)
load_wm = Q_feed / max(N_wm_on * 370, eps)
```

若暂时不实现开停台数 DCS，可作为隐藏状态，但后续建议输出对应设备组运行状态或用电流群组反映。

### 浓度与分布

弱磁最佳浓度窗口用报告工艺要求 23%-27%：

```text
C_wm_opt = 0.25
E_C_wm = exp(-((C_feed - C_wm_opt)/sigma_C_wm)^2)
E_load_wm = exp(-k_over_wm*max(load_wm - 1, 0)^2 - k_under_wm*max(load_min_wm - load_wm, 0)^2)

foam_disturb = sigmoid(k_foam*(_x_f25_ball - f25_ref) + k_Cfoam*(C_feed - C_wm_opt))
maldist_wm = clip(maldist_base + k_maldist*foam_disturb + xi_maldist, 0, 1)
E_dist_wm = 1 - k_dist_wm*maldist_wm
```

改动原因：

- 报告指出二溢浓度偏高，弱磁给矿受泡沫影响有时分布不均。
- 泡沫、泥化、浓度高会导致单台给矿不均，影响实际回收和夹带。

### 组分回收率

弱磁对不同组分的回收率不同：

```text
R_wm_mag  = clip(R_wm_mag0  * Liberation * E_C_wm * E_load_wm * E_dist_wm, 0, 0.995)
R_wm_hem  = clip(R_wm_hem0  * Liberation^a_hem * E_C_wm * E_load_wm, 0, 0.50)
R_wm_carb = clip(R_wm_carb0 * E_ent_wm, 0, 0.25)
R_wm_sil  = clip(R_wm_sil0  * E_ent_wm, 0, 0.25)
```

夹带：

```text
E_ent_wm = clip(e_wm0 * (C_feed/C_wm_opt)^a_C * (1 + a_slime*_x_f25_ball) * (1 + a_maldist*maldist_wm), 0, e_wm_max)
R_wm_gangue = E_ent_wm
```

产品：

```text
Fe_wm_conc_j = R_wm_j * Fe_feed_j
Gangue_wm_conc = R_wm_gangue * M_gangue
M_wm_conc_solid = sum_j Fe_wm_conc_j + Gangue_wm_conc
G_wm_conc = sum_j Fe_wm_conc_j / max(M_wm_conc_solid, eps)

Fe_wm_tail_j = Fe_feed_j - Fe_wm_conc_j
Gangue_wm_tail = M_gangue - Gangue_wm_conc
M_wm_tail_solid = sum_j Fe_wm_tail_j + Gangue_wm_tail
G_wm_tail = sum_j Fe_wm_tail_j / max(M_wm_tail_solid, eps)
```

校准目标：

- 弱精平均约 50.59%，正常范围 50%-52%。
- 弱尾平均约 23.54%，正常范围 24%-26%，允许受浓度和给矿品位波动略低或略高。

## 强磁前浓缩重新设计

现有公式只让弱磁尾矿质量流做一阶滞后。建议改为固体、水量、液位、底流浓度的动态模型。

### 入流

```text
M_pre_in_solid = M_wm_tail_solid
Q_pre_in_water = M_wm_tail_solid * (1 - C_wm_tail) / max(C_wm_tail*rho_water, eps)
Q_pre_in_slurry = Q_pre_in_water + M_pre_in_solid/rho_solid
```

### 浓缩池状态

```text
dM_solid_pre/dt = M_pre_in_solid - M_under_solid - M_over_solid
dV_water_pre/dt = Q_pre_in_water - Q_under_water - Q_over_water
L_pre = V_pre / A_pre
tau_pre = V_pre / max(Q_under_slurry + Q_over_slurry, eps)
```

底流浓度受床层、絮凝等效状态和底流泵影响：

```text
C_under_ss = clip(C_under_base
                  + k_bed*(L_pre - L_pre_ref)
                  - k_Qunder*(Q_under_slurry - Q_under_ref)
                  - k_dist_pre*disturb_pre,
                  C_under_min, C_under_max)

C_under = ZOH(C_under, C_under_ss, tau_C_under)
```

底流泵：

```text
f_under = controller(L_pre, L_pre_set)
Q_under_slurry = k_under_pump * f_under * sqrt(max(L_pre, 0))
M_under_solid = Q_under_slurry * rho_slurry(C_under) * C_under
```

改动原因：

- 工厂报告中强磁给矿设计浓度 45%，工艺要求 42%-47%，实际平均只有 30.30%，这一点必须成为强磁效果的重要输入。
- 强磁前浓缩是停留时间和浓度波动来源，不应只是质量流滞后。

校准目标：

- 强磁给矿浓度长期均值可按调试数据落在 30%-35%，但控制目标仍设 42%-47%。
- 在“浓缩机状态好、底流泵稳定”的情景下应能达到 42%-47%。

## 强磁重新设计

### 磁场和热衰减

强磁磁场由励磁电流决定，但需要考虑线圈温升和电源状态：

```text
B_raw = B_max * (1 - exp(-I_exc / I_B_ref))
thermal_derate = clip(1 - k_TB*max(T_coil - T_coil_ref, 0), B_derate_min, 1)
B_eff = B_raw * thermal_derate
```

说明：

- 保留现有线圈电阻、电流、焦耳热、温度模型。
- `agg_mag_excit_current` 是操作和设备状态代理，不直接等于产品品位。

### 流速、停留时间和负荷

```text
Q_hm_feed = Q_under_slurry
N_hm_on = schedule_or_controller(ceil(M_under_solid / M_hm_unit_target), 2, 10)
load_hm = M_under_solid / max(N_hm_on * 68, eps)

v_matrix = Q_hm_feed / max(N_hm_on * A_matrix * porosity_matrix, eps)
tau_hm = V_effective_hm / max(Q_hm_feed / N_hm_on, eps)
```

### 捕获概率

```text
E_C_hm = exp(-((C_under - C_hm_opt)/sigma_C_hm)^2)       # C_hm_opt 取 0.45
E_load_hm = exp(-k_load_hm*max(load_hm - 1, 0)^2)
E_level_hm = sigmoid(k_L_hm*(L_hm - L_hm_low))

capture_hm_j = sigmoid(
    a0_j
  + aB_j*log(max(B_eff/B_ref, eps))
  - av_j*log(max(v_matrix/v_ref, eps))
  + aL_j*log(max(Liberation/L_ref, eps))
  + aC_j*log(max(E_C_hm, eps))
  + atau_j*log(max(tau_hm/tau_ref, eps))
)
```

不同组分系数：

- `Fe_hem` 对强磁最敏感，是强磁主回收对象。
- `Fe_mag` 中弱磁未回收部分也可被回收，但系数低于弱磁。
- `Fe_carb`、`Fe_sil` 只允许小比例进入强精，主要通过夹带和部分弱磁性矿物进入。

### 脉动、转环和冲洗水

```text
E_pulse = exp(-((f_pul - f_pul_opt)/sigma_pul)^2)
E_ring = exp(-((f_ring - f_ring_opt)/sigma_ring)^2)

wash_quality = sigmoid(k_Pwash*(P_flush - P_flush_ref))
matrix_clog = ZOH(matrix_clog,
                 clog_base + k_slime*_x_f25_ball + k_C*C_under + k_lowwash*max(P_flush_ref-P_flush,0),
                 tau_clog)

E_matrix = clip((1 - k_clog*matrix_clog) * E_pulse * E_ring, E_matrix_min, 1)
R_hm_j = clip(capture_hm_j * E_matrix * E_load_hm * E_level_hm, 0, R_hm_j_max)
```

冲洗水同时影响保留和精矿夹带：

```text
strip_loss = sigmoid(k_strip*(P_flush - P_strip_ref))
R_hm_j_final = R_hm_j * (1 - s_j*strip_loss)

E_ent_hm = clip(e_hm0 * (C_under/C_hm_opt)^a * (1 + a_clog*matrix_clog) * (1 - k_wash*wash_quality), 0, e_hm_max)
R_hm_gangue = E_ent_hm
```

改动原因：

- 工厂强磁设备为立环脉动高梯度磁选机，现场运行涉及电流、转环、脉动、冲洗水、液面。
- 高冲洗水可能降低夹带但过强会冲掉已捕获颗粒；低冲洗水会堵塞介质并增加夹带。
- 浓度偏低会降低处理状态稳定性和回收效率，浓度过高会增大黏度、堵塞和夹带。

校准目标：

- 强精平均约 39.70%，正常范围 39%-41%。
- 强尾平均约 13.77%，正常范围 14%-16%。
- 当强磁给矿浓度长期低于 42%-47% 时，强精、强尾应出现更大波动，而不是简单固定在目标值。

## 扫强磁重新设计

扫强磁处理强磁尾矿，目标是进一步降低尾矿品位，同时产生低品位扫强精。其给矿浓度窗口为 17%-22%，与强磁不同。

```text
C_sw_feed = C_strong_tail
C_sw_opt = 0.195
E_C_sw = exp(-((C_sw_feed - C_sw_opt)/sigma_C_sw)^2)

N_sw_on = schedule_or_controller(ceil(M_strong_tail_solid / M_sw_unit_target), 2, 10)
load_sw = M_strong_tail_solid / max(N_sw_on * 68, eps)
v_sw = Q_sw_feed / max(N_sw_on * A_matrix * porosity_matrix, eps)
```

扫强磁捕获概率：

```text
capture_sw_j = sigmoid(
    b0_j
  + bB_j*log(max(B_sw_eff/B_sw_ref, eps))
  - bv_j*log(max(v_sw/v_sw_ref, eps))
  + bC_j*log(max(E_C_sw, eps))
  + bL_j*log(max(Liberation/L_ref, eps))
)

R_sw_j = clip(capture_sw_j * E_pulse_sw * E_ring_sw * E_load_sw * E_level_sw, 0, R_sw_j_max)
```

扫强精和扫强尾：

```text
Fe_sw_conc_j = R_sw_j * Fe_strong_tail_j
Gangue_sw_conc = R_sw_gangue * Gangue_strong_tail
G_sw_conc = sum_j Fe_sw_conc_j / max(sum_j Fe_sw_conc_j + Gangue_sw_conc, eps)

Fe_sw_tail_j = Fe_strong_tail_j - Fe_sw_conc_j
Gangue_sw_tail = Gangue_strong_tail - Gangue_sw_conc
G_sw_tail = sum_j Fe_sw_tail_j / max(sum_j Fe_sw_tail_j + Gangue_sw_tail, eps)
```

改动原因：

- 扫强磁不是强磁公式的常数回收率尾巴，而是“低品位尾矿再回收”。
- 报告中扫强磁给矿浓度基本合理，扫强尾平均 7.90%，说明它是稳定降低尾矿品位的关键环节。

校准目标：

- 扫强精平均约 30.26%，正常范围 30%-31%。
- 扫强尾平均约 7.90%，正常范围 7%-8%。

## 混磁精矿输出

混磁精矿由三段精矿合并：

```text
M_mag_solid = M_wm_conc_solid + M_hm_conc_solid + M_sw_conc_solid
Fe_mag_total = sum_j(Fe_wm_conc_j + Fe_hm_conc_j + Fe_sw_conc_j)

_x_m_mag = wet_mass(M_mag_solid, C_mag_product)
_x_g_mag = clip(Fe_mag_total / max(M_mag_solid, eps), 0, 1)
```

建议新增隐藏输出：

```text
_x_fe_mag_frac_mag  = (Fe_wm_conc_mag + Fe_hm_conc_mag + Fe_sw_conc_mag) / max(Fe_mag_total, eps)
_x_fe_hem_frac_mag  = ...
_x_fe_carb_frac_mag = ...
_x_fe_sil_frac_mag  = ...
_x_liberation_mag   = mass_weighted(Liberation of products)
_x_C_mag            = C_mag_product
```

这些隐藏变量不作为 DCS 直接输出，但供塔磨和浮选段使用：

- `_x_fe_carb_frac_mag`、`_x_fe_sil_frac_mag` 增加浮选难度。
- `_x_liberation_mag` 决定塔磨后粒度改善和浮选可选性。
- `_x_C_mag` 影响塔磨泵池和旋流器负荷。

改动原因：

- 工厂报告指出碳酸铁和硅酸铁在浮给中富集，会影响浮选指标。
- 后续最终精矿品位不能只由加药、pH 和泡沫高度预测，应让上游矿物组成扰动有滞后、间接、部分可观测的路径。

## 磁选 DCS 变量生成规则

所有 DCS 变量必须由设备状态、操作量、负荷、传感器误差生成，不得从 `_x_g_mag` 或任何下游品位反推。

新增聚合口径：磁选内部不再把 `agg_mag_*` 当作真实设备。弱磁、强磁、扫强磁先分别维护运行台数和设备组状态；`agg_mag_*` 只在最终 `DCSOutputAdapter` 中作为兼容旧数据列输出。强磁和扫强磁的电流、液位、冲洗水、转环、脉动等状态在机理层必须分开，因为两段给矿性质、浓度窗口和目标不同。

推荐内部状态：

```text
wm_unit[i].is_on, wm_unit[i].load, wm_unit[i].level
hm_unit[i].is_on, hm_unit[i].I_exc, hm_unit[i].V_exc, hm_unit[i].T_coil, hm_unit[i].level, hm_unit[i].flush_pressure
sw_unit[i].is_on, sw_unit[i].I_exc, sw_unit[i].V_exc, sw_unit[i].T_coil, sw_unit[i].level, sw_unit[i].flush_pressure
```

推荐输出适配：

```text
DCSOutputAdapter:
  agg_mag_excit_current      <- compatible aggregate of hm_unit[] and sw_unit[]
  agg_mag_hm_excit_current   <- hm_unit[] sensors
  agg_mag_sw_excit_current   <- sw_unit[] sensors
  wm_units_on, hm_units_on, sw_units_on
```

具体聚合统计方式可以由输出配置决定；它不影响磁选机理公式。

### 励磁电压、电流、线圈温度

保留现有电热模型，但将电流设定改为操作策略状态：

```text
I_exc_sp = operator_policy(G_wm_tail, C_under, load_hm, scenario) + xi_I_sp
V_exc = controller(I_exc_sp, I_exc, R_coil)
I_exc = V_exc / R_coil
T_coil = thermal(I_exc^2 * R_coil, T_amb)
```

输出适配：

```text
hm_unit[i].sensor_I_exc = hm_unit[i].I_exc + sensor_noise
sw_unit[i].sensor_I_exc = sw_unit[i].I_exc + sensor_noise
DCSOutputAdapter(hm_unit[].sensor_I_exc, sw_unit[].sensor_I_exc) -> agg_mag_* columns
```

说明：

- 若实现阶段不希望控制策略看到隐藏 `G_wm_tail`，可改为由弱磁尾矿在线代理、流量、浓度和时段策略驱动。
- 电流可以预测后续品位，但不是品位回写。

### 转环、脉动、冲洗水压

```text
f_ring_sp = operator_schedule(load_hm, matrix_clog)
f_pul_sp  = operator_schedule(C_under, matrix_clog)
f_ring = first_order(f_ring_sp)
f_pul = first_order(f_pul_sp)

Q_flush = valve_flush * sqrt(max(_x_d4, 0))
P_flush = _x_d4 - k_pipe*Q_flush^2 - k_nozzle*clog_nozzle
```

输出适配：

```text
hm_unit[i].sensor_ring_freq = hm_unit[i].f_ring + sensor_noise
sw_unit[i].sensor_ring_freq = sw_unit[i].f_ring + sensor_noise
hm_unit[i].sensor_flush_pressure = hm_unit[i].P_flush + sensor_noise
sw_unit[i].sensor_flush_pressure = sw_unit[i].P_flush + sensor_noise
```

### 液位、排污和电机电流

液位进入选别效率：

```text
dL_hm/dt = (Q_hm_feed - Q_hm_tail - Q_hm_conc - Q_over)/A_hm
E_level_hm = sigmoid(k_L*(L_hm - L_low))
```

电机电流由机械负荷生成：

```text
I_motor_rc = I0
           + k_Q*Q_hm_feed
           + k_C*C_under
           + k_ring*f_ring
           + k_clog*matrix_clog
           + k_rho*rho_slurry(C_under)
           + noise
```

排污阀影响堵塞状态：

```text
matrix_clog = matrix_clog - k_blow*u_blow*dt + clog_generation*dt
```

输出适配：

```text
hm_unit[i].sensor_level = hm_unit[i].L + sensor_noise
sw_unit[i].sensor_level = sw_unit[i].L + sensor_noise
hm_unit[i].sensor_motor_current = hm_unit[i].I_motor + sensor_noise
sw_unit[i].sensor_motor_current = sw_unit[i].I_motor + sensor_noise
DCSOutputAdapter(...) -> agg_mag_level, agg_mag_motor_current_rc, diagnostic columns
```

改动原因：

- 报告指出个别磁选机液面偏低、强磁和扫强磁电流调整幅度较大。
- 这些变量应通过设备负荷、堵塞、液位和回收率影响品位，而不是装饰性噪声。

## 时滞设计

建议磁选段内部至少使用以下动态：

```text
tau_wm = V_wm_effective / max(Q_wm_feed, eps)
tau_pre = V_pre / max(Q_under_slurry + Q_over_slurry, eps)
tau_hm = V_hm_effective / max(Q_hm_feed, eps)
tau_sw = V_sw_effective / max(Q_sw_feed, eps)
```

每段的产品组分使用一阶混合或环形缓冲：

```text
Product_stage_delayed = delay_or_ZOH(Product_stage_raw, tau_stage)
```

塔磨段已有对 `_x_m_mag`、`_x_g_mag` 的段间 delay。磁选内部新增动态后，应重新校准塔磨入口总时滞，避免重复过长。

## 参数校准顺序

1. 固定给矿均值：二溢品位约 32.02%，二溢浓度按实际调试均值 33.68% 和设计窗口 23%-27% 两类场景分别校准。
2. 校准弱磁：使弱精约 50.59%、弱尾约 23.54%，并让浓度偏高时弱尾和夹带波动增加。
3. 校准强磁前浓缩：普通调试情景下强磁给矿浓度约 30.30%，良好控制情景下接近 42%-47%。
4. 校准强磁：强精约 39.70%、强尾约 13.77%，电流、浓度、液位和冲洗水扰动应造成滞后波动。
5. 校准扫强磁：扫强精约 30.26%、扫强尾约 7.90%。
6. 校准混磁精矿：长期均值约 43.64%，并保留碳酸铁、硅酸铁富集状态，使进入浮选的有害铁矿物富集倍数可落在 1.29-1.93 的工厂报告范围内。

## 泄漏与相关性检查

后续实现后建议做以下检查：

1. `agg_mag_*` 与 `_x_g_mag` 不能存在同一步直接代数反推关系。允许通过 `hm/sw_unit[i].I_exc -> B_eff -> recovery -> product grade -> DCSOutputAdapter` 形成相关。
2. 任一 DCS 变量单独预测最终 `y_fx_xin1/2` 的能力不应过高，尤其不应超过“上游品位隐藏状态 + 磁选/塔磨/浮选多变量窗口”的组合模型。
3. `_x_g_mag` 到 `_x_g_ov`、再到浮选最终精矿品位应有可解释滞后。
4. 强磁给矿浓度、液位、冲洗水压、电机电流、线圈温度应与 `_x_g_mag` 或后续 `y_fx_xin` 呈弱到中等滞后相关，而不是即时强相关。
5. 碳酸铁、硅酸铁隐藏组分应提高浮选难度，但不应被任何 DCS 变量完全观测。

## 对后续代码实现的接口建议

保持现有输出兼容接口：

```text
_x_m_mag
_x_g_mag
agg_mag_excit_voltage
agg_mag_excit_current
agg_mag_coil_temp
agg_mag_ring_freq
agg_mag_pulsation_freq
agg_mag_level
agg_mag_blowdown_valve
agg_mag_flush_water_pressure
agg_mag_motor_current_rc
agg_mag_motor_voltage_rc
```

但这些 `agg_mag_*` 只作为最终输出列，不能作为塔磨、浮选或磁选内部下一步公式的输入。若代码短期仍通过 `bus` 传递，应在命名或注释中标明它们来自输出适配层。

新增隐藏接口建议：

```text
_x_mag_C_product
_x_mag_liberation
_x_mag_fe_mag_frac
_x_mag_fe_hem_frac
_x_mag_fe_carb_frac
_x_mag_fe_sil_frac
_x_mag_pre_underflow_C
_x_mag_matrix_clog
```

新增隐藏接口不进入训练特征，除非明确要模拟可获得的在线分析仪。它们主要用于塔磨和浮选段的真实因果链。

## 本轮结论

磁选段应从“品位代数映射”改为“矿物组分质量平衡 + 浓度/负荷/设备状态驱动的动态分选”。这样改动后，DCS 变量对最终精矿品位仍有预测价值，但预测价值来自处理量、浓度、停留时间、磁场、冲洗水、液位、堵塞和矿物组成的滞后因果路径，而不是目标信息回写或过度集中的公式。
