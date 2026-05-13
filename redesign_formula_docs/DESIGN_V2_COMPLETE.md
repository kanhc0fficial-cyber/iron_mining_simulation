# 选矿仿真系统 v2 完整设计规格

版本：v2.1-draft  
定位：这是后续重构的唯一施工图。`redesign_formula_docs/00~07` 只作为推导、审查记录和附录参考。  
目标：生成更接近真实工厂机理的 DCS 时序、过程化验时序和最终精矿品位标签，避免目标信息反写到 DCS 特征。

## 0. 文档地位与版本锁定

本文是实现层面的唯一施工图。后续代码实现、参数配置、测试验收优先服从本文；若本文与 `00~07` 附录文档存在冲突，以本文为准。附录文档用于追溯推导原因，不再要求实现者合并阅读后自行判断。

本文吸收的依据如下：

| 来源 | 当前用途 | 在本文中的落点 |
|---|---|---|
| `00_process_lab_outputs.md` | 过程化验输出口径 | 第 11 节 |
| `01_magnetic_separation_redesign.md` | 磁选组分分流、强磁/扫强磁设备状态 | 第 8 节 |
| `02_boundary_feed_redesign.md` | 入口边界和三路线二溢样 | 第 7 节 |
| `03_tower_mill_redesign.md` | 塔磨闭路、三次分级、解离度更新 | 第 9 节 |
| `04_flotation_redesign.md` | 新1#/新2#浮选、药剂、段级 CSTR | 第 10 节 |
| `06_implementation_dataflow_equations.md` | 全流程调度和数据流 | 第 5、6 节 |
| `07_dcs_output_aggregation_draft.md` | DCS 输出适配层和 `agg_*` 口径 | 第 5.3、6、8~10 节 |
| `agg_source_variable_mapping_report.md` | 旧 `agg_*` 兼容列全名单和来源统计 | 第 5.4、8、9 节 |
| `工厂生产调试报告.md` | 标定目标与设备边界 | 第 2、7~12 节 |

后续如果附录文档继续修订，必须同步检查本文对应章节；不能只改附录而默认本文自动继承。

## 1. 结论与可行性

本设计可以实现，但不建议一次性“大爆炸式”替换全部代码。推荐按“入口边界 -> 物料流结构 -> 磁选 -> 塔磨 -> 浮选 -> 化验输出 -> 校准”的顺序分阶段重构。

可行性判断：

- 现有工程已经按 `DisturbanceLayer -> BallMillInput -> MagSepSystem -> TowerMillSystem -> FlotationSystem` 分层，天然适合逐层替换。
- 现有 `_x_*` 隐藏量和 DCS bus 机制可以保留，只需扩展隐藏状态和 writer。
- `agg_*` 变量应重新定位为最终输出适配层的兼容列，而不是仿真内部的真实设备状态。工艺公式读取 `Stream`、设备状态、系列状态和传感器状态，最后由 `DCSOutputAdapter` 聚合输出 DCS。
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

浮选范围只包括新1#和新2#两套 70 m3 新浮选系统，对应最终标签 `y_fx_xin1`、`y_fx_xin2`。老浮选系统 BFⅡ-16 不进入本系统浮选机理仿真，也不用老系统浮精/浮尾指标校准新系统标签。

允许作为边界或公用扰动进入的对象：

```text
公用入口矿石性质
公用磁选和塔磨上游状态
公用水压/循环水状态
经点位确认的公用药剂站库存或供给压力
事故泵/事故池事件标志
```

这些公用对象只能作为边界扰动、设备负荷或异常事件进入，不生成老系统目标，也不把老系统性能混入新1#/新2#浮选模型。

明确不在仿真范围：

```text
破碎机内部
一段球磨内部
二段球磨内部
球磨 DCS
破碎/球磨设备电流、功率、轴承温度
老浮选系统内部槽、泵、气量和目标品位
```

因此，`1#二溢/2#二溢/3#二溢` 可以作为入口边界化验样输出，但不能解释为仿真内部球磨模型的结果。

## 3. 设计目标

### 3.1 数据集目标

生成三类数据：

1. DCS 过程变量：用于软测量特征。
2. 过程化验变量：用于流程状态跟踪、多任务标签、数据质检，不默认进入 DCS 特征。
3. 最终精矿品位标签：`y_fx_xin1/2`，不设置化验报出滞后。

软测量建模目标：

- 目标不是让单个 DCS 点位强预测最终品位，而是让多变量、非线性、带时间窗口的深度学习模型能够利用真实过程路径获得优势。
- 一个合理数据集应表现为：时间窗口模型优于单时刻模型，多变量模型优于少数强代理变量，上游矿石性质扰动能沿磁选、塔磨、浮选产生可解释滞后。
- `lab_*` 过程化验可以用于辅助监督或质检，但默认不进入 DCS 主特征集，避免把人工化验当作在线传感器。

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

最终 DCS 聚合列 agg_*
  -> 回流进磁选、塔磨、浮选机理公式
```

`agg_*` 的语义是“DCS 输出看到的聚合/兼容列”。它可以作为软测量训练特征，但不能成为仿真机理的输入。

## 4. 全局单位与工具函数

内部单位：

| 类别 | 内部单位 |
|---|---|
| 质量流量 | t/h |
| 体积流量 | m3/h |
| 品位、浓度、粒级含量 | 0-1 |
| 化验输出 | 百分数，0-100 |
| 时间步长 | `dt`，默认 60 s |

时间单位约定：

- `dt` 和 `ZOH(x, x_ss, tau)` 中的 `tau` 默认使用秒。
- 由体积/体积流量计算的停留时间 `V/Q` 默认得到小时，因为 `Q` 使用 m3/h；变量名必须写成 `tau_*_h`。
- 若把停留时间送入 `ZOH`，必须先转换为秒：`tau_*_s = 3600*tau_*_h`。
- 若把停留时间送入速率公式 `1-exp(-k*tau)`，则 `k` 的单位必须与 `tau` 匹配；例如 `k_h_inv` 对应 `tau_h`。
- 禁止在同一公式中混用秒、分钟、小时而不写后缀。

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

解离度不是粒级含量的同义词。`F200/F325` 只能作为解离度预测的输入之一，不能直接用 `sigmoid(F200-0.80)` 当作真实单体解离度。

第一版采用经验校准函数：

```text
Liberation_fe = clip(L0_fe
                     + k325_fe*(F325-F325_ref)
                     + k25_fe*(f25-f25_ref)
                     - k_coarse_fe*coarse_frac
                     + k_grind_fe*grinding_history,
                     0, 1)

