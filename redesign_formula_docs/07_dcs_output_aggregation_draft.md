# DCS 输出聚合层重新设计草稿

版本：v0.1-draft

定位：本文只规定仿真内部状态与最终 DCS 输出之间的边界。它不急于确定每个聚合变量到底取均值、最大值、加权均值还是总和，而是先避免一个更根本的问题：不要让聚合变量提前进入工艺机理公式。

## 核心结论

仿真内部不应提前聚合。

正确分层应为：

```text
真实工艺机理层：
  Stream、设备状态、系列状态、槽段状态
  -> 用这些非聚合状态计算物料流动、分选、磨矿、浮选

传感器层：
  对真实设备/槽段/泵/阀状态加噪声、漂移、故障和采样

DCS 输出适配层：
  按真实 DCS 标签或兼容列名，把多个传感器读数映射成最终 CSV/Parquet 列
```

`agg_*` 是最后一层输出列，不是仿真内部的真实设备。

因此模块公式中不应写：

```text
agg_mag_excit_current -> B_eff -> recovery
agg_tm_cyclone_feed_flow -> P_cyc
agg_fx_s1_air_flow -> flotation_rate
```

而应写：

```text
hm_device[i].I_exc -> hm_device[i].B_eff -> hm_device[i].recovery
tm_train[k].Q_feed -> tm_train[k].P_cyc -> classification
fx_series[s].stage[rougher].Q_air -> flotation_rate

最后：
DCSOutputAdapter(states) -> agg_* / raw-like DCS columns
```

## 为什么不能提前聚合

提前聚合会带来三个偏差：

1. 运行台数丢失。两台高负荷和六台低负荷可能均值相同，但分选停留时间、单机负荷、堵塞风险完全不同。
2. 工艺职责混淆。强磁和扫强磁都叫强磁机，但给矿性质、目标、浓度窗口和操作策略不同，不能先平均再参与回收率公式。
3. 目标泄漏检查会失真。一个过度聚合的变量可能看似“稳定、合理”，实际把多个可解释路径压缩成单一强代理，反而让软测量模型学到不真实的捷径。

仿真接近真实，不是让输出列越像 DCS 均值越早越好，而是让内部物料和设备状态先像真实流程一样传播，最后再模拟 DCS 系统如何看见它。

## 实现层次

### 1. 工艺物料层

继续使用统一 `Stream`：

```text
Stream = {
  M_solid, M_water, C,
  Fe_mag, Fe_hem, Fe_carb, Fe_sil, Gangue,
  TFe,
  F200, F325, f25, d80,
  Liberation_fe, Liberation_gangue,
  WI, clay
}
```

说明：

- `Liberation` 建议拆为铁矿物和脉石两个量，避免 D2 中“旋流器溢流细粒解离度应更高但被标量传递抹平”的问题。
- `Stream` 不保存 `agg_*`。

### 2. 设备状态层

并联设备用数组或列表保存，不提前合并：

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

对于不是单台设备的段级模型，也要保留系列和段：

```text
FlotationSeriesState = {
  series_id in {new1, new2},
  stage[rougher, cleaner, scav1, scav2, scav3],
  reagent_pumps,
  air_system,
  sumps,
  feed_thickener
}
```

### 3. 传感器层

传感器只读真实设备状态：

```text
sensor_value = true_value
             + drift(sensor_id, t)
             + noise(sensor_id, t)
             + optional_fault(sensor_id, t)
```

传感器层不得读取最终精矿品位、过程化验品位或未来时刻。

### 4. DCS 输出适配层

最后统一执行：

```text
DCSFrame = DCSOutputAdapter.step(
    BoundaryOut,
    MagOut.states,
    TMOut.states,
    FloOut.states,
    lab_outputs,
    y_true
)
```

适配器负责：

- 输出原始 DCS 风格列。
- 输出兼容旧代码的 `agg_*` 列。
- 可选输出诊断列，例如 `_on_count`、`_source_count`、`_std`、`_min`、`_max`。
- 执行特征集分层：默认训练特征、可选诊断特征、异常工况标志、默认禁用特征。

工艺模块不得反读适配器生成的 `agg_*`。

## 单步调度草稿

推荐改为：

```text
BoundaryGenerator.step(t)
MagSepSystem.step(BoundaryOut.mixed)
TowerMillSystem.step(MagOut.mixed_conc)
FlotationSystem.step(TMOut.cyclone_overflow)
ProcessLabSampler.step(BoundaryOut, MagOut, TMOut, FloOut)
DCSOutputAdapter.step(BoundaryOut, MagOut, TMOut, FloOut, lab_*, y_*)
Writer.step(DCSFrame, lab_*, y_*)
```

其中：

- `MagSepSystem`、`TowerMillSystem`、`FlotationSystem` 可以写调试状态，但不直接决定最终训练列。
- 如果为了兼容现有代码短期仍在 `bus` 中写 `agg_*`，必须标注为 adapter 输出，不能在下游公式中读取。

## 磁选段调整草稿

内部应拆成：

```text
WeakMagGroup:
  wm_unit[1..12]
  wm_units_on

HighIntensityMagGroup:
  hm_unit[1..10]
  hm_units_on

SweepHighIntensityMagGroup:
  sw_unit[1..10]
  sw_units_on
```

强磁与扫强磁分别计算：

```text
hm_unit[i].B_eff = f(hm_unit[i].I_exc, hm_unit[i].T_coil)
hm_unit[i].R_j = f(B_eff, C_hm_feed, load_i, level_i, pulse_i, ring_i, flush_i, clog_i)

sw_unit[i].B_eff = f(sw_unit[i].I_exc, sw_unit[i].T_coil)
sw_unit[i].R_j = f(B_eff, C_sw_feed, load_i, level_i, pulse_i, ring_i, flush_i, clog_i)
```

