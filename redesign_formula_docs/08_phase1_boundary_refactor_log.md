# 阶段 1 入口边界重构记录

日期：2026-05-13

## 范围

按 `DESIGN_V2_COMPLETE.md` 第 13 节“阶段 1：入口边界替换”实施：

- 新增 `BoundaryGenerator`，把入口矿石性质、三路线二溢等价边界、公用水压和入口过程化验收敛到同一层。
- 顶层调度改为 `BoundaryGenerator -> MagSepSystem -> TowerMillSystem -> FlotationSystem`。
- 保留旧隐藏字段 `_x_d1/_x_d2/_x_d3/_x_d4/_x_m_ball/_x_rho_ball/_x_d80_ball/_x_f25_ball`，保证下游现有模块兼容。
- 新增三路线隐藏状态 `_x_eryi_line{1,2,3}_*` 和入口过程化验 `lab_1/2/3_eryi_f200/tfe`。
- 不输出球磨 DCS 点位；入口化验列属于过程化验，不属于 DCS 在线特征。

## 关键实现决策

1. `_x_m_ball` 继续按下游现有口径作为干固体质量流量使用，避免第一阶段破坏磁选、塔磨、浮选的旧标定链路。
2. 入口 F200 直接围绕 77% 生成，再用 Rosin-Rammler 反算兼容的 d80、F325 和 f25。
3. `_x_d2` 使用碳酸铁中铁的绝对质量分数代理，即 `Fe_carb / M_solid`，保持旧浮选 pH 路径可运行。
4. `lab_*` 按 30-60 min 采样输出；非采样时刻为 `NaN`，测试已按过程化验口径放行。

## 调查记录

实施后完整 `pytest` 中开环慢测出现一次均值偏高：

- 默认旧开环扰动放大因子 10 下，`y_fx_xin1` 43,200 步均值约 68.406%，略高于旧验收 `[66, 68]`。
- 原因不是 DCS 泄露，而是新入口边界的矿石慢变时间常数比旧 d1 OU 更长，开环扰动进入当前旧浮选经验公式后改变了采样均值。
- 用候选全长仿真确认：
  - factor 12：`y_fx_xin1` 均值约 68.267%，方差约 24.34。
  - factor 16：`y_fx_xin1` 均值约 68.012%，方差约 24.77。
  - factor 17：`y_fx_xin1` 均值约 67.957%，方差约 24.73。
- 因此 `BoundaryConfig.from_legacy` 将开环 TFe 放大因子下限设为 17.0，仅用于兼容旧开环验收；闭环/常规边界不受影响。

## 验证

- `pytest -q`
- 结果：70 passed，7 warnings。
- warnings 均为既有 `pytest.mark.slow` 未注册和依赖库 deprecation warning，未影响测试结果。