Liberation_gangue = clip(L0_g
                         + k325_g*(F325-F325_ref)
                         + k25_g*(f25-f25_ref)
                         - k_carb_g*r_carb
                         - k_sil_g*r_sil,
                         0, 1)
```

必须用流程考查解离度锚点校准：

| 样点 | 粒度 | 铁矿物解离度 | 脉石解离度 |
|---|---:|---:|---:|
| 混磁精 | `-200目` 约 78.26% | 约 67.51% | 约 37.43% |
| 旋给 | `-325目` 约 70.35% | 约 66.94% | 约 29.24% |
| 塔排 | `-325目` 约 70.45% | 约 72.73% | 约 31.36% |
| 旋溢 | `-325目` 约 93.46% | 约 79.09% | 约 61.37% |

旋流器分级时，溢流和沉砂的解离度应按粒级偏析更新；溢流通常更细、解离度更高，不能简单复制给矿标量。

## 5. 核心数据结构

### 5.1 Stream

所有物料流都使用同一结构：

```text
Stream = {
  M_solid, M_water, C,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  FeO_proxy,
  TFe,
  F200, F325, f25, d80,
  Liberation_fe, Liberation_gangue,
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
- `FeO_proxy`：亚铁/FeO 代理量，用于生成 `lab_*_feo` 等过程化验；它不是总铁的重复字段，不能由最终品位反推。
- `Liberation_fe`：铁矿物单体解离度代理。
- `Liberation_gangue`：脉石矿物单体解离度代理。
- `WI`：下游再磨难度代理，只影响塔磨和粒度，不代表仿真球磨内部。

若公式中为了简写使用 `Liberation`，默认指 `Liberation_fe`。浮选中涉及脉石可浮性、夹带或硅酸盐去除时，应优先使用 `Liberation_gangue` 或两者组合。

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
  states
}

TMOut = {
  cyclone_feed, cyclone_overflow, cyclone_sand,
  tm_discharge,
  states
}

FloOut = {
  feed,
  rougher_conc, rougher_tail,
  cleaner_conc, cleaner_tail,
  scav1_conc, scav1_tail,
  scav2_conc, scav2_tail,
  scav3_conc, final_tail,
  y_fx_xin1, y_fx_xin2,
  states
}
```

### 5.3 设备状态与 DCS 输出适配

并联设备和系列设备不在机理层提前聚合。模块内部应维护设备/系列/段级状态：

```text
DeviceGroupState = {
  device[i].is_on,
  device[i].feed_stream,
  device[i].product_stream,
  device[i].tail_stream,
  device[i].level,
  device[i].current,
  device[i].voltage,
  device[i].temperature,
  device[i].valve_position,
  device[i].fault_state
}
```

对浮选段：

```text
FlotationSeriesState = {
  series_id in {new1, new2},
  feed_thickener,
  reagent_pump[NaOH, DF_K6, CaO, TD_rougher, TD_cleaner],
  stage[rougher, cleaner, scav1, scav2, scav3],
  sump[],
  final_conc,
  final_tail
}
```

最终 DCS 输出由单独适配器生成：

```text
DCSFrame = DCSOutputAdapter.step(BoundaryOut, MagOut.states, TMOut.states, FloOut.states)
```

适配器可以输出旧 `agg_*` 兼容列、推荐的新语义列和诊断列，但工艺模块不得反向读取这些输出列。

### 5.4 DCS 输出列与特征分层

DCS 输出分三层管理：

```text
required_dcs_features:
  默认进入软测量训练的在线过程变量。

optional_diagnostic_features:
  用于诊断、消融、异常识别或开发调试，默认可输出但不一定进入训练。

disabled_or_label_only:
  默认不进入 DCS 特征集，只作为标签、化验、隐藏真值或待确认字段。
```

默认规则：

- `required_dcs_features` 只能包含现场在线可见量或其输出适配结果，例如泵频、泵电流、液位、压力、气量、药剂泵流量、设备开台数。
- `optional_diagnostic_features` 可以包含 `_on_count`、`_source_count`、`_std`、`_min`、`_max`、异常标志、单台设备统计，但不作为第一版主特征强制进入。
- `disabled_or_label_only` 包含 `y_fx_xin1/2`、`lab_*`、理论真值 `_x_*_true`、未确认样点、以及会造成标签泄漏的中间真值。
- 隐藏状态 `_x_*` 可用于模块间传递和调试，但默认不是 DCS 特征；若为了兼容旧数据集临时输出，必须标为 `debug_hidden`。

旧数据集中已经存在的 `agg_*` 兼容列如下，第一版继续输出，但全部由 `DCSOutputAdapter` 生成：

```text
磁选兼容列:
agg_mag_excit_voltage
agg_mag_excit_current
agg_mag_coil_temp
agg_mag_tailings_valve1
agg_mag_tailings_valve2
agg_mag_blowdown_valve
agg_mag_pulsation_freq
agg_mag_ring_freq
agg_mag_level
agg_mag_flush_water_pressure
agg_mag_motor_current_rc
agg_mag_motor_voltage_rc

塔磨/三次分级兼容列:
agg_tm_motor_current
agg_tm_reducer_oil_temp
agg_tm_reducer_outlet_temp
agg_tm_cyclone_pump_current
agg_tm_cyclone_pump_freq
agg_tm_cyclone_sand_water_flow
agg_tm_cyclone_feed_flow
agg_tm_cyclone_sand_valve_setpoint
agg_tm_cyclone_sand_valve_feedback
agg_tm_cyclone_pool_valve_setpoint
agg_tm_cyclone_pool_level
agg_tm_cyclone_overflow_pool_level
agg_tm_overflow_pump_current

公用/异常兼容列:
agg_accident_pump_freq
agg_accident_pump_current
agg_bottom_pump_freq_setpoint
agg_bottom_pump_current
```

其中 `agg_accident_*` 默认不作为稳态软测量主特征。它们应同时派生：

```text
event_accident_pump_active
event_accident_pump_load
```

训练集可以选择剔除事故窗口，或保留为异常场景并显式带 `event_*` 标志。不能让事故泵电流/频率在正常浮选或磁选公式中连续参与品位生成。

`agg_bottom_*` 属于公用底流/渣浆泵兼容列。若实现阶段无法确认其与新1#/新2#浮选目标的直接物料关系，默认作为 `optional_diagnostic_features`，不进入机理公式；若后续确认它对应三次分级或浓缩底流的真实输送路径，再绑定到对应泵池状态。

推荐新增的新语义列：

```text
磁选:
wm_units_on
hm_units_on
sw_units_on
agg_mag_hm_excit_current
agg_mag_sw_excit_current
agg_mag_hm_excit_voltage
agg_mag_sw_excit_voltage
agg_mag_hm_coil_temp
agg_mag_sw_coil_temp
agg_mag_hm_level
agg_mag_sw_level
agg_mag_hm_flush_water_pressure
agg_mag_sw_flush_water_pressure

