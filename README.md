# 东鞍山铁矿选矿全流程仿真系统

这是一个面向软测量建模和流程机理校验的选矿仿真工程。系统按东鞍山铁矿“入口边界 -> 磁选 -> 塔磨/三次分级 -> 新1#/新2#浮选 -> 过程化验/最终精矿品位”的流程生成时间序列数据。

当前版本可作为 **G1 / v1.0 仿真基线** 使用：全流程机理已接通，包含 DCS 在线变量、隐藏组分流、过程化验 `lab_*`、最终精矿品位标签 `y_fx_xin1/2`，并通过综合 pytest 验证。

## 适用范围

本软件用于生成更接近真实工艺逻辑的训练/验证数据，重点服务：

- 精矿 TFe 软测量模型训练与验证。
- 上游扰动、设备状态、药剂/pH/粒度/浓度对最终品位影响的仿真研究。
- 磁选、塔磨、浮选各段的质量平衡和过程化验一致性检查。
- DCS 特征泄漏检查，避免单个在线变量直接复现最终标签。

它不是现场 DCS、PLC 或生产调度系统，也不应直接用于真实生产控制决策。

## 环境准备

建议使用 Python 3.12 或 3.13。

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## 快速运行

运行 100 步快速验证，输出 Parquet：

```bash
python scripts/run_simulation.py --steps 100 --output output/quick.parquet
```

跳过预热并输出 CSV：

```bash
python scripts/run_simulation.py --steps 100 --no-warmup --format csv --output output/quick.csv
```

运行完整 30 天仿真，默认 43,200 步，步长 60 秒：

```bash
python scripts/run_simulation.py --output output/simulation.parquet
```

运行开环激励数据集，适合做建模和泄漏检查：

```bash
python scripts/run_simulation.py --open-loop --seed 42 --output output/open_loop.parquet
```

指定随机种子以保证复现：

```bash
python scripts/run_simulation.py --steps 1000 --seed 123 --output output/seed123.parquet
```

## 输出说明

输出文件由 `sim/output/schema.py` 注册列决定，写入 `.parquet` 或 `.csv`。隐藏字段 `_x_*` 不写入默认输出文件，只在仿真总线内部用于机理传递和测试。

主要输出类别：

- `STEP1_COLUMNS`：磁选段 DCS 变量。
- `STEP2_COLUMNS`：塔磨/三次分级 DCS 变量。
- `STEP3_COLUMNS`：浮选段 DCS 变量和最终标签。
- `PROCESS_LAB_COLUMNS`：过程化验变量，采样时刻有值，非采样时刻为 `NaN`。
- `y_fx_xin1`, `y_fx_xin2`：新1#/新2#最终精矿 TFe 标签，小数单位，例如 `0.67` 表示 67%。

过程化验 `lab_*` 为百分数单位，例如 `lab_flo_conc_tfe_s1 = 67.1` 表示 67.1%。这类变量不是在线 DCS 特征，训练在线软测量模型时应按任务需要决定是否纳入。

## 常用检查命令

运行磁选标定断言：

```bash
python scripts/calibrate.py
```

对仿真结果做泄漏检查：

```bash
python scripts/leakage_check.py --input output/open_loop.parquet --target y_fx_xin1 --top 12
```

如果希望检测到强代理变量时让命令失败：

```bash
python scripts/leakage_check.py --input output/open_loop.parquet --target y_fx_xin1 --check --max-single-r2 0.95
```

读取输出文件做简单预览：

```bash
python - <<'PY'
import pandas as pd

df = pd.read_parquet("output/simulation.parquet")
print(df.shape)
print(df[["y_fx_xin1", "y_fx_xin2", "lab_flo_conc_tfe_s1", "lab_tm_overflow_f325"]].describe())
PY
```

Windows PowerShell 可用：

```powershell
@'
import pandas as pd

df = pd.read_parquet("output/simulation.parquet")
print(df.shape)
print(df[["y_fx_xin1", "y_fx_xin2", "lab_flo_conc_tfe_s1", "lab_tm_overflow_f325"]].describe())
'@ | python -
```

## 测试

运行全部测试：

```bash
pytest -q
```

运行综合覆盖测试：

```bash
pytest tests/test_comprehensive_boundary.py `
       tests/test_comprehensive_mag_sep.py `
       tests/test_comprehensive_tower_mill.py `
       tests/test_comprehensive_flotation.py `
       tests/test_comprehensive_process_lab.py -q
```

Linux/macOS 写法：

```bash
pytest tests/test_comprehensive_boundary.py \
       tests/test_comprehensive_mag_sep.py \
       tests/test_comprehensive_tower_mill.py \
       tests/test_comprehensive_flotation.py \
       tests/test_comprehensive_process_lab.py -q
```

当前验收结果见 [TEST_REPORT.md](TEST_REPORT.md)：新增综合测试 395 项通过，原有测试 89 项通过，全套 484 项通过。

## 项目结构

```text
my_mining_simulation/
├── sim/
│   ├── config.py                 # 全局参数入口
│   ├── simulator.py              # 顶层流程编排
│   ├── rng.py                    # 可复现随机数管理
│   ├── layers/
│   │   ├── boundary.py           # 入口边界与三路线二溢样
│   │   ├── mag_sep.py            # 弱磁/强磁/扫强磁组分分流
│   │   ├── tower_mill.py         # 塔磨与三次分级
│   │   ├── flotation.py          # 新1#/新2#段级浮选
│   │   └── process_lab.py        # 确认点位过程化验 sampler
│   ├── output/
│   │   ├── schema.py             # 输出列注册表
│   │   └── writer.py             # Parquet/CSV 增量写入
│   ├── utils/                    # PID、缓冲、传感器、聚合等工具
│   └── validation/
│       └── leakage.py            # 校准与泄漏检查工具
├── scripts/
│   ├── run_simulation.py         # 仿真命令行入口
│   ├── calibrate.py              # 标定断言
│   └── leakage_check.py          # 泄漏检查命令行入口
├── tests/                        # 单元、集成、综合覆盖测试
├── redesign_formula_docs/        # 重构设计文档和阶段日志
└── TEST_REPORT.md                # 综合测试报告
```

## 当前基线与已知限制

当前版本已经可以作为阶段性成果收尾。报告中记录的已知限制不是阻塞问题：

- 入口 TFe 在短窗口、特定种子下可能有轻微均值下偏；长周期仿真影响较小。
- 故障注入是概率事件，短测试窗口不保证一定出现。
- 开环 PRBS 需要足够步数才稳定观测到两个水平。
- `粗细溢`、`29米*`、`38米` 等现场点位仍属未确认映射，未硬凑为 `lab_*` 输出。

后续如果拿到新的现场数据，建议进入单独的“现场校准版”迭代，而不是在缺少资料时继续凭感觉调参。

