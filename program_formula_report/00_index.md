# 程序反推公式报告索引

本报告只以仿真程序文件为准反推数学关系。未读取以下文件：`design.md`、`plan.md`、`README.md`、`requirements.txt`、`REVIEW_ISSUES.md`、`预演.md`、`选矿仿真系统设计文档.md`。

已读取的公式来源主要是：

- `sim/config.py`
- `sim/simulator.py`
- `sim/rng.py`
- `sim/layers/disturbance.py`
- `sim/layers/ball_mill.py`
- `sim/layers/mag_sep.py`
- `sim/layers/tower_mill.py`
- `sim/layers/flotation.py`
- `sim/utils/buffer.py`
- `sim/utils/pid.py`
- `sim/utils/sensor.py`
- `sim/utils/thermal.py`
- `scripts/run_simulation.py`
- `scripts/calibrate.py`

## 文档结构

- [01_common_models.md](01_common_models.md)：公共随机过程、传感器、PID、缓冲、热模型、调度顺序。
- [02_disturbance_and_ball_mill.md](02_disturbance_and_ball_mill.md)：外生扰动和球磨溢流边界输入。
- [03_magnetic_separation.md](03_magnetic_separation.md)：弱磁、强磁、扫强磁、混磁精矿、磁选 DCS 量。
- [04_tower_mill.md](04_tower_mill.md)：塔磨给矿泵池、旋流器、塔磨功率、粒度、温度、电流和溢流。
- [05_flotation.md](05_flotation.md)：浮选浓缩、加药、pH、TFe、浮选槽、泡沫、泵池、化验标签。

## 全局仿真顺序

单步调度顺序来自 `sim/simulator.py`：

1. `DisturbanceLayer.step` 生成 `_x_d1` 到 `_x_d4`。
2. `BallMillInput.step` 生成 `_x_m_ball`、`_x_rho_ball`、`_x_d80_ball`、`_x_f25_ball`。
3. `MagSepSystem.step` 生成磁选 DCS 量和 `_x_g_mag`、`_x_m_mag`。
4. `TowerMillSystem.step` 生成塔磨 DCS 量和 `_x_f325_ov`、`_x_m_ov`、`_x_g_ov`、`_x_P_mech`、`_x_alpha_ov`。
5. `FlotationSystem.step` 生成浮选 DCS 量、`y_fx_xin1/2` 和若干隐藏测试量。

默认步长为 `dt = 60 s`，默认步数 `n_steps = 43200`，默认预热步数 `warm_up_steps = 300`。