塔磨:
tm_units_on
tm_cyclone_trains_on
tm_cyclone_feed_flow_total
tm_cyclone_feed_pressure
tm_cyclone_open_count
tm_motor_current_max
tm_overflow_pool_level

浮选:
fx_new1_feed_flow
fx_new2_feed_flow
fx_new1_feed_density
fx_new2_feed_density
fx_new1_ph
fx_new2_ph
fx_new1_naoh_pump_flow
fx_new2_naoh_pump_flow
fx_new1_df_k6_pump_flow
fx_new2_df_k6_pump_flow
fx_new1_cao_pump_flow
fx_new2_cao_pump_flow
fx_new1_td_rougher_pump_flow
fx_new2_td_rougher_pump_flow
fx_new1_td_cleaner_pump_flow
fx_new2_td_cleaner_pump_flow
fx_new1_rougher_air_flow
fx_new2_rougher_air_flow
fx_new1_cleaner_air_flow
fx_new2_cleaner_air_flow
```

这些新语义列优先用于后续模型实验；旧 `agg_*` 列用于兼容历史数据结构。具体聚合取均值、总和、最大值、加权均值还是健康设备均值，由输出适配器配置决定，不在机理公式中硬编码。

命名约束：任何以 `agg_` 开头的列，即使是新补充的 `agg_mag_hm_*`、`agg_mag_sw_*` 分组列，也一律视为 DCS 输出适配层结果。它们可以进入训练特征集，但永远不能作为磁选、塔磨、浮选机理公式的输入。若实现者需要机理输入，必须读取 `hm_unit[]`、`sw_unit[]`、`train[]`、`tm_unit[]`、`series[]` 等内部状态。

## 6. 单步调度

```text
BoundaryGenerator.step(t)
MagSepSystem.step(BoundaryOut.mixed)
TowerMillSystem.step(MagOut.mixed_conc)
FlotationSystem.step(TMOut.cyclone_overflow)
ProcessLabSampler.step(BoundaryOut, MagOut, TMOut, FloOut)
DCSFrame = DCSOutputAdapter.step(BoundaryOut, MagOut.states, TMOut.states, FloOut.states)
Writer.step(DCSFrame, lab_*, y_*)
```

`DCSOutputAdapter` 默认不接收 `lab_*` 和 `y_*`，避免实现时误把标签读进 DCS 生成。若工程上为了统一写表、打时间戳或生成列分层元数据需要接收它们，也必须保证生成 DCS 特征列时不读取其数值。更严格的实现可以拆成：

```text
DCSFrame = DCSOutputAdapter.step(BoundaryOut, MagOut.states, TMOut.states, FloOut.states)
FeatureCatalog.step(DCSFrame, lab_*, y_*)
Writer.step(DCSFrame, lab_*, y_*, feature_catalog)
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

三路线可用性是离散调度状态，不用连续噪声替代：

```text
N_mill_lines_on in {1,2,3}
availability_i in {0,1}
sum_i availability_i = N_mill_lines_on
```

单线处理量围绕约 252 t/h 的生产能力波动。三线同时运行时总量接近满负荷；一线/两线运行时入口流量应出现离散台阶，而不是平滑连续变化。

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
FeO_proxy_i = k_feo_mag*Fe_mag_i + k_feo_carb*Fe_carb_i + k_feo_hem*Fe_hem_i + k_feo_sil*Fe_sil_i
Gangue_i = max(M_solid_i-Fe_total_i,0)
```

汇总：

```text
BoundaryOut.mixed = mass_weighted_sum(line[1..3])
```

校准目标：

| 场景 | TFe | 浓度 C | 粒度 | 用途 |
|---|---:|---:|---:|---|
| 流程考查/默认现场场景 | 31%-32% | 均值 38%-40%，范围约 34%-42% | `-200目` 均值约 77%，范围约 74%-83% | 默认训练数据主场景 |
| 调试磁选单独考查场景 | 约 32% | 均值约 33.68%，范围约 19%-42% | 通常 75%-80% | 覆盖调试期波动 |
| 理想控制/设计场景 | 30%-33% | 弱磁设计窗口 23%-27% | `-200目 >= 80%` | 对照、消融和良好工况 |

默认不使用 23%-27% 作为真实现场均值；它只是工艺设计/理想控制窗口。若生成现场软测量训练数据，应优先使用流程考查或调试实际分布。

`WI` 仅作为下游再磨难度代理。没有现场直接测量时，应限制在经验范围并降低权重，避免让它成为任意调参自由度。第一版建议把 `WI` 作为慢变隐变量，主要影响塔磨磨矿速率和粒度响应，不直接进入最终品位公式。

## 8. 磁选段

磁选设备边界：

```text
弱磁：12 台 CTB1245 半逆流永磁筒式磁选机
强磁：10 台 LHGC-3000 立环脉动高梯度强磁机
扫强磁：10 台 LHGC-3000 立环脉动高梯度强磁机
强磁前：浓缩 + 平板筛/除渣筛
```

运行台数必须作为离散设备状态进入：

```text
N_wm_on in [3,11]   # 调试运行范围，设计设备 12 台
N_hm_on in [2,6]    # 调试运行范围，设计设备 10 台
N_sw_on in [2,6]    # 调试运行范围，设计设备 10 台
```

强磁和扫强磁在机理层分开建模。两者设备相似，但给矿品位、浓度窗口、目标和操作策略不同，不能共用一个平均设备状态。

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

弱磁浓度窗口使用双口径：

| 口径 | 浓度 |
|---|---:|
| 工艺设计/理想控制 | 23%-27%，中心 25% |
| 调试实际 | 均值约 33.68%，20 批样中多数高于 30% |

因此 `E_C_wm` 的最优点仍可设在 0.25，但默认现场场景不应把入口浓度强行拉回 25%。模型应允许弱磁在偏高浓度下运行，并让分布不均、夹带和弱尾波动增加。

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

除渣筛作为强磁给矿质量修正，不做复杂筛分设备仿真，但必须保留一条状态路径：

```text
trash_load = f(coarse_impurity, screen_health, wash_water, load)
screen_bypass = event_or_fault(screen_health, overload)
hm_feed = screen(hm_feed_raw, trash_removal_eff, screen_bypass)
```

除渣筛主要影响强磁给矿粗杂质、局部堵塞、液位和矩阵堵塞风险。第一版可让它影响 `matrix_clog`、`maldistribution_hm` 和少量夹带，而不直接改写产品品位。

强磁给矿浓度标定分两类：

| 场景 | 强磁给矿浓度 |
|---|---:|
| 调试实际均值 | 约 30.30%，范围约 22%-41% |
| 工艺设计/良好控制 | 42%-47%，中心约 45% |

实现要求：在 30.30% 的实际低浓度场景下，强精/强尾不能被强行固定到最优指标；应表现为波动更大、效率偏离或需要其他操作补偿。`E_C_hm` 可设置效率下限或分场景参数，但必须保留“浓度偏离设计窗口会影响强磁稳定性”的路径。

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
hm_unit[i].I_exc, hm_unit[i].V_exc, hm_unit[i].T_coil, hm_unit[i].level, hm_unit[i].motor_current
sw_unit[i].I_exc, sw_unit[i].V_exc, sw_unit[i].T_coil, sw_unit[i].level, sw_unit[i].motor_current

DCSOutputAdapter:
  agg_mag_excit_current        <- compatible aggregate of hm_unit[] and sw_unit[]
  agg_mag_hm_excit_current     <- high-intensity magnetic group sensors
  agg_mag_sw_excit_current     <- sweep high-intensity magnetic group sensors
  hm_units_on, sw_units_on     <- discrete operating counts
```

