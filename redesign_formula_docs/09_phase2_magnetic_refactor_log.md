# 阶段 2 磁选重构记录

日期：2026-05-14

## 范围

按 `DESIGN_V2_COMPLETE.md` 第 13 节“阶段 2：磁选替换”实施：

- 磁选核心从单一 TFe 标量分流改为 `Fe_mag / Fe_hem / Fe_carb / Fe_sil / Gangue` 五组分质量平衡。
- 入口边界混合流显式输出 `_x_boundary_fe_mag`、`_x_boundary_fe_hem`、`_x_boundary_fe_carb`、`_x_boundary_fe_sil`、`_x_boundary_gangue`、`_x_boundary_feo_proxy`。
- 磁选输出弱磁、强磁、扫强磁各段精矿/尾矿隐藏流：`_x_mag_wm_*`、`_x_mag_hm_*`、`_x_mag_sw_*`、`_x_mag_mixed_conc_*`。
- 保留下游兼容字段 `_x_g_mag` 和 `_x_m_mag`，并保证它们与混磁精矿组分流一致。
- 设备 DCS 聚合暂沿用当前 `agg_mag_*` 写法；本阶段不扩大到全局 `DCSOutputAdapter` 拆分。

## 关键实现决策

1. 弱磁、强磁和扫强磁均使用组分选择性向量分配目标铁回收量，再用夹带 gangue 量贴合该段品位锚点。
2. 强磁和扫强磁在机理层分开建模，分别输出段级隐藏状态和回收率诊断量。
3. 第一版解离度仍使用粒度经验锚定：混磁精矿 `Liberation_fe` 默认围绕约 67.51%，`Liberation_gangue` 默认围绕约 37.43%。
4. `_x_m_ball` 仍按现有下游语义作为固体干矿量兼容输入，避免阶段 2 同时重写塔磨/浮选。

## 调查记录

组分模型接入后，初始版本的弱磁和强磁锚点正常，但扫强磁沿用旧标量公式后出现偏高：

- 弱精均值约 51.49%，弱尾约 23.96%。
- 强精均值约 40.83%，强尾约 14.94%。
- 扫强精均值约 37.71%，高于设计目标 30%-31%。
- 混磁精均值约 45.01%，高于设计目标约 43%-44%。

处理方式：

- 增加 `sw_conc_grade_target = 0.31`，让扫强精第一版显式锚定到报告目标，而不是继续由旧标量公式外推。
- 将 `beta_sweep_Fe` 调整为 0.65，使扫强尾均值回到约 8.24%，混磁精均值约 43.12%。
- 该调整保持强磁/扫强磁为组分质量平衡，不通过最终品位反写 DCS。

## 验证

- `pytest tests/test_mag_sep.py tests/test_boundary.py -q`
- `pytest tests/test_tower_mill.py tests/test_flotation.py tests/test_integration.py::TestShortRun -q`
- `pytest tests/test_integration.py::TestOpenLoopStats -q`
- `pytest -q`

完整结果：

```text
75 passed, 7 warnings in 549.43s
```

warnings 为既有 `pytest.mark.slow` 未注册和依赖库 deprecation warning，未影响测试结果。
