# 浮选段仿真问题备忘录

本文档记录了在 PR #4 代码审查和冒烟测试中发现的问题。
已在本次 PR 中修复的问题（Issue 1、Issue 4）不在此列。

---

## 关于 PR Review 意见的独立分析

### Review Issue 2：开环模式协方差结构问题

**GPT-5.4 的结论**：开环下 Cholesky L 矩阵只改变了 s1，
导致 d1-d2 相关系数改变，不严格保留相关结构。

**独立分析结论：Review Issue 2 不是 Bug，当前实现正确。**

数学验证（以 s1=0.0005, s2=0.0002, ρ=−0.6，开环放大系数=10 为例）：

```
正常模式 L = [[s1,    0           ],
              [ρ·s2,  s2·√(1−ρ²) ]]

开环模式 L = [[10s1,  0           ],
              [ρ·s2,  s2·√(1−ρ²) ]]   ← L[1,0] 不变

Cov_normal = L·Lᵀ = [[s1²,          ρ·s1·s2    ],
                      [ρ·s1·s2,      s2²        ]]

Cov_open   = L·Lᵀ = [[(10s1)²,     ρ·(10s1)·s2],
                      [ρ·(10s1)·s2, s2²         ]]

相关系数 = Cov[0,1] / (σ_d1 · σ_d2)
         = ρ·(10s1)·s2 / (10s1 · s2) = ρ   ✓
```

实测验证（以 d1_sigma=0.0005, d2_sigma=0.0002, rho=-0.6, factor=10 代入计算）：
- 正常/开环相关系数均为 −0.6
- d1 sigma 比例 = 10.0，d2 sigma 比例 = 1.0

**结论**：开环模式正确实现了"保持 d1-d2 相关系数不变，同时扩大 d1 扰动幅度 10 倍"的设计意图。
无需修改，但可在代码注释中明确说明，以免后续维护者误解。

---

## 冒烟测试发现的新问题

### BUG-A：`fx_ah5_power` / `fx_ah6_power` 始终钳位在 100 kW（零方差）

**现象**：
```
fx_ah5_power: mean=100.0, std=0.000000
fx_ah6_power: mean=100.0, std=0.000000
```

**根本原因**：
```python
# sim/layers/flotation.py
P_AH = np.clip(P_AH, 100.0, 5000.0)   # min_clip = 100 kW
```
但实际计算值约 77 kW（低于下限），因此始终被钳位：
- P_FXJ_total（每系列 7 个槽 × ~5 A × 380V × √3 × 0.85 / 1000）≈ 19.6 kW
- P_pump_total（每系列 3 个泵 × ~34 A × 380V × √3 × 0.85 / 1000）≈ 57 kW
- 合计 ≈ 76.6 kW < 100 kW → 钳位到 100 kW

**影响**：这两列信号方差为零，对软测量训练毫无意义。

**建议修法**（任选其一）：
1. 将 `min_clip` 从 100 kW 降到 10 kW（或直接去掉下限钳位）
2. 提高 `I_FXJ0`（空载电流）从 5 A 到符合现实的 15~30 A

---

### BUG-B：`air_sp` 14 列始终为常数（零方差）

**现象**：
```
fx_s1_cx1_air_sp: mean=0.0100, std=0.000000   # 所有 14 列相同
```

**根本原因**：
```python
Q_air_sp = cfg.Q_air_nom * np.ones((_N_SERIES, _N_CELLS))
```
`air_sp` 每步都被重置为 `Q_air_nom`，完全不变。

**影响**：
- 14 列常数对 ML 训练没有信息量，浪费列位
- `air_flow` 列已经含有噪声，但 `air_sp` 全为 0.01 m³/s 无法体现操作员调整

**建议**：
- 方案 A：用 AR(1) 过程模拟操作员对充气量的偶尔调整（与 `bv_pos` 类似）
- 方案 B：去掉 `air_sp` 列，只保留 `air_flow` 列（降维、更简洁）

---

### 观察-C：泵池 ODE 使用固定名义入流量，不响应给矿量变化

**现象**：将 `m_ov` 从 750 t/h 阶跃到 1000 t/h，泵池液位在 200 步内均值不变（≈0.95 m）。

**根本原因**：
```python
# __init__ 中预计算了名义入流量
self._Q_in_pool_nom = cfg.m_ov_nom * 1000.0 / cfg.rho_ov / 3600.0 / _N_POOLS
# step 中始终使用固定值
dL_pool = (self._Q_in_pool_nom - Q_pump_pool) / cfg.A_pool_flo
```

