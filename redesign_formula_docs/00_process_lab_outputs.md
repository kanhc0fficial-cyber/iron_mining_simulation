# 过程化验变量输出设计

版本：v0.1  
范围：定义仿真系统除 DCS 之外应输出的过程化验变量。  
原则：这些变量模拟现场“日常指标跟踪”和流程考查样，不必设置化验报出滞后，可按采样时刻直接写入。

## 目标

现有系统重点输出 DCS 变量和最终精矿品位 `y_fx_xin1/2`。后续应同时输出过程化验变量，使数据集既能训练软测量模型，也能支持流程机理校验。

图中样式对应的变量不是 DCS，而是人工取样/化验/粒度筛析/磁选管试验结果。例如：

- `1#二溢`、`2#二溢`、`3#二溢`：粒度 `-200目`、品位。
- `粗细溢`：品位、磁性铁、亚铁、碳酸铁。
- `磁选管`：管精品位、产率。
- 其他日常跟踪点：`29米1#`、`29米2#`、`29米3#`、`29米4#`、`38米`，建议先作为待确认取样口保留，不在未确认前强行绑定到某个流程节点。

## 仿真边界与取样口径

本仿真系统不模拟破碎和球磨内部设备。仿真入口是破碎和球磨已经完成后的边界结果，默认可理解为给入弱磁前的二次分级溢流/二溢等价流。

因此过程化验变量分三类：

| 类别 | 处理方式 | 例子 |
|---|---|---|
| 入口边界样 | 可以由边界发生器直接输出 | `1#二溢`、`2#二溢`、`3#二溢` |
| 仿真内部样 | 从磁选、塔磨、浮选隐藏状态输出 | 弱精、强尾、三次分级溢流、浮精、浮尾 |
| 待确认取样口 | 保留字段或用配置映射，未确认前不强行造数 | `粗细溢`、`29米1#`、`38米` 等 |

待确认样点采用配置绑定：

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

默认建议：

- `二溢` 按入口边界三路线输出，因为工厂报告明确二次分级溢流给入弱磁。
- `粗细溢`、`29米*`、`38米` 未经现场点位确认前输出 `NaN`，或者使用 `lab_unverified_*` 字段。
- 确认点位后再映射到入口边界或塔磨后三次分级溢流。

## 输出策略

过程化验变量按两类频率输出：

1. 高频过程样：按固定间隔或班次采样，例如每 30 min、60 min 或每班一次。
2. 流程考查样：按配置的考查窗口输出，覆盖磁选、塔磨、浮选各关键产品。

不设置化验滞后：

```text
若 t 是采样时刻:
    y_lab_var(t) = true_process_var(t) + lab_noise + sampling_noise
否则:
    y_lab_var(t) = NaN
```

其中 `sampling_noise` 表示取样缩分误差，`lab_noise` 表示化验误差。两者不应过大到掩盖工艺趋势，也不应为零。

## 过程化验变量清单

### 入口边界与分级样

| 变量名建议 | 含义 | 来源状态 |
|---|---|---|
| `lab_1_eryi_f200` | 1#二溢 `-200目` 含量 | 入口边界线 1 粒度 |
| `lab_1_eryi_tfe` | 1#二溢 TFe 品位 | 入口边界线 1 组分 |
| `lab_2_eryi_f200` | 2#二溢 `-200目` 含量 | 入口边界线 2 粒度 |
| `lab_2_eryi_tfe` | 2#二溢 TFe 品位 | 入口边界线 2 组分 |
| `lab_3_eryi_f200` | 3#二溢 `-200目` 含量 | 入口边界线 3 粒度 |
| `lab_3_eryi_tfe` | 3#二溢 TFe 品位 | 入口边界线 3 组分 |
| `lab_cuxiyi_tfe` | 粗细溢品位 | 待确认映射：入口混合样或塔磨溢流 |
| `lab_cuxiyi_mag_fe` | 粗细溢磁性铁 | 待确认映射后的组分 |
| `lab_cuxiyi_feo` | 粗细溢亚铁 | 待确认映射后的 FeO 代理 |
| `lab_cuxiyi_carb_fe` | 粗细溢碳酸铁 | 待确认映射后的碳酸铁组分 |

说明：

- 现有程序只生成总 `_x_d1`、`_x_d2`、`_x_d3`、`_x_d80_ball`、`_x_f25_ball`。后续应扩展为入口三路线边界状态，再汇总进入磁选。
- `磁性铁/亚铁/碳酸铁` 不应由最终精矿品位反推，而应来自入口边界或已确认取样口对应的矿物组成状态。

### 磁选样

