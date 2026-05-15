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