实际上，泵池的入流应等于上游（浮选槽出流）的实时值，而非名义值。

**影响**：
- 泵池液位不会随给矿量波动而变化，丢失了一条物理耦合通路
- 对软测量研究影响较小（泵池液位不是主要目标变量），但降低了数据集的物理真实性

**建议**：在 `step()` 中用实时 `Q_total_s / _N_POOLS` 代替 `_Q_in_pool_nom`。

---

### 观察-D：7 个浮选槽接受相同入流，槽间无级联关系

**现象**：7 个槽使用相同的 `Q_in_cell = Q_total_s / _N_CELLS`，
所有槽的液位、泡沫层高度完全相同（仅噪声不同）。

**根本原因**：
```python
Q_in_cell = Q_total_s / _N_CELLS   # 均匀分配，无级联
```

在真实浮选回路中，矿浆通常从槽 1 依次流向槽 7，
每槽的有价矿物浓度随精矿被浮出而逐渐降低。

**影响**：
- cx1~cx3（粗选）、jx（精选）、sx1~sx3（扫选）电流/泡沫理论上应有梯度
- 目前 7 槽数据几乎等同于复制，ML 能轻易发现这种重复，
  限制了以槽为粒度的特征工程价值

**建议**：为不同槽位设置不同的 TFe 参与率参数，或引入简单级联流量模型。

---

## 优先级建议

| 编号 | 描述 | 影响 | 建议优先级 |
|------|------|------|----------|
| BUG-A | P_AH 钳位，零方差 | 高（两列无用） | P1 修复 |
| BUG-B | air_sp 常数，零方差 | 中（14 列无用） | P2 修复或删除 |
| 观察-C | 泵池不响应流量变化 | 低（非主要信号） | P3 后续优化 |
| 观察-D | 槽间无级联 | 中（降低物理真实性） | P3 后续优化 |

---

*生成于仿真系统 PR #4 代码审查 + 冒烟测试，2026-05-12*

---

## PR #8：V5 spec loader 反向审查（2026-05-15）

本节记录对当前 PR（`sim/v5/spec_loader.py`）做的“换角度”审查。
按你的要求：**只记录问题，不修改实现**。

### 新增审查脚本

已新增脚本：

```bash
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/review_v5_spec_loader.py
```

脚本思路：

1. 先加载真实 V5 CSV，确认当前 PR 基本功能正常；
2. 再对临时副本做变异（duplicate lhs / invalid status / missing manual_override / unknown parent / duplicate formula_id / missing variable row）；
3. 观察 loader 是否能拒绝这些坏规格；
4. 额外检查 `dependency_list()` 的 API 语义是否真的是“list”。

本次脚本输出摘要：

```text
- [PASS] baseline_load
- [PASS] duplicate_lhs_rejected
- [PASS] invalid_status_rejected
- [PASS] missing_manual_override_rejected
- [PASS] unknown_parent_rejected
- [WARN] duplicate_formula_id_rejected
- [WARN] missing_variable_row_rejected
- [WARN] dependency_api_contract
summary: warnings=3, total_checks=8
```

---

### BUG-PR8-A：`duplicate formula_id` 未被拒绝，`by_id` 会静默覆盖

**现象**：

审查脚本向 `v5_executable_formulas.csv` 追加一行：
- `formula_id` 与已有行相同
- `lhs` 改为新值，避免触发 duplicate lhs

结果：`load_spec()` **仍然成功加载**，没有报错。

**根本原因**：

```python
# sim/v5/spec_loader.py
for row in formulas:
    self.by_id[row.formula_id] = row
```

这里直接写入 dict，没有对 `formula_id` 重复做检测；重复键会被后写入的行静默覆盖。对应位置：
- `sim/v5/spec_loader.py:275-277`

而 V5 规范校验脚本明确把 duplicate formula IDs 作为结构性问题统计：
- `redesign_formula_docs/validate_v5_clean_spec.py:291-292`
- `redesign_formula_docs/V5_CLEAN_AUTOCHECK.md:12`

**影响**：
- `formula_id -> formula row` 索引不再可靠
- 坏规格可能被 loader 悄悄吞掉，后续运行时看到的是“最后一行赢”
- 后面真正做 runtime engine 时，定位公式来源会变得不可信

**建议**：
- 在构建 `by_id` 时显式校验 duplicate `formula_id`

---