| 变量名建议 | 含义 | 来源状态 |
|---|---|---|
| `lab_mag_wm_conc_tfe` | 弱精品位 | 弱磁精矿组分 |
| `lab_mag_wm_tail_tfe` | 弱尾品位 | 弱磁尾矿组分 |
| `lab_mag_hm_conc_tfe` | 强精品位 | 强磁精矿组分 |
| `lab_mag_hm_tail_tfe` | 强尾品位 | 强磁尾矿组分 |
| `lab_mag_sw_conc_tfe` | 扫强精品位 | 扫强磁精矿组分 |
| `lab_mag_sw_tail_tfe` | 扫强尾品位 | 扫强磁尾矿组分 |
| `lab_mag_mixed_conc_tfe` | 混磁精品位 | 三段磁精合并 |
| `lab_mag_tube_conc_tfe` | 磁选管管精品位 | 对给矿样的标准条件磁选管试验 |
| `lab_mag_tube_yield` | 磁选管产率 | 标准条件磁选管试验 |

磁选管试验不是生产设备 DCS，建议由给矿可选性生成：

```text
R_tube = sigmoid(a0 + a_mag*r_mag + a_lib*Liberation - a_carb*r_carb - a_sil*r_sil)
lab_mag_tube_yield = clip(Y0 + kY*R_tube + noise, 0, 1)
lab_mag_tube_conc_tfe = clip(G_feed + dG_tube*R_tube - k_ent*gangue_entrainment + noise, 0, 1)
```

### 塔磨与三次分级样

| 变量名建议 | 含义 | 来源状态 |
|---|---|---|
| `lab_tm_feed_f325` | 塔磨给矿 `-325目` | 混磁精矿进入三次分级前粒度 |
| `lab_tm_discharge_f325` | 塔磨排矿 `-325目` | 塔磨排矿粒度 |
| `lab_tm_overflow_f325` | 三次分级溢流 `-325目` | 旋流器溢流粒度 |
| `lab_tm_overflow_tfe` | 三次分级溢流品位 | 塔磨溢流组分 |
| `lab_tm_sand_f325` | 三次分级沉砂 `-325目` | 旋流器沉砂粒度 |
| `lab_tm_overflow_conc` | 三次分级溢流浓度 | 水固平衡 |

校准依据：

- 工厂报告称三次分级溢流粒度 `-325目` 在 83.65%-94.77% 之间，平均 89.51%，低于工艺要求 92%。
- 塔磨给矿 `-325目` 平均约 55.18%，排矿约 63.72%，提高幅度偏低。
- 磨矿浓度、旋流器给矿压力和处理量波动会影响粒度。

### 浮选样

| 变量名建议 | 含义 | 来源状态 |
|---|---|---|
| `lab_flo_feed_tfe_s1/s2` | 浮给品位 | 浮选前浓缩底流 |
| `lab_flo_feed_f325_s1/s2` | 浮给粒度 `-325目` | 三次分级溢流 |
| `lab_flo_conc_tfe_s1/s2` | 浮精品位 | 精选精矿 |
| `lab_flo_tail_tfe_s1/s2` | 浮尾品位 | 三扫尾矿 |
| `lab_flo_rough_conc_tfe_s1/s2` | 粗精品位 | 粗选泡沫 |
| `lab_flo_rough_tail_tfe_s1/s2` | 粗尾品位 | 粗选槽尾 |
| `lab_flo_clean_tail_tfe_s1/s2` | 精尾品位 | 精选尾矿 |
| `lab_flo_scav1_conc_tfe_s1/s2` | 一扫精品位 | 一扫泡沫 |
| `lab_flo_scav1_tail_tfe_s1/s2` | 一扫尾品位 | 一扫尾 |
| `lab_flo_scav2_conc_tfe_s1/s2` | 二扫精品位 | 二扫泡沫 |
| `lab_flo_scav2_tail_tfe_s1/s2` | 二扫尾品位 | 二扫尾 |
| `lab_flo_scav3_conc_tfe_s1/s2` | 三扫精品位 | 三扫泡沫 |
| `lab_flo_final_conc_yield_s1/s2` | 浮精产率 | 精矿质量/给矿质量 |
| `lab_flo_final_conc_recovery_s1/s2` | 浮精铁回收率 | 铁质量平衡 |

最终目标仍可保留：

```text
y_fx_xin1 = lab_flo_conc_tfe_s1
y_fx_xin2 = lab_flo_conc_tfe_s2
```

但建议同时输出 `lab_flo_conc_tfe_s1/s2`，保持“最终标签”和“过程化验”语义可分。

## 噪声与采样误差

```text
lab_value = true_value
          + N(0, sigma_assay)
          + N(0, sigma_sampling * sqrt(1 + k_heterogeneity*heterogeneity))
```

不同变量噪声建议：

- TFe 品位：0.10-0.30 个百分点。
- 粒度含量：0.5-1.5 个百分点。
- 磁性铁/亚铁/碳酸铁：0.05-0.20 个百分点，按变量量级调整。
- 产率/回收率：0.3-1.0 个百分点。

## 泄漏约束

1. 过程化验变量可以强预测最终精矿品位，因为它们本来就是化验样；但训练 DCS 软测量模型时应允许用户选择是否纳入这些变量。
2. 默认 DCS 特征集不包含 `lab_*` 变量。
3. `lab_*` 可作为辅助监督、数据质检、流程状态标签或多任务学习目标。
4. 所有 `lab_*` 必须来自对应时刻的隐藏组分和流程状态，不能由最终 `y_fx_xin` 反推。
