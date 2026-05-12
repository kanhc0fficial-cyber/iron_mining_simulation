# 东鞍山选矿全流程DCS仿真系统

基于物理机理的选矿全流程 DCS 仿真系统，用于生成含物理耦合的时间序列数据，
训练精矿品位（TFe）软测量模型。

## 项目结构

```
iron_mining_simulation/
├── plan.md                   # 三步实施计划
├── requirements.txt
├── sim/
│   ├── config.py             # 全局参数（唯一参数入口）
│   ├── rng.py                # 可复现随机数管理
│   ├── simulator.py          # 顶层编排器
│   ├── layers/
│   │   ├── disturbance.py    # 第0层：外生扰动（OU过程）
│   │   ├── ball_mill.py      # 球磨溢流边界输入
│   │   └── mag_sep.py        # 磁选段（12个DCS变量）
│   ├── utils/
│   │   ├── buffer.py         # RingBuffer（时滞缓冲）
│   │   ├── pid.py            # 离散PID控制器
│   │   ├── thermal.py        # 热力学一阶ODE
│   │   └── sensor.py         # 传感器噪声/漂移/故障
│   └── output/
│       ├── schema.py         # 输出列名注册表
│       └── writer.py         # 增量写 Parquet/CSV
├── scripts/
│   ├── run_simulation.py     # CLI入口
│   └── calibrate.py          # 标定点断言
└── tests/
    ├── test_disturbance.py
    └── test_mag_sep.py
```

## 快速开始

```bash
pip install -r requirements.txt

# 运行标定验证
python scripts/calibrate.py

# 运行100步快速验证
python scripts/run_simulation.py --steps 100

# 运行完整30天仿真
python scripts/run_simulation.py

# 单元测试
pytest tests/
```

## 仿真参数

| 参数 | 值 |
|------|-----|
| 仿真步长 | 60 s |
| 总步数 | 43,200（30天） |
| 输出变量 | ~200 个 DCS 变量 + 2 个 TFe 目标 |
| 运行时间目标 | < 5 min（单核） |

## 三步实施进度

- [x] **第一步**：脚手架 + 工具类 + 磁选段（12个DCS变量）
- [ ] **第二步**：塔磨段（18个DCS变量）
- [ ] **第三步**：浮选段（~170个DCS变量 + TFe目标）

详见 [plan.md](plan.md)。