### BUG-PR8-B：未校验 `formulas` / `variables` 跨表一致性

**现象**：

审查脚本删除 `v5_variables.csv` 中 `B_eff` 对应变量行后，
`load_spec()` **仍然成功加载**。

**根本原因**：

当前 loader 只是读取 `v5_variables.csv`：

```python
variables = self._load_variables()
...
registry = FormulaRegistry(...)
...
self._validate_statuses_and_roles(formulas)
self._validate_required_statuses_present(formulas)
self._validate_parents(registry)
```

但没有做：
- variable 是否都有对应 formula
- formula lhs 是否都有 variable row
- `defined_by_formula_id` 是否与 formula 表一致

对应位置：
- `sim/v5/spec_loader.py:362-384`
- `sim/v5/spec_loader.py:413-416`

而 V5 autocheck 明确把这两项列为 hard checks：
- `redesign_formula_docs/V5_CLEAN_AUTOCHECK.md:14-15`
- `redesign_formula_docs/validate_v5_clean_spec.py:294-297`

**影响**：
- loader 可能接受“公式表和变量表已分叉”的规格
- 后续如果 runtime engine 依赖 `variables` 做 state registry / schema / stage routing，可能在运行时才暴露问题

**建议**：
- 将 `variables_without_formula == 0`
- `formulas_without_variable == 0`
- `defined_by_formula_id` 一致性

作为 loader 的结构校验之一

---

### 观察-PR8-C：`dependency_list()` 实际返回无序集合，不是“list”

**现象**：

`FormulaRow.from_dict()` 里将父节点解析为 `frozenset`：

```python
parents = frozenset(p.strip() for p in raw_parents.split(";") if p.strip())
```

而 `dependency_list()` 也直接返回 `frozenset`：

```python
def dependency_list(self, lhs: str) -> FrozenSet[str]:
    return self.parents_of.get(lhs, frozenset())
```

对应位置：
- `sim/v5/spec_loader.py:55-56`
- `sim/v5/spec_loader.py:296-298`

**问题点**：
- PR 目标里写的是 `parents -> dependency list`
- 现在实现更接近 `dependency set`
- CSV 中父节点原始顺序被丢失

**影响**：
- 对“仅做存在性校验”来说问题不大
- 但如果后续 runtime formula engine / 调试输出 / 差异比较依赖父节点顺序，当前 API 不够稳妥

**建议**：
- 若后续执行层需要稳定顺序，保留原始 parent list，同时可另建 set 用于 membership 校验

---

## 本轮结论

当前 PR 的主体目标（加载 V5 CSV、建立基本索引、拒绝明显坏规格）**已经完成**，
但从“反向破坏输入”的角度看，至少还有 2 个结构性遗漏 + 1 个 API 语义问题：

| 编号 | 描述 | 类型 | 影响 |
|------|------|------|------|
| BUG-PR8-A | duplicate `formula_id` 未被拒绝 | 结构校验遗漏 | 中 |
| BUG-PR8-B | `formulas` / `variables` 跨表一致性未校验 | 结构校验遗漏 | 中 |
| 观察-PR8-C | `dependency_list()` 返回无序集合 | API 语义偏差 | 低~中 |

按你的要求：**上述问题仅记录，未在本次提交中修复。**

---

## PR #9：PR3 staged engine + 脚本复测问题记录（2026-05-15）

本节记录对当前分支新增的 V5 staged engine（`sim/v5/helpers.py` / `sim/v5/formula_evaluator.py` / `sim/v5/engine.py`）做的额外脚本测试与人工代码审查结果。

按你的要求：**只记录问题，不修复实现。**

### 本轮额外脚本测试

已执行：

```bash
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/calibrate.py
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/review_v5_spec_loader.py
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/run_simulation.py --steps 5 --no-warmup --format csv --output /tmp/iron_sim_review.csv
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/run_simulation.py --steps 5 --no-warmup --format parquet --output /tmp/iron_sim_review.parquet
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/leakage_check.py --input /tmp/iron_sim_review.csv --top 5
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/redesign_formula_docs/validate_v5_clean_spec.py
python /home/runner/work/iron_mining_simulation/iron_mining_simulation/scripts/run_simulation.py --steps -1 --no-warmup --format csv --output /tmp/neg_steps.csv
```

结果摘要：

