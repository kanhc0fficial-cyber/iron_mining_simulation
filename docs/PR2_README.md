# PR 2 — 临时说明文档

> **状态：** 已合并骨架，待 PR-3 实现公式求值引擎后激活。

---

## 概述

PR 2 实现了 V5 引擎的**运行骨架**，即在不执行任何公式 RHS 的前提下，建立：

- 跨时间步的变量状态管理（`StateStore`）
- 外部输入父节点的强制注册校验（`ExternalInputRegistry`）
- 按 `v5_execution_steps.csv` 驱动的阶段调度（`ExecutionScheduler`）

这三个模块是 PR-3（公式求值引擎）的直接依赖。

---

## 模块说明

### `sim/v5/state_store.py` — `StateStore`

| 功能 | API |
|------|-----|
| 写入当前步变量 | `store.set(name, value)` |
| 读取当前步变量 | `store.get(name)` → 缺失时抛 `StateStoreError` |
| 安全读取（不抛错） | `store.get_or_none(name)` |
| 判断当前步是否存在 | `name in store` |
| 读取上一步变量 | `store.get_previous(name)` → 解析 `previous_state_reference` 类父节点 |
| 推进时间步 | `store.advance()` → current → previous，清空 current 和 dcs_buffer |
| 写入 DCS 输出缓冲 | `store.set_dcs(name, value)` |
| 读取 DCS 输出缓冲 | `store.get_dcs(name)` |
| 当前步快照（测试用） | `store.snapshot()` |

**重要约束：**
- `StateStore` 只保留 **1 步历史**（`previous` = 上一步 `current`）。
- 需要 t-k（k>1）延迟的公式应配合 `sim/utils/buffer.py` 的 `DelayBuffer` 使用。
- DCS 缓冲在 `advance()` 时清空——输出 writer **必须在 `advance()` 之前**读取 DCS 缓冲。

---

### `sim/v5/external_input_registry.py` — `ExternalInputRegistry`

从 `v5_external_inputs.csv`（通过 `FormulaRegistry`）构建的只读索引。

| 功能 | API |
|------|-----|
| 检查是否已注册 | `ext.is_registered(name)` → bool |
| 强制断言已注册 | `ext.assert_registered(name)` → 未注册时抛 `UnregisteredInputError` |
| 查询分类 | `ext.get_classification(name)` → 字符串（如 `"parameter"`, `"previous_state_reference"`, `"stream_or_state_input"`） |
| 按分类查询集合 | `ext.parents_by_classification(cls)` → frozenset |
| 全量注册名 | `ext.all_registered()` → frozenset |

**⚠️ 重要限制（BUG-2）：**  
`ExternalInputRegistry` **只覆盖外部输入**（参数、外生输入、lag 引用等）。  
它**不**包含公式导出变量（formula LHS）。  
因此，**不能将其用作通用父节点解析的唯一守卫**——否则会拒绝所有合法的派生变量（如 `C_feed`、`B_eff`）。  
完整的父节点解析应检查：`ExternalInputRegistry` **或** `FormulaRegistry.by_lhs`。

---

### `sim/v5/execution_scheduler.py` — `ExecutionScheduler`

从 `v5_execution_steps.csv` 读取步骤，按 `step_order` 数值排序，驱动每个时间步的公式调度。

| 功能 | API |
|------|-----|
| 有序阶段列表 | `scheduler.ordered_stages()` → `["boundary", "magnetic", "tower_mill", "flotation", "lab", "label"]` |
| 某阶段步骤列表 | `scheduler.steps_for_stage(stage)` |
| 某阶段运行时公式 | `scheduler.formulas_for_stage(stage)` → 排除 `concept`/`reference` 角色 |
| 手工权威公式可见性 | `scheduler.manual_formulas_for_stage(stage)` / `scheduler.all_manual_formulas()` |
| 驱动单步执行 | `scheduler.run_step(evaluator, stages=None)` |

**⚠️ 重要限制（BUG-1）：**  
`global` 阶段（17 个 definition 公式：`Fe_total`, `Stream`, `mu_slurry` 等）和 `dcs` 阶段（3 个公式，含 `manual_closure` 的 `fx_s{s}_{c}_froth_h`）**不在** `v5_execution_steps.csv` 中，因此 `formulas_for_stage("global")` 和 `formulas_for_stage("dcs")` **返回空列表**，这些公式不会被 `run_step()` 调度。

这是一个待修复的关键 Bug，见 `docs/PR2_BUG_REPORT.md`。

---

## 管道顺序

```
boundary (010–030)
  → magnetic (100–120)
    → tower_mill (200–250)
      → flotation (300–350)
        → lab (400)
          → label (500)

[global]  ← 17 个定义型公式，当前未进入调度 (BUG-1)
[dcs]     ← 3 个 DCS 代理公式，当前未进入调度 (BUG-1)
```

---

## 典型使用模式（PR-3 公式引擎接入示例）

```python
from sim.v5.spec_loader import load_spec
from sim.v5.state_store import StateStore
from sim.v5.external_input_registry import ExternalInputRegistry
from sim.v5.execution_scheduler import ExecutionScheduler

registry = load_spec()
store = StateStore()
ext = ExternalInputRegistry(registry)
scheduler = ExecutionScheduler(registry)

def evaluator(formula):
    # 1. 从 store / ext 读取父节点值
    # 2. 计算 formula.rhs
    # 3. store.set(formula.lhs, result)
    pass

for step in range(n_steps):
    scheduler.run_step(evaluator)
    # 在 advance() 之前读取 DCS 缓冲并写入输出文件
    dcs_snapshot = dict(store.dcs_buffer)
    store.advance()
```

---

## 测试覆盖

测试文件：`tests/test_v5_state_and_scheduler.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestStateStore` | 13 | set/get、advance、previous、DCS buffer、snapshot |
| `TestExternalInputRegistry` | 12 | 注册检查、分类查询、断言守卫 |
| `TestExecutionScheduler` | 14 | 阶段顺序、步骤排序、公式过滤、manual 可见性、run_step |
| `TestStateAndRegistryIntegration` | 3 | previous_state_reference 模式、注册守卫集成 |
| **合计** | **44** | |

---

## 已知问题（摘要）

| ID | 严重度 | 说明 |
|----|--------|------|
| BUG-1 | 严重 | `global`/`dcs` 阶段共 20 个公式从未被调度，含 `fx_s{s}_{c}_froth_h`（manual_closure） |
| BUG-2 | 严重 | `ExternalInputRegistry` 不能单独用作父节点解析守卫，需配合 `FormulaRegistry.by_lhs` |
| BUG-3 | 中 | `get_or_none()` 对 `None` 值有歧义 |
| BUG-4 | 中 | `advance()` 清空 DCS buffer，writer 必须先读后 advance |
| BUG-5 | 中 | 只保留 1 步历史，多步延迟需外部 `DelayBuffer` |

完整描述见 [`docs/PR2_BUG_REPORT.md`](./PR2_BUG_REPORT.md)。

---

*作者：Copilot agent — PR 2 临时文档，待 PR-3 后更新。*
