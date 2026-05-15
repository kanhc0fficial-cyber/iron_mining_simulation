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
| 安全读取（不抛错） | `store.get_or_none(name)` ⚠️ `None` 值有歧义，见 BUG-3 |
| 明确判断当前步是否存在 | `store.has(name)` → bool（推荐替代 `get_or_none`）✅ 新增 |
| 判断当前步是否存在（运算符） | `name in store` |
| 读取上一步变量 | `store.get_previous(name)` → 解析 `previous_state_reference` 类父节点 |
| 推进时间步 | `store.advance()` → current → previous，清空 current；DCS 保存为 `previous_dcs` |
| 写入 DCS 输出缓冲 | `store.set_dcs(name, value)` |
| 读取 DCS 输出缓冲 | `store.get_dcs(name)` |
| 推荐：消费并清空 DCS 缓冲 | `store.flush_dcs()` → dict ✅ 新增，在 `advance()` 前调用 |
| 读取上一步 DCS（advance 后仍可读） | `store.previous_dcs` dict ✅ 新增 |
| 当前步快照（测试用） | `store.snapshot()` |
| 全量快照（测试/调试用） | `store.snapshot_full()` → `{current, previous, dcs_buffer, previous_dcs}` ✅ 新增 |

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
| 有序阶段列表 | `scheduler.ordered_stages()` → `["boundary", "magnetic", "tower_mill", "flotation", "dcs", "lab", "label"]` |
| 某阶段步骤列表 | `scheduler.steps_for_stage(stage)` |
| 某阶段运行时公式 | `scheduler.formulas_for_stage(stage)` → 排除 `concept`/`reference` 角色 |
| 手工权威公式可见性 | `scheduler.manual_formulas_for_stage(stage)` / `scheduler.all_manual_formulas()` |
| 驱动单步执行 | `scheduler.run_step(evaluator, stages=None)` |

**✅ BUG-1 已修复：**  
`dcs` 阶段（3 个公式，含 `manual_closure` 的 `fx_s{s}_{c}_froth_h`）已加入 `v5_execution_steps.csv`（step 360），现在正常调度。  
`global` 阶段（17 个 definition 公式：`Fe_total`, `Stream`, `mu_slurry` 等）不作为独立步骤调度——它们是 helper 定义，由公式求值器内联使用。调度器启动时对遗漏 executable 阶段会抛 `ValueError`。

---

## 管道顺序

```
boundary (010–030)
  → magnetic (100–120)
    → tower_mill (200–250)
      → flotation (300–350)
        → dcs (360)          ← DCS 代理信号 + froth fault closures [BUG-1 修复后加入]
          → lab (400)
            → label (500)

[global]  ← 17 个 definition 类公式（helper 定义），不作为独立步骤调度，由公式求值器内联调用
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
    # 在 advance() 之前用 flush_dcs() 读取 DCS 缓冲并写入输出文件（推荐写法）
    dcs_snapshot = store.flush_dcs()
    store.advance()
```

---

## 测试覆盖

测试文件：`tests/test_v5_state_and_scheduler.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestStateStore` | 24 | set/get、advance、previous、DCS buffer、snapshot、has()、flush_dcs()、previous_dcs、snapshot_full() |
| `TestExternalInputRegistry` | 12 | 注册检查、分类查询、断言守卫 |
| `TestExecutionScheduler` | 19 | 阶段顺序（含 dcs）、步骤排序、公式过滤、manual 可见性、run_step、dcs 阶段验证 |
| `TestStateAndRegistryIntegration` | 3 | previous_state_reference 模式、注册守卫集成 |
| **合计** | **58** | |

---

## 已知问题（摘要）

| ID | 严重度 | 状态 | 说明 |
|----|--------|------|------|
| BUG-1 | 严重 | ✅ 已修复 | `dcs` 阶段加入 execution_steps，3 个公式（含 `fx_s{s}_{c}_froth_h` manual_closure）现已调度；调度器启动时对遗漏 executable 阶段抛 ValueError |
| BUG-2 | 严重 | ⚠️ 已文档化 | `ExternalInputRegistry` 不能单独用作父节点解析守卫，需配合 `FormulaRegistry.by_lhs` |
| BUG-3 | 中 | ✅ 已修复 | 新增 `StateStore.has()` 方法，消除 `get_or_none()` 对 `None` 值的歧义 |
| BUG-4 | 中 | ✅ 已修复 | `advance()` 保存 `previous_dcs`；新增 `flush_dcs()` 推荐写法 |
| BUG-5 | 中 | ⚠️ 已文档化 | 只保留 1 步历史，多步延迟需外部 `DelayBuffer` |
| BUG-PR2-R2-1 | 高 | ⚠️ 待处理 | 调度器覆盖校验只检查 `executable`，对“仅 definition 且缺 execution step”阶段会静默漏调度 |
| BUG-PR2-R2-2 | 中 | ⚠️ 待处理 | `run_step(stages=...)` 对未知阶段名静默 no-op，拼写错误不会 fail-fast |

完整描述见 [`docs/PR2_BUG_REPORT.md`](./PR2_BUG_REPORT.md)。

---

## 本轮临时说明（2026-05-15）

- 采用“换角度脚本测试 + 手工读码推演”对 PR2 三模块复审；
- 当前仓库基线验证通过：`pytest tests/`（786 passed）、`scripts/calibrate.py`、`scripts/run_simulation.py --steps 100`；
- 新增发现 2 个未修复调度层问题（见 BUG-PR2-R2-1 / BUG-PR2-R2-2），本次仅先落文档，后续由你接手处理代码修复。

---

*作者：Copilot agent — PR 2 临时文档，待 PR-3 后更新。*