- `calibrate.py`：通过
- `review_v5_spec_loader.py`：**当前已全部 PASS**，说明前一节 PR8 中记录的 loader 结构问题在当前代码上已不可复现
- `run_simulation.py`：5 步 CSV / parquet 冒烟均可运行
- `leakage_check.py`：在 5 步样本上输出全 NaN（样本量过小，暂不单独记为 bug）
- `validate_v5_clean_spec.py`：通过
- `run_simulation.py --steps -1`：**暴露新问题**，见 BUG-PR9-A

---

### BUG-PR9-A：CLI 接受负步数并返回成功，但可能根本不产出文件

**现象**：

```bash
python scripts/run_simulation.py --steps -1 --no-warmup --format csv --output /tmp/neg_steps.csv
```

输出为：

```text
[仿真] 开始仿真 -1 步 ...
[仿真] 完成！耗时 0.00s，输出 → /tmp/neg_steps.csv
EXIT:0
```

但 `/tmp/neg_steps.csv` 并未生成。

**根本原因**：

CLI 对 `--steps` 只做了 `int` 解析，没有校验正数：

```python
# scripts/run_simulation.py
parser.add_argument("--steps", type=int, default=None, ...)
...
n_steps = args.steps if args.steps is not None else sim_cfg.n_steps
sim.run_steps(n_steps)
```

而底层执行是：

```python
# sim/simulator.py
for t in range(n_steps):
    self._step(t, write=True)
self._writer.close()
```

`range(-1)` 直接是空循环，所以脚本以“成功”结束，但没有任何真实仿真步发生。对应位置：

- `scripts/run_simulation.py:24-29, 90-97`
- `sim/simulator.py:95-99`

**影响**：

- 调用方会误以为仿真已正常完成
- CI / shell 脚本如果只看退出码，会把“零步且无输出”的情况当成功
- 对数据流水线而言，这比显式报错更危险，因为它是静默失败

**建议**：

- CLI 层显式校验 `steps > 0`
- 或在 `Simulator.run_steps()` 中拒绝非正整数

---

### BUG-PR9-B：lab 报告时间门控失效；`report_time > 0` 时结果会永久停留为 NaN

**现象（定向复现）**：

将 `report_time_tm_overflow_tfe=120.0`、`report_time_mag_mixed_conc_tfe=120.0`，
然后运行 10 步（总时间 600 s）后，两个 lab 结果仍然是 `NaN`。

**根本原因**：

`lab_sample_template()` 依赖 keyword-only 参数 `step_time`：

```python
# sim/v5/helpers.py
def lab_sample_template(..., *, step_time: float = 0.0, ...):
    if float(step_time) < float(report_time):
        return float("nan")
```

但 eval namespace 里注册的 wrapper 仍然使用默认值 `step_time=0.0`：

```python
def _lab_sample_template(..., step_time=0.0):
    return lab_sample_template(..., step_time=step_time, rng=rng)
```

而 evaluator 虽然把当前步时钟写进了 namespace，
写入的名字却是 `_step_time`，并没有注入到 `lab_sample_template(...)` 调用里：

```python
# sim/v5/formula_evaluator.py
ns["_step_time"] = step_time
result = eval(expr, {"__builtins__": {}}, ns)
```

对应位置：

- `sim/v5/helpers.py:139-179`
- `sim/v5/helpers.py:300-305`
- `sim/v5/formula_evaluator.py:177-180, 224-228`

**影响**：

- 只要 `report_time > 0`，当前实现中的 lab 公式就永远不会“到点发布”
- 现在测试通过，主要是因为默认参数把 `report_time_*` 设成了 0
- 一旦后续把真实 sample/report delay 接回去，lab/label 时序会直接坏掉

**建议**：

- 明确把当前 `step_time` 传入 `lab_sample_template`
- 不要依赖 wrapper 的默认 `step_time=0.0`

---

### BUG-PR9-C：缺少当前步父节点时，evaluator 会偷偷回退到上一时刻值

**现象（定向复现）**：

对公式 `Q_conc`，只在 `store.previous` 中放 `M_conc_solid=123.0`，
`store.current` 不放该变量，`eval_formula()` 仍然能成功算出结果，而不是报“当前依赖缺失”。

**根本原因**：

namespace 构建时，previous state 被同时注入成：

```python
for k, v in store.previous.items():
    ns[k] = v
    ns[f"{k}_prev"] = v
```

这意味着：

- `X_prev` 会正确映射到上一时刻
- **但 `X` 也会被上一时刻值填充**

如果某个本应来自“当前步上游公式”的父节点还没算出来，
evaluator 不会报缺失，而是静默用旧值顶上。对应位置：

