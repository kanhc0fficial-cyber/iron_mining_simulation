# 阶段 3 塔磨/三次分级重构记录

日期：2026-05-14

## 范围

按 `DESIGN_V2_COMPLETE.md` 第 13 节“阶段 3：塔磨替换”推进：

- 塔磨段读取阶段 2 磁选输出的混磁精矿组分流。
- 为 `Fe_mag / Fe_hem / Fe_carb / Fe_sil / Gangue` 五组分建立磁选到塔磨的段间延迟缓冲。
- 输出三次分级给矿、溢流和沉砂隐藏流：
  - `_x_tm_cyclone_feed_*`
  - `_x_tm_cyclone_overflow_*`
  - `_x_tm_cyclone_sand_*`
  - `_x_tm_overflow_*`
- 保留旧兼容字段 `_x_m_ov`、`_x_g_ov`、`_x_f325_ov`，其中 `_x_m_ov` 仍保持旧浮选使用的湿态流量语义。

## 关键实现决策

1. 阶段 3 新增的 `_x_tm_overflow_*` 使用固体组分流口径；旧 `_x_m_ov` 暂不改为固体流量，避免提前破坏阶段 4 之前的浮选经验模型。
2. 旋流器给矿组分按当前泵量相对磁精矿入池量放大，用于表达返砂闭路造成的内循环负荷。
3. 旋流器溢流和沉砂先按 `alpha_ov` 做组分质量平衡拆分，第一版不引入未确认的组分选择性偏析。
4. 溢流解离度按 `F325_over - F325_feed` 和单位能耗提升；沉砂解离度按较粗粒级残余近似，避免把溢流/沉砂解离度简单复制为同一个值。

## 调查记录

阶段 3 接入后抽查 700 步边界-磁选-塔磨链路，后 300 步均值大致为：

- 三次分级给矿固体组分流约 2628 t/h。
- 三次分级溢流固体组分流约 602 t/h。
- 三次分级沉砂固体组分流约 2026 t/h。
- 溢流 TFe 与 `_x_g_ov` 一致，约 42.55%。
- 溢流 `F325` 约 93.13%。
- 溢流铁矿物解离度约 0.746，沉砂约 0.644，给矿约 0.674。

这些结果满足阶段 3 的核心方向：输出三次分级溢流组分和 F325，同时溢流/沉砂解离度不再简单复制给矿。

## 验证

- `pytest tests/test_tower_mill.py -q`
- `pytest tests/test_boundary.py tests/test_mag_sep.py tests/test_flotation.py tests/test_integration.py::TestShortRun -q`
- `pytest tests/test_integration.py::TestOpenLoopStats -q`

上述分组均已通过。完整测试另见本轮最终验证记录。
