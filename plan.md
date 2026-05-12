# 东鞍山选矿全流程DCS仿真系统 — 三步实施计划

## 设计评审摘要

本仿真工程目标：以 Python 单进程在 60 s 步长下仿真 ≥ 30 天，输出 ~200 个 DCS
时序变量与 2 个精矿品位目标变量（`y_fx_xin1/2`），用于训练 TFe 软测量模型。

**核心架构**：信号总线（`bus: dict`）驱动的流水线——外生扰动 → 球磨溢流边界 →
磁选段 → 塔磨段 → 浮选段 → 输出落盘。各子系统只通过 `bus` 交换信息，内部状态
完全封装。

**物理验证基准**（来自考查报告标定点）：
- 弱磁：给矿 31.49 % TFe → 精矿 51.29 %，作业回收率 45.23 %
- 强磁：给矿 23.91 % TFe → 精矿 40.73 %，回收率 67.99 %
- 混磁精矿：品位 43.84 %
- 塔磨溢流：−325 目 ≥ 92.5 %，旋流器分级效率 ≈ 24.81 %
- 浮选精矿：Q_TD = 2100 g/t → TFe ≈ 67.43 %；Q_TD = 1500 g/t → TFe ≈ 66.56 %

---

## 第一步：项目脚手架 + 工具类 + 磁选段

**范围**

搭建完整项目骨架，实现所有通用工具类，完成扰动层、球磨溢流边界层、磁选段，
并交付可独立运行的仿真器（仅运行前三段）与输出系统。

**交付物清单**

```
iron_mining_simulation/
├── requirements.txt
├── README.md
├── plan.md
├── sim/
│   ├── __init__.py
│   ├── config.py          # SimConfig / DisturbanceConfig / BallMillConfig / MagSepConfig
│   ├── rng.py             # RNGFactory（可复现随机流）
│   ├── simulator.py       # Simulator（此阶段只调度前三段）
│   ├── layers/
│   │   ├── disturbance.py # OU过程驱动的外生扰动 d1~d4
│   │   ├── ball_mill.py   # 球磨溢流 AR(1) 边界输入
│   │   └── mag_sep.py     # 磁选段全部物理 + 12个DCS变量
│   ├── utils/
│   │   ├── buffer.py      # RingBuffer（时滞循环缓冲）
│   │   ├── pid.py         # PIDController（离散，含反积分饱和）
│   │   ├── thermal.py     # FirstOrderThermal（前向欧拉ODE）
│   │   └── sensor.py      # add_noise / add_drift / inject_fault
│   └── output/
│       ├── schema.py      # 第一步输出列名注册（12个磁选DCS变量）
│       └── writer.py      # 增量写 Parquet / CSV（每1000行批写）
├── scripts/
│   ├── run_simulation.py  # CLI入口（argparse）
│   └── calibrate.py       # 磁选段标定点断言（不依赖运行仿真）
└── tests/
    ├── test_disturbance.py # 可复现性、物理范围约束
    └── test_mag_sep.py     # PID收敛、热力学稳态、标定点
```

**磁选段 12 个 DCS 输出变量**

| 变量名 | 物理含义 |
|--------|---------|
| `agg_mag_excit_voltage` | 励磁电压 |
| `agg_mag_excit_current` | 励磁电流 |
| `agg_mag_coil_temp` | 线圈温度 |
| `agg_mag_tailings_valve1` | 尾矿阀1开度 |
| `agg_mag_tailings_valve2` | 尾矿阀2开度 |
| `agg_mag_blowdown_valve` | 排污阀开度 |
| `agg_mag_pulsation_freq` | 脉动频率 |
| `agg_mag_ring_freq` | 转环频率 |
| `agg_mag_level` | 选矿液位 |
| `agg_mag_flush_water_pressure` | 冲矿水压力 |
| `agg_mag_motor_current_rc` | 主电机A相电流 |
| `agg_mag_motor_voltage_rc` | 主电机BC线电压 |

**验收标准**

- `python scripts/calibrate.py` 全部断言通过：
  - 弱磁：d1=0.3149 → g_wmag ≈ 51.29 % (±0.5 %)，β_wm ≈ 45.23 % (±1 %)
  - 强磁：g_feed=0.2391 → g_strong ≈ 40.73 % (±1 %)，β_strong ≈ 67.99 % (±1 %)
- `pytest tests/test_disturbance.py tests/test_mag_sep.py` 全部通过：
  - 相同 seed 产生完全相同的输出序列
  - 扰动变量值始终在物理可行范围内
  - 液位 PID 在 300 步（5 min）内稳定
  - T_coil 热力学稳态在 60~80 °C 之间
- `python scripts/run_simulation.py --steps 100` 无报错运行，
  输出 Parquet 文件包含 `t` + 12 个磁选 DCS 列，无 NaN / Inf

---

## 第二步：塔磨段

**范围**

在第一步基础上新增塔磨段（`TowerMillSystem`），实现段间时滞（磁选→塔磨
15~30 min），扩充输出至 30+ 个 DCS 变量。

**新增交付物**

```
sim/layers/tower_mill.py   # TowerMillSystem（18个DCS变量）
tests/test_tower_mill.py
```

**塔磨段 18 个 DCS 变量（新增）**

泵池液位、泵池水阀位给定、泵池加水流量、旋流器给矿管道流量、三旋给矿泵频率/
电流、沉砂水阀位给定/反馈、沉砂水流量、塔磨主电机电流、滑动轴承温度×2、
主电机定子温度×2、减速机油池温度、减速机出油口温度、溢流泵池液位、溢流泵电流。

**验收标准**

- 塔磨段标定断言通过：P_mech ∈ [730, 950] kW；f_{−325μm,ov} ≥ 92.5 %；
  旋流器分级效率 ≈ 24.81 % (±2 %)
- `pytest tests/test_tower_mill.py` 通过：
  - 轴承/定子/减速机温度稳态值在设计范围内（标定值 ±5 %）
  - 故障注入（p=0.002）：1000步内出现 −287.04 °C 异常值
- 30 天仿真运行成功，输出 ≥ 30 列，无 NaN / Inf

---

## 第三步：浮选段 + 全集成

**范围**

新增浮选段（`FlotationSystem`）——含两系列浮选槽（各 7 个槽）、加药网络、
pH 动力学、搅拌槽温度、泵池液位、`LabAssayer` 化验时滞——扩充至 ~200 个
DCS 变量 + 2 个目标变量，并实现开环激励模式（PRBS），完成全集成测试。

**新增交付物**

```
sim/layers/flotation.py    # FlotationSystem（~170个DCS变量 + y_fx_xin1/2）
sim/output/schema.py       # 更新：全量 ~200 列注册
tests/test_flotation.py
tests/test_integration.py
```

**验收标准**

- 浮选段标定断言通过：
  - Q_TD=2100 g/t → TFe ≈ 67.43 % (±0.5 %)，尾矿 ≈ 12.86 %
  - Q_TD=1500 g/t → TFe ≈ 66.56 % (±0.5 %)
  - 稳态 pH ∈ [9.2, 10.1]
- `pytest tests/test_integration.py` 通过：
  - 30 天完整仿真（43 200 步）运行时间 < 5 min（单核）
  - 输出 DataFrame 列数 ≥ 200，无缺失列，无 NaN/Inf（除 y_fx_xin1/2 的 NaN）
  - **开环模式**：TFe 方差 ≥ 4.0，均值 ∈ [66, 68] %
  - 传感器故障频率与文档一致（轴承 ≈ 0.2 %，泡沫层 ≈ 0.5 %）