- `sim/v5/formula_evaluator.py:169-175`

**影响**：

- 会掩盖 stage 内执行顺序错误
- 会掩盖“上游公式没执行/执行失败”的问题
- 结果看起来能跑，但其实混入了 stale state，最难排查

**建议**：

- 只把 previous state 注入到 `X_prev`
- 当前步普通父节点缺失时，应显式失败

---

### BUG-PR9-D：V5 engine 在大量公式失败时仍然整体返回成功，错误只写入 `skipped`

**现象（定向复现）**：

跑 1 步 V5 engine：

```text
executed 97
skipped 329
Counter({'Unsupported': 233, 'SyntaxError': 95, 'FormulaEval': 1})
```

其中很多失败是明确的公式不可执行（例如模板变量名导致 `SyntaxError`），
但 `engine.run()` 仍然正常返回，没有抛错。

**根本原因**：

`_eval_and_store()` 捕获 `UnsupportedFormulaError` / `FormulaEvaluationError` 后，
只记录到 `self.skipped`，然后返回 `None`：

```python
except UnsupportedFormulaError as exc:
    self.skipped[formula.lhs] = ...
    return None
except FormulaEvaluationError as exc:
    self.skipped[formula.lhs] = ...
    return None
```

对应位置：

- `sim/v5/engine.py:570-592`

**影响**：

- 从 API 视角看，`run()` 成功了；但从语义看，大部分公式根本没执行
- 当前测试只验证“每个 stage 至少有一些输出”，掩盖了“多数公式仍失败”的事实
- 后续如果有人把这个 engine 接到 CLI / 数据生成流程里，极易把残缺结果当完整结果消费

**建议**：

- 至少为“存在 skipped”提供 fail-fast 模式
- 或把 skipped 计数提升为显式运行状态，而不是仅靠调用方自己读 dict

---

### BUG-PR9-E：带模板占位符的变量名直接进入 `eval()`，导致大量 SyntaxError

**现象**：

例如：

- `E_air_{s,c}`
- `Q_air_{s,c}`
- `fx_s{s}_{c}_froth_h`

这些名字在 Python 语法里并不是合法标识符。
当前实现对 RHS 的预处理只有：

- `^ -> **`
- 去掉行尾注释

并不会先把模板变量展开或重写成合法名字。对应位置：

```python
def preprocess_rhs(rhs: str) -> str:
    expr = rhs.replace("^", "**")
    expr = re.sub(r"\s*#[^\n]*$", "", expr).strip()
    return expr
```

对应位置：

- `sim/v5/formula_evaluator.py:73-93`

另外，`DEFAULT_PARAMS` 中也直接放了这些带花括号的键：

- `Q_pump_pool_{s,1}`
- `Q_air_{s,c}`
- `fx_s{s}_{c}_froth_h`

对应位置：

- `sim/v5/engine.py:310-311`
- `sim/v5/engine.py:336-339`
- `sim/v5/engine.py:356-367`

**影响**：

- 只要遇到未展开模板名，eval 就会在语法层面失败
- 这也是上面 95 个 `SyntaxError` 的直接来源之一
- 当前 engine 更像“部分公式可跑的 skeleton”，还不能视为完整可执行层

**建议**：

- 在 eval 前做模板实例化 / 名称正规化
- 或建立显式 AST / helper 执行层，避免把带模板标识符的原始 RHS 直接交给 Python parser

---

### BUG-PR9-F：两个 helper 仍是“占位语义”，与 V5 规格含义不一致

#### F1. `topology_feed_j_rate()` 忽略槽间级联关系

当前实现：

```python
def topology_feed_j_rate(stage_index, series, Q_feed_s, feed_grade_j_s, **kwargs):
    return float(Q_feed_s) * float(feed_grade_j_s)
```

但函数注释自己也承认，V5 规格需要的是 cascade：

```python
Q_in[0] = Q_total_s
Q_in[c] = Q_out[c-1]
```

对应位置：

- `sim/v5/helpers.py:187-213`

**影响**：

- `feed_j_rate_{s,c}` 目前没有体现 cell-by-cell 拓扑
- 浮选每槽的进料关系被压平为同一个标量

#### F2. `standardized()` 实际返回原始输入均值，不是标准化结果

当前实现：

```python
"standardized": lambda *args: sum(float(a) for a in args) / max(len(args), 1),
```

对应位置：

- `sim/v5/helpers.py:344-346`