磁选 DCS 源状态必须至少覆盖：

```text
hm_unit[i].sensor_I_exc
hm_unit[i].sensor_V_exc
hm_unit[i].sensor_T_coil
hm_unit[i].sensor_tailings_valve1
hm_unit[i].sensor_tailings_valve2
hm_unit[i].sensor_blowdown_valve
hm_unit[i].sensor_pulsation_freq
hm_unit[i].sensor_ring_freq
hm_unit[i].sensor_level
hm_unit[i].sensor_flush_water_pressure
hm_unit[i].sensor_motor_current
hm_unit[i].sensor_motor_voltage

sw_unit[i].sensor_I_exc
sw_unit[i].sensor_V_exc
sw_unit[i].sensor_T_coil
sw_unit[i].sensor_tailings_valve1
sw_unit[i].sensor_tailings_valve2
sw_unit[i].sensor_blowdown_valve
sw_unit[i].sensor_pulsation_freq
sw_unit[i].sensor_ring_freq
sw_unit[i].sensor_level
sw_unit[i].sensor_flush_water_pressure
sw_unit[i].sensor_motor_current
sw_unit[i].sensor_motor_voltage
```

旧兼容列的默认来源：

```text
agg_mag_excit_voltage         <- adapter(hm_unit[].sensor_V_exc, sw_unit[].sensor_V_exc)
agg_mag_excit_current         <- adapter(hm_unit[].sensor_I_exc, sw_unit[].sensor_I_exc)
agg_mag_coil_temp             <- adapter(hm_unit[].sensor_T_coil, sw_unit[].sensor_T_coil)
agg_mag_tailings_valve1       <- adapter(hm/sw tailings valve 1 sensors)
agg_mag_tailings_valve2       <- adapter(hm/sw tailings valve 2 sensors)
agg_mag_blowdown_valve        <- adapter(hm/sw blowdown valve sensors)
agg_mag_pulsation_freq        <- adapter(hm/sw pulsation frequency sensors)
agg_mag_ring_freq             <- adapter(hm/sw ring frequency sensors)
agg_mag_level                 <- adapter(hm/sw level sensors)
agg_mag_flush_water_pressure  <- adapter(hm/sw flush water pressure sensors)
agg_mag_motor_current_rc      <- adapter(hm/sw main motor current sensors)
agg_mag_motor_voltage_rc      <- adapter(hm/sw main motor voltage sensors)
```

第一版适配器可仍按历史口径输出一个全磁选 `agg_mag_*`，但必须同时输出 `hm/sw` 分组列或 `hm_units_on/sw_units_on`，否则无法诊断“强磁和扫强磁被过度平均”的问题。

说明：强磁和扫强磁在机理层必须分开计算。旧 `agg_mag_*` 只作为输出兼容列保留，不再作为强磁或扫强磁公式的输入。

## 9. 塔磨与三次分级

设备边界：

```text
塔磨：6 台 CSM-1120 立式搅拌磨
三次分级：6 组 Φ250 mm × 16 水力旋流器组
```

调试运行口径：

```text
N_tm_on in [2,5]，大部分时间约 4 台
N_cyclone_trains_on 与塔磨运行组数大体对应
每组旋流器开台数可在 4-11 台波动，正常生产/流程考查更常见 7-12 台
```

塔磨和旋流器组属于新1#/新2#浮选的公用上游系统。它们可以作为共同扰动影响两个新浮选系列，但不能生成老系统目标，也不能用老系统结果校准。

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

旋流器开台和压力场景：

| 场景 | 旋流器开台 | 压力 |
|---|---:|---:|
| 正常流程考查 | 常见约 7-12 台 | 多数低于 0.25 MPa |
| 调试早期/异常 | 可出现 4-11 台 | 允许极端值至约 0.84 MPa |

实现时 `P_max` 不应卡死在 0.25 MPa；建议允许至少 1.0 MPa 的异常上限，并用 `event_pressure_spike` 或泵池/阀门异常解释极端压力。正常生产数据生成时，不应高频生成 4 台开台的早期异常场景。

### 9.2 塔磨

```text
M_sand = (1-alpha_over)*M_cyc_feed
C_mill = calc_mill_concentration(Q_sand, Q_sand_water)

media_load = ZOH(media_load, media_load_target - media_wear_rate*dt + media_makeup, tau_media)
P_media = k_media*media_load*speed_mill^3
P_pulp = k_pulp*M_sand^a_M*rho_slurry(C_mill)^a_rho
P_grind_difficulty = k_WI*WI + k_C*(C_mill-C_opt)^2 + k_fine*(1-F325_sand)
P_mech_ss = P0 + P_media + P_pulp + P_grind_difficulty
P_mech = ZOH(P_mech, clip(P_mech_ss,0,1.15*P_rated), tau_P)

E_spec = P_mech/max(M_sand,eps)
k_grind = k0*E_spec/max(WI,eps)*E_C_mill*E_load
d80_discharge = d80_sand*exp(-k_grind*tau_mill)
F325_discharge = F(45e-6; d80_discharge,n_rr)
Liberation_fe_discharge = clip(Liberation_fe_sand
                               + k_lib_fe*(F325_discharge-F325_sand)
                               + k_energy_fe*log1p(E_spec/E_ref),
                               0,1)
Liberation_gangue_discharge = clip(Liberation_gangue_sand
                                   + k_lib_g*(F325_discharge-F325_sand)
                                   + k_energy_g*log1p(E_spec/E_ref),
                                   0,1)
```