输出适配器再生成：

```text
agg_mag_excit_current          # 旧兼容列，可保留
agg_mag_hm_excit_current       # 推荐新列
agg_mag_sw_excit_current       # 推荐新列
hm_units_on
sw_units_on
```

这里是否取均值不是当前核心问题；核心是聚合只能发生在 `hm_unit[]` 和 `sw_unit[]` 已经各自完成分选之后。

## 塔磨与三次分级调整草稿

内部应拆成：

```text
TowerMillGroup:
  tm_unit[1..6]
  tm_units_on

CycloneTrainGroup:
  train[1..6]
  train[k].cyclone_count_on
  train[k].feed_pool
  train[k].feed_pump
  train[k].cyclone_overflow
  train[k].cyclone_sand
```

机理公式读取：

```text
train[k].Q_feed
train[k].P_feed
train[k].C_feed
train[k].cyclone_count_on
tm_unit[i].media_load
tm_unit[i].motor_current
```

而不是读取：

```text
agg_tm_cyclone_feed_flow
agg_tm_motor_current
```

输出适配器最后生成兼容列：

```text
agg_tm_cyclone_feed_flow
agg_tm_cyclone_pump_current
agg_tm_motor_current
agg_tm_cyclone_pool_level
```

同时可输出更清楚的新列：

```text
tm_units_on
tm_cyclone_trains_on
tm_cyclone_feed_flow_total
tm_cyclone_feed_flow_per_train
tm_motor_current_max
```

## 浮选段调整草稿

仿真范围只包括新1#和新2#：

```text
FlotationSystem:
  series[new1]
  series[new2]
```

老系统不进入浮选机理仿真。若真实工厂存在公用上游、公用水、药剂站或浓缩系统影响，可作为边界扰动或公用资源状态进入，但不得输出 `y_fx_old*`，也不得用老系统指标校准新1#/新2#。

每个新系列内部保留：

```text
series[s].feed_thickener
series[s].reagent_pump[NaOH, DF_K6, CaO, TD_rougher, TD_cleaner]
series[s].stage[rougher, cleaner, scav1, scav2, scav3]
series[s].sump[]
series[s].final_conc
series[s].final_tail
```

药剂处理建议：

```text
Q_reagent_ml_s = pump_sensor_or_controller(...)
dose_kg_t = Q_reagent_ml_s * 3.6 * rho_reagent * active_fraction / max(M_feed_solid_tph, eps)
```

说明：

- DCS 默认输出泵流量、泵频、pH、气量、液位等现场可见量。
- `dose_kg_t` 是内部机理量，用于浮选速率，不必作为默认 DCS 特征。
- `DF+K6` 应作为抑制剂药剂体系命名，不再写成没有来源解释的 `K6液位`。

## 事故泵与异常状态

事故泵、事故池、漫槽回打等变量不应作为正常工况的连续软测量主特征。

建议输出：

```text
event_accident_pump_active
event_accident_pump_load
```

默认训练集可以选择：

- 删除事故工况窗口。
- 或保留为异常场景，但显式带 `event_*` 标志。

不要让事故泵电流在正常公式中参与最终精矿品位生成。

## 输出名单草稿

### 默认保留的旧兼容列

旧 `agg_*` 可继续输出，以保持旧数据集列名兼容：

```text
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
```

但这些列只由输出适配器生成，后续机理公式不得读取它们。

### 推荐新增的语义列

磁选：

```text
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
```

塔磨：

```text
tm_units_on
tm_cyclone_trains_on
tm_cyclone_feed_flow_total
tm_cyclone_feed_pressure
tm_motor_current_max
tm_overflow_pool_level
```

浮选：

```text
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

这份名单仍是草稿。它解决的是“哪些物理对象应该可见”，不是最终决定每列如何做统计。

## 需要修改的文档口径

1. `DESIGN_V2_COMPLETE.md` 中的 DCS 公式应改为“设备状态公式 + 输出适配器”，不再直接写 `agg_* = true_state + noise` 作为机理公式。
2. `06_implementation_dataflow_equations.md` 的单步调度应插入 `DCSOutputAdapter.step`。
3. `01_magnetic_separation_redesign.md` 的 `agg_mag_*` 约束应改成：强磁、扫强磁内部状态分开，`agg_mag_*` 仅为输出兼容列。
4. `03_tower_mill_redesign.md` 的 `agg_tm_*` 说明应改成：塔磨/旋流器组状态先分开计算，输出层再映射。
5. `04_flotation_redesign.md` 应明确只仿真新1#/新2#，浮选 DCS 以系列和段级状态生成。

## 本草稿吸收的 review 精神

- F1/F2/F9：老系统不进入浮选仿真，只保留新1#和新2#。
- F5/F7：药剂 DCS 优先保留现场泵流量/泵频；`DF+K6` 是抑制剂体系，不应写成无来源的孤立变量。
- M5/M6：强磁、扫强磁、运行台数必须进入内部设备状态，不能只靠一个全厂平均 `agg_mag_*`。
- D1：浓缩机、泵池、闭路返砂等延迟应在工艺状态层表达，而不是靠输出 DCS 滞后凑出来。
- D2：解离度应随塔磨和分级改变，不能被一个全局标量一路传递。
- L1/L2：过程化验和内部 FeO/Fe2+ 代理不应被最终品位反推；不确定变量可以输出但默认不进 DCS 训练特征。

## 一句话实施标准

任何公式只要要影响物料、回收率、粒度、解离度、浮选速率，就必须读取 `Stream` 或设备/系列状态；任何 `agg_*` 只允许在 `DCSOutputAdapter` 中生成，并且只能用于最终输出和模型训练，不允许回流进仿真机理。