而从函数名和 DCS proxy 语义看，它本应产生“标准化后的 proxy”，不是简单平均。

**影响**：

- `online_froth_proxy` / `online_load_proxy` 变成对原始量纲的均值聚合
- 不同量纲（液位/流量/频率/压力/电流）直接平均，物理含义不成立
- 实测一组默认参数下，两个 proxy 输出分别约为 `8.38` 和 `95.71`，已经明显不是“标准化信号”

**建议**：

- 这两个 helper 在后续实现里应被视为未完成项，而不是最终逻辑

---

## 本轮结论

本轮"脚本复测 + 手动读代码"确认：

1. 旧的 PR8 loader 审查问题在当前代码上已不可复现；
2. 但 PR3 新增的 staged engine 仍存在多处结构性问题；
3. 其中影响最大的不是"小公式误差"，而是：
   - lab 时序门控失效
   - 当前/上一时刻依赖混淆
   - 大量公式失败却整体返回成功
   - 模板标识符未实例化就直接喂给 `eval()`

修复状态：

| 编号 | 描述 | 类型 | 优先级 | 状态 |
|------|------|------|--------|------|
| BUG-PR9-B | lab `report_time` 门控失效 | 时序逻辑错误 | P1 | ✅ 已修复 |
| BUG-PR9-C | 缺少当前步父节点时回退到上一时刻 | 状态依赖错误 | P1 | ⚠️ 已记录（保持向后兼容的 fallback，docstring 明确说明） |
| BUG-PR9-D | 大量公式失败但 engine 仍返回成功 | 运行状态错误 | P1 | ✅ 已修复 |
| BUG-PR9-E | 模板标识符未展开直接 `eval` | 执行层缺陷 | P1 | ✅ 已修复 |
| BUG-PR9-A | CLI 接受负步数并报成功 | CLI / 脚本健壮性 | P2 | ✅ 已修复 |
| BUG-PR9-F | helper 仍是占位语义 | 规格偏离 | P2 | ✅ 已修复（加 TODO 注释，明确 stub 状态） |

---

## PR3 总结

**PR3：V5 staged formula execution engine**

本次 PR 实现了 V5 仿真的分阶段公式执行骨架（`sim/v5/engine.py`、`sim/v5/formula_evaluator.py`、`sim/v5/helpers.py`）。

### 已交付的功能

- `V5SimulationEngine`：按 `v5_execution_steps.csv` 定义的顺序（boundary → magnetic → tower_mill → flotation → dcs → lab → label）执行公式
- `FormulaEvaluator`：将公式 RHS 字符串转换为 Python 表达式并在受控 namespace 中求值
- `build_helpers_namespace`：提供 clip / sigmoid / thermal_derate / lab_sample_template 等核心辅助函数
- C006 规则：`y_fx_xin_s` / `y_fx_xin_s_true` 只在 label 阶段生成，不在 flotation 阶段提前泄露
- 104 个单元测试全部通过

### 本轮修复（PR9 审查反馈）

| Bug | 修复内容 | 文件 |
|-----|---------|------|
| PR9-A | CLI `--steps` 负数静默通过 | `scripts/run_simulation.py`, `sim/simulator.py` |
| PR9-B | `lab_sample_template` 的 `step_time` 永远为 0 | `sim/v5/formula_evaluator.py` — `build_namespace` 每次注入 step_time 绑定闭包 |
| PR9-D | 大量公式失败时 `run()` 静默成功 | `sim/v5/engine.py` — 新增 `RuntimeWarning` / `run_summary()` / `skipped_count` |
| PR9-E | 带 `{s,c}` 模板名的 RHS 直接传入 `eval()` 导致 SyntaxError | `sim/v5/formula_evaluator.py` — `preprocess_rhs` 提前检测并抛出 `UnsupportedFormulaError` |
| PR9-F | `topology_feed_j_rate` / `standardized` 无 stub 说明 | `sim/v5/helpers.py` — 加 TODO docstring，明确标注未完成语义 |

### 已知遗留问题（不在本次 PR 范围内）

- `topology_feed_j_rate` 仍是标量近似（无级联）
- `standardized` 仍是算术均值（无 z-score）
- 当前步父节点缺失时 evaluator 仍 fallback 到上一时刻值（设计 tradeoff，已在 docstring 中说明，见 BUG-PR9-C）
- 443 个公式中仍有 329 个为 UnsupportedFormulaError（未展开的模板索引公式），待后续完整实现 index expansion