塔磨功率不应由固体处理量线性主导。立式搅拌磨主功率主要受研磨介质装载量、搅拌转速、矿浆密度和机械状态影响；固体给矿量只作为较弱的负荷修正。调试报告中塔磨电流约 70-75 A，在处理量显著变化时变化不大，因此 `k_pulp` 和 `a_M` 应限制，避免功率成为处理量的强代理。

研磨介质状态第一版可作为慢变隐藏状态：

```text
media_load_t
media_size_mix = {phi25, phi19, phi12}
media_wear_rate
media_makeup_event
```

若没有现场球耗数据，`media_load` 使用设备设计值和缓慢漂移，不作为 DCS 默认特征。

塔磨排矿返回三次分级后，旋流器溢流和沉砂的解离度不能简单复制给矿：

```text
Liberation_fe_over = clip(Liberation_fe_feed
                          + k_class_fe*(F325_over-F325_feed)
                          + k_select_fe*(fine_iron_bias),
                          0,1)

Liberation_gangue_over = clip(Liberation_gangue_feed
                              + k_class_g*(F325_over-F325_feed)
                              + k_select_g*(fine_gangue_bias),
                              0,1)

Liberation_fe_sand = mass_balance_residual(Liberation_fe_feed, Liberation_fe_over, alpha_over)
Liberation_gangue_sand = mass_balance_residual(Liberation_gangue_feed, Liberation_gangue_over, alpha_over)
```

这里的 `fine_iron_bias` 和 `fine_gangue_bias` 是粒级偏析代理，第一版可由 `F325_over-F325_sand`、`f25_over-f25_sand` 和组分比例近似。校准目标仍以第 4 节的四个解离度锚点为准。

塔磨 DCS：

```text
train[k].Q_feed, train[k].P_feed, train[k].pool_level, train[k].pump_current
tm_unit[i].P_mech, tm_unit[i].motor_current, tm_unit[i].bearing_temp, tm_unit[i].reducer_temp

DCSOutputAdapter:
  agg_tm_cyclone_feed_flow     <- compatible aggregate of train[].Q_feed sensors
  agg_tm_cyclone_pump_current  <- compatible aggregate of train[].pump_current sensors
  agg_tm_motor_current         <- compatible aggregate of tm_unit[].motor_current sensors
  tm_units_on, tm_cyclone_trains_on
```

塔磨/三次分级 DCS 源状态必须至少覆盖：

```text
train[k].sensor_feed_flow
train[k].sensor_feed_pressure
train[k].sensor_feed_density
train[k].sensor_pump_freq
train[k].sensor_pump_current
train[k].sensor_sand_water_flow
train[k].sensor_sand_valve_setpoint
train[k].sensor_sand_valve_feedback
train[k].sensor_pool_valve_setpoint
train[k].sensor_pool_level
train[k].cyclone_count_on

tm_unit[i].sensor_motor_current
tm_unit[i].sensor_reducer_oil_temp
tm_unit[i].sensor_reducer_outlet_temp
tm_unit[i].sensor_bearing_temp
tm_unit[i].is_on

overflow_pool[k].sensor_level
overflow_pump[k].sensor_current
```

旧兼容列的默认来源：

```text
agg_tm_motor_current                 <- adapter(tm_unit[].sensor_motor_current)
agg_tm_reducer_oil_temp              <- adapter(tm_unit[].sensor_reducer_oil_temp)
agg_tm_reducer_outlet_temp           <- adapter(tm_unit[].sensor_reducer_outlet_temp)
agg_tm_cyclone_pump_current          <- adapter(train[].sensor_pump_current)
agg_tm_cyclone_pump_freq             <- adapter(train[].sensor_pump_freq)
agg_tm_cyclone_sand_water_flow       <- adapter(train[].sensor_sand_water_flow)
agg_tm_cyclone_feed_flow             <- adapter(train[].sensor_feed_flow)
agg_tm_cyclone_sand_valve_setpoint   <- adapter(train[].sensor_sand_valve_setpoint)
agg_tm_cyclone_sand_valve_feedback   <- adapter(train[].sensor_sand_valve_feedback)
agg_tm_cyclone_pool_valve_setpoint   <- adapter(train[].sensor_pool_valve_setpoint)
agg_tm_cyclone_pool_level            <- adapter(train[].sensor_pool_level)
agg_tm_cyclone_overflow_pool_level   <- adapter(overflow_pool[].sensor_level)
agg_tm_overflow_pump_current         <- adapter(overflow_pump[].sensor_current)
```

同时推荐输出 `tm_cyclone_feed_pressure` 和 `tm_cyclone_open_count`。它们比单纯的流量均值更能描述旋流器分级状态，尤其用于区分“高流量但开台多”和“低开台过载”的两类工况。

说明：旋流器组、塔磨机组、泵池和溢流泵池先在内部保留分组状态，最后再映射为 `agg_tm_*`。

## 10. 浮选段

第一版实现用段级 CSTR，不直接做 16 台或 18 台槽逐槽矿物平衡。

仿真对象只包括新1#、新2#新浮选系统。老系统数据可用于理解工厂混运背景，但不进入 `y_fx_xin1/2` 标定。

新浮选系统设备边界：

```text
series in {new1, new2}
cell_volume_nominal = 70 m3
rougher: 5 cells
cleaner: 3 cells
scav1: 4 cells
scav2: 3 cells
scav3: 3 cells
```

段级 CSTR 的有效体积：

```text
V_stage = n_cells_stage * 70 m3 * eta_effective_volume_stage
tau_stage_h = V_stage / max(Q_stage_m3_h, eps)
tau_stage_min = 60*tau_stage_h
```

流程考查 2#系统的停留时间锚点可作为第一版校准参考：

| 段 | 停留时间参考 |
|---|---:|
| 粗选 | 约 39 min |
| 精选 | 约 35 min |
| 一扫 | 约 28 min |
| 二扫 | 约 27 min |
| 三扫 | 约 42 min |

老系统 BFⅡ-16 的槽容、台数、自吸气机理、停留时间不进入本段公式。

默认标定目标：

| 场景 | 浮给 TFe | 浮给浓度 | 浮精 TFe | 浮尾 TFe | 说明 |
|---|---:|---:|---:|---:|---|
| 新2#流程考查良好工况 | 约 44.28% | 质量浓度统一按 40%-42% | 约 67.06% | 约 20.70%，范围约 17.6%-22.8% | 默认良好工况锚点 |
| 新1#调试较好工况 | 默认按 44%-45% | 质量浓度统一按 40%-42% | 约 68% | 约 23%-24% | 系列差异锚点 |
| 新系统较差/调试波动 | 约 45% | 可高于设计 38%-40% | 65%-67% | 可升至 25%-30% | 覆盖扰动场景 |

旧系统约 18% 的低浮尾品位不作为新系统必须覆盖的默认标定目标。若需要全厂综合尾矿或混运背景，应在系统外另建汇总层。

浮选给矿浓度统一解释为固体质量浓度 `C`。若报告、DCS 或原始表中出现其他浓度口径或密度口径，必须先通过配置显式转换为 `C` 后再进入公式；不得把不同口径的“浓度”直接混用。

系列偏置默认关闭。若需要让新1#和新2#在相同给矿下保持不同运行风格，必须通过 `series_bias[new1/new2]` 在配置中显式给出，并标注参数可信度等级；不能在公式里写隐含常数。

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

浮选前浓缩机必须提供显式滞后。第一版不使用纯固定延迟，而使用 CSTR/多级 CSTR 混合滞后：

```text
tau_flo_pre_thickener = V_effective / max(Q_in, eps)
NT_state = CSTR_or_N_stage_CSTR(TMOverflow_delayed, tau_flo_pre_thickener)
```

默认参数在没有更详细容积和液位数据时设为可配置范围：

```text
tau_flo_pre_thickener in [0.5 h, 3 h]
```

后续用塔磨溢流浓度/流量变化与浮选给矿浓度/流量变化的互相关反标定。该滞后属于工艺物料滞后，不是化验报出滞后。

### 10.2 药剂和 pH

```text
f_drug_j = ZOH(f_drug_j, f_drug_sp_j, tau_drug) + noise
Q_drug_j_ml_s = max(k_pump_j*f_drug_j*health_j + noise, 0)
dose_j_kg_t = Q_drug_j_ml_s*3.6*rho_drug_j_kg_L*active_j/max(M_feed_solid_tph,eps)

OH_effect = k_naoh*dose_naoh_kg_t + k_cao_oh*dose_cao_kg_t
Ca2_effect = k_cao_ca*dose_cao_kg_t
buffer_capacity = b0 + b_carb*r_carb + b_sil*r_sil + b_C*C_under
pH_ss = pH_base + k_pH*log1p(OH_effect/max(buffer_capacity,eps))
pH = ZOH(pH,pH_ss,tau_pH) + noise
```

药剂 DCS 默认保留现场泵流量/泵频，`dose_kg_t` 是内部机理量。报告给出单系统药剂表，可作为第一版换算锚点：

药剂换算单位不得省略：

```text
Q_drug_j_ml_s: 药剂泵流量，mL/s
rho_drug_j_kg_L: 药剂溶液密度，kg/L
active_j: 有效成分质量分数，0-1
M_feed_solid_tph: 当前系列浮选给矿干矿量，t/h
3.6 = 3600 s/h / 1000 mL/L
dose_j_kg_t: 有效成分单耗，kg/t 干矿
```

如果实现中使用 `rho_drug_j_kg_m3`，则换算系数不能再用 `3.6`，必须改为 `0.0036`。`active_j` 只能乘一次，不能把“药剂浓度百分比”和“有效成分分数”重复计入。

| 药剂 | 浓度 | 用量 | 单耗锚点 |
|---|---:|---:|---:|
| NaOH | 20% | 约 200 mL/s | 约 1.01 kg/t |
| DF+K6 抑制剂 | 3% | 约 400-600 mL/s | 约 0.30-0.45 kg/t |
| CaO | 2.5% | 约 1000-1600 mL/s | 约 0.63-1.01 kg/t |
| TD-II 粗选 | 6% | 约 400-600 mL/s | 约 0.61-0.91 kg/t |
| TD-II 精选 | 6% | 约 200-250 mL/s | 约 0.31-0.39 kg/t |

`DF+K6` 是抑制剂体系，不得拆成语义不明的独立 K6 变量。如需要抑制剂药箱液位，应命名为 `DF_K6_tank_level` 或相同语义。

CaO 不与 NaOH 完全等效。CaO 同时提供 OH- 和 Ca2+，其中 Ca2+ 通过活化/矿物表面环境影响脉石可浮性；NaOH 主要进入 pH/OH 路径。浮选速率中应允许 `Ca2_effect` 单独影响碳酸盐/硅酸盐回收和选择性。

### 10.3 反浮选速率

```text
E_collector = sigmoid(a1*(dose_collector-dose_low))*sigmoid(a2*(dose_high-dose_collector))
E_pH = exp(-((pH-pH_opt)/sigma_pH)^2)
E_air = sigmoid(k1*(Q_air-Q_low))*sigmoid(k2*(Q_high-Q_air))
E_density = exp(-((C-C_opt)/sigma_C)^2)
E_size = sigmoid(k_size*(F325-F325_min))

k_float_gangue = k0_g*E_collector*E_pH*E_air*E_density*E_size
k_float_sil = k_float_gangue*(1+a_sil*r_sil) * E_Ca2_sil(Ca2_effect)
k_float_carb = k_float_gangue*(1+a_carb*r_carb) * E_Ca2_carb(Ca2_effect)
k_float_Fe = k0_Fe*(1-E_depressant(dose_starch))*entrainment_factor
```

停留时间和分流：

```text
tau_stage_h = V_stage/max(Q_stage_m3_h,eps)
tau_stage_min = 60*tau_stage_h
R_float_j = 1-exp(-k_float_j_h_inv*tau_stage_h)
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

浮选 DCS 输出适配：

```text
series[s].sensor_ph = series[s].pH + noise
series[s].sensor_drug_pump[j] = sensor(series[s].reagent_pump[j])
series[s].stage[stage].sensor_level = L_stage + noise
series[s].stage[stage].sensor_air_flow = Q_air + noise
series[s].stage[stage].sensor_froth_h = h_froth + noise
series[s].stage[stage].sensor_motor_current = I0 + k_rho*(rho-rho_ref) + k_mu*(mu-mu_ref) + k_air*Q_air + noise

DCSOutputAdapter:
  fx_new1_* <- series[new1] sensors
  fx_new2_* <- series[new2] sensors
  optional agg_fx_* compatibility columns
```

浮选 DCS 不再输出老系统点位。新1#/新2#每个系列至少应有如下源状态：

```text
series[s].sensor_feed_flow
series[s].sensor_feed_density
series[s].sensor_ph
series[s].sensor_nt_underflow_conc
series[s].sensor_nt_current

series[s].reagent_pump[NaOH].sensor_flow_or_freq
series[s].reagent_pump[DF_K6].sensor_flow_or_freq
series[s].reagent_pump[CaO].sensor_flow_or_freq
series[s].reagent_pump[TD_rougher].sensor_flow_or_freq
series[s].reagent_pump[TD_cleaner].sensor_flow_or_freq

series[s].stage[rougher].sensor_level
series[s].stage[rougher].sensor_air_flow
series[s].stage[rougher].sensor_froth_h
series[s].stage[rougher].sensor_motor_current
series[s].stage[cleaner].sensor_level
series[s].stage[cleaner].sensor_air_flow
series[s].stage[cleaner].sensor_froth_h
series[s].stage[cleaner].sensor_motor_current
series[s].stage[scav1/2/3].sensor_level
series[s].stage[scav1/2/3].sensor_air_flow
series[s].stage[scav1/2/3].sensor_froth_h
series[s].stage[scav1/2/3].sensor_motor_current

series[s].sump[k].sensor_level
series[s].sump[k].sensor_pump_freq
series[s].sump[k].sensor_pump_current
```

推荐输出列口径：

```text
fx_new{s}_feed_flow
fx_new{s}_feed_density
fx_new{s}_ph
fx_new{s}_nt_underflow_conc
fx_new{s}_nt_current
fx_new{s}_naoh_pump_flow
fx_new{s}_df_k6_pump_flow
fx_new{s}_cao_pump_flow
fx_new{s}_td_rougher_pump_flow
fx_new{s}_td_cleaner_pump_flow
fx_new{s}_{stage}_level
fx_new{s}_{stage}_air_flow
fx_new{s}_{stage}_froth_h
fx_new{s}_{stage}_motor_current
fx_new{s}_sump{k}_level
fx_new{s}_sump{k}_pump_freq
fx_new{s}_sump{k}_pump_current
```

`dose_kg_t`、`OH_effect`、`Ca2_effect`、`hydrophobic_load`、`k_float_*` 是内部机理量，默认不作为 DCS 特征输出。若为了调试输出，必须放入 `debug_hidden` 或 `optional_diagnostic_features`，不能混入默认在线特征。

说明：浮选段只仿真新1#和新2#。新旧系统差异不通过聚合平均处理；老系统指标不用于校准 `y_fx_xin1/2`。

最终标签：

```text
y_fx_xin_s_true = 100*TFe(cleaner_froth_s)
y_fx_xin_s = y_fx_xin_s_true + N(0,sigma_y)
```

`y_fx_xin_s_true` 是每个仿真时间步的即时理论真值，用于评价即时软测量算法。`y_fx_xin_s` 是写入训练/评估表的最终标签；默认 `sigma_y = 0`，只有在明确需要模拟标签观测噪声时才设为非零。采样型化验值另由 `lab_flo_conc_tfe_s1/s2` 输出；两者语义不同，不要求 `y_fx_xin_s` 在非采样时刻为 `NaN`。

## 11. 过程化验

过程化验是仿真输出，不是 DCS 在线特征。用户当前需求保留 30-60 min 的采样间隔，即使现场实际可能更接近日/班次采样；这是数据生成策略选择，不作为真实现场采样频率声明。

采样策略：

```text
if sample_time(var):
    lab_var = 100*true_fraction_at_sample_point + N(0,sigma_assay) + N(0,sigma_sampling)
else:
    lab_var = NaN
```

待确认样点必须通过配置绑定，不能在公式中硬写：

```text
lab_sample_point_map = {
  "cuxiyi": "boundary_mixed" | "tm_overflow" | "manual_disabled",
  "29m_1":  "tm_cyclone_train_1_overflow" | "manual_disabled",
  "29m_2":  "tm_cyclone_train_2_overflow" | "manual_disabled",
  "29m_3":  "tm_cyclone_train_3_overflow" | "manual_disabled",
  "29m_4":  "tm_cyclone_train_4_overflow" | "manual_disabled",
  "38m":    "tm_overflow_mixed" | "manual_disabled"
}
```

默认配置为 `manual_disabled`。确认取样口之前，不允许用相近流程点“硬凑”这些化验列。

默认输出：

命名约定：`_s1` 等价于 `new1`，`_s2` 等价于 `new2`。后续若输出列同时存在 `s1/s2` 和 `new1/new2` 两套命名，必须在列目录中声明一一映射，不能让两者代表不同系列。

```text
入口边界:
lab_1_eryi_f200, lab_1_eryi_tfe
lab_2_eryi_f200, lab_2_eryi_tfe
lab_3_eryi_f200, lab_3_eryi_tfe
lab_cuxiyi_tfe, lab_cuxiyi_mag_fe, lab_cuxiyi_feo, lab_cuxiyi_carb_fe

磁选:
lab_mag_wm_conc_tfe, lab_mag_wm_tail_tfe
lab_mag_hm_conc_tfe, lab_mag_hm_tail_tfe
lab_mag_sw_conc_tfe, lab_mag_sw_tail_tfe
lab_mag_mixed_conc_tfe
lab_mag_tube_conc_tfe, lab_mag_tube_yield

塔磨:
lab_tm_feed_f325, lab_tm_discharge_f325
lab_tm_overflow_f325, lab_tm_overflow_tfe, lab_tm_overflow_conc
lab_tm_sand_f325

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

关键口径：

- `y_fx_xin1/2` 默认等于即时理论真值；只有显式设置 `sigma_y>0` 时才叠加标签观测噪声。它用于验证即时软测量算法，不模拟化验报出滞后。
- 如未来需要真实报出流程，可另输出 `lab_flo_conc_tfe_reported_s1/s2` 并设置 1-4 h 报出滞后，但默认不启用。
- `lab_mag_tube_yield` 和 `lab_mag_tube_conc_tfe` 来自标准条件磁选管试验代理，不是生产 DCS。它们可用于质检或辅助标签，默认不进入 DCS 主特征集。
- `lab_*_feo` 必须来自 `FeO_proxy` 或 `Fe2_mass` 代理，不得由最终精矿品位拟合。若对应取样点没有物相状态，变量应为 `NaN` 或 `manual_disabled`，不能硬凑。

磁选管试验第一版只作为辅助标签，公式必须保持低权重、可禁用：

```text
R_tube = sigmoid(a0
               + a_mag*r_mag
               + a_lib*Liberation_fe
               - a_carb*r_carb
               - a_sil*r_sil)

lab_mag_tube_yield = clip(Y0 + kY*R_tube + noise, 0, 1)
lab_mag_tube_conc_tfe = clip(TFe_feed + dG_tube*R_tube - k_ent*gangue_entrainment + noise, 0, 1)
```

由于当前没有真实磁选管试验序列支撑，`lab_mag_tube_*` 不参与主目标校准，也不用于决定磁选生产回收率。它只能从入口可选性代理生成，不能反过来调整强磁/扫强磁实际产品。

## 12. 校准目标与参数可信度

### 12.1 分模块校准目标

| 模块 | 默认现场/良好工况目标 | 波动/异常覆盖 | 备注 |
|---|---|---|---|
| 入口边界 | 原矿/入口 TFe 约 31%-32%，二溢浓度均值 38%-40%，`-200目` 均值约 77% | 浓度约 19%-42%，粒度约 74%-83% | 设计窗口不是默认现场均值 |
| 弱磁 | 弱精约 50%-52%，弱尾约 23%-26% | 浓度偏高时弱尾和夹带波动增加 | 运行台数 3-11 台 |
| 强磁前浓缩 | 调试实际强磁给矿浓度约 30.30%；良好控制 42%-47% | 浓缩机/底流泵异常导致浓度偏离 | 低浓度场景不能强行固定指标 |
| 强磁 | 强精约 39%-41%，强尾约 14%-16% | 电流、液位、冲洗水、除渣筛状态导致波动 | 与扫强磁分开建模 |
| 扫强磁 | 扫强精约 30%-31%，扫强尾约 7%-8% | 微细粒铁损失、碳酸铁/硅酸铁升高 | 给矿浓度窗口约 17%-22% |
| 混磁精矿 | TFe 约 43%-44%，保留碳酸铁/硅酸铁富集 | 有害铁矿物富集倍数约 1.29-1.93 | 传给塔磨/浮选 |
| 塔磨/三次分级 | 旋溢 `-325目` 良好工况约 90%-93%，流程考查可到约 93% | 覆盖约 83%-95%；压力异常可至约 0.84 MPa | 功率不应由处理量线性主导 |
| 浮选新1#/新2# | 浮精约 67%，新2#流程考查浮尾约 20.70% | 新系统尾矿可覆盖约 20%-30% | 不用老系统指标校准 |
| 过程化验 | 按采样时刻输出真值加采样/化验误差 | 未确认点位输出 `NaN` | 默认不进 DCS 主特征 |

### 12.2 参数可信度分级

为避免“参数很多但任意可调”，实现时每个参数必须标注来源等级：

| 等级 | 含义 | 示例 |
|---|---|---|
| A 实测锚点 | 来自报告流程考查/调试表，可直接作为均值、范围或锚点 | 浮精 67.06%、浮尾 20.70%、扫强尾 7.30%、旋溢解离度 79.09% |
| B 设备设计 | 来自设备规格或工艺设计值 | 设备台数、槽容积、设计浓度窗口、塔磨装球量 |
| C 工艺先验 | 有明确机理方向，但缺少本厂直接数据 | WI 范围、介质磨耗、浓缩机有效滞后 |
| D 调参占位 | 仅用于让模型可运行，必须在配置中标明并限制范围 | 部分速率常数、噪声强度、故障概率 |
| E 禁止/待确认 | 没有点位或语义不清，默认不输出或不进训练 | 未确认 `29m*`、`38m`、无法映射的 `lab_*_feo` |

参数调试顺序必须从 A/B 约束开始，再调 C/D；不能用 D 级参数覆盖 A 级实测矛盾。

参数配置表必须保留以下元数据：

```text
Parameter = {
  name,
  module,
  value,
  unit,
  allowed_range,
  trust_level in {A,B,C,D,E},
  source_doc,
  source_note,
  enabled,
  calibration_role
}
```

`calibration_role` 建议取值：

```text
anchor_mean        # 用于均值锚定
anchor_range       # 用于范围约束
shape_prior        # 决定趋势形状，如非单调药剂效应
noise_model        # 噪声/漂移/故障
scenario_switch    # 场景切换或异常概率
disabled_pending   # 待确认，不参与运行
```

第一版实现允许把该表写在配置文件、CSV 或 YAML 中；但不能只散落在代码常量里。所有 D 级参数必须有 `allowed_range`，所有 E 级参数默认 `enabled=false`。

### 12.3 验收方向

G1 的严格数值阈值可后续再定，但当前实现至少要满足：

- 单个 DCS 变量不能近乎直接复现 `y_fx_xin1/2`。
- 多变量时间窗口模型应明显优于单时刻、少变量模型。
- 改变入口粒度、有害矿物、浓度或设备台数时，影响应沿磁选、塔磨、浮选产生合理滞后。
- `agg_*` 列只允许由 `DCSOutputAdapter` 生成，不允许回流进机理公式。

## 13. 代码重构路线

### 阶段 0：保留现状，增加基础结构

目标：

- 新增 `Stream` 辅助结构或等价字典工具。
- 新增组分质量计算工具。
- 新增过程化验 sampler 框架。
- 新增 `DCSOutputAdapter` 框架；短期可继续写旧 `agg_*`，但标记为输出适配结果。
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
- 内部维护弱磁、强磁、扫强磁运行台数和设备组状态；DCS 继续保持现有列名，但通过输出适配器由设备状态生成。

验收：

- 弱精、弱尾、强精、强尾、扫强精、扫强尾、混磁精均值接近报告目标。
- 磁选 DCS 与混磁品位呈滞后弱/中相关，而非直接反推。

### 阶段 3：塔磨替换

目标：

- 建立泵池、旋流器、返砂、塔磨功率和粒度闭路。
- 输出三次分级溢流组分和 F325。
- 内部维护塔磨机组、旋流器组、泵池和溢流泵池状态；`agg_tm_*` 只在输出适配器中生成。

验收：

- 溢流 `-325目` 平均约 89%-92%，能覆盖 83%-95%。
- 泵池液位、给矿压力、功率、电流与负荷/粒度相关。

### 阶段 4：浮选替换

目标：

- 明确只仿真新1#和新2#浮选系列，老系统不进入浮选机理。
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

## 14. 是否需要保留旧 redesign 文档

建议保留，但不作为实现依据：

- `DESIGN_V2_COMPLETE.md`：实现依据。
- `00~07`：推导依据、公式来源、讨论记录。

实现时如果 `DESIGN_V2_COMPLETE.md` 与其他 redesign 文档冲突，以本文为准。
