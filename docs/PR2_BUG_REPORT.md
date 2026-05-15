# PR 2 — Bug Report & Code Review Findings

**Scope:** `sim/v5/state_store.py`, `sim/v5/external_input_registry.py`,
`sim/v5/execution_scheduler.py`, `tests/test_v5_state_and_scheduler.py`

**Review method:** manual code reading + angle-script probing
(automated edge-case Python scripts executed against live module objects).

**Current baseline re-check (2026-05-15):** `786 passed` (full `pytest tests/`) + `scripts/calibrate.py` passed + `scripts/run_simulation.py --steps 100` passed.

---

## Critical Bugs — FIXED

### BUG-1 · `ExecutionScheduler` silently dropped `global` and `dcs` stage formulas

**Status: ✅ FIXED**

**Files:** `sim/v5/execution_scheduler.py`; `redesign_formula_docs/v5_execution_steps.csv`

**Root cause:**
`_formulas_by_stage` was built only for stages that appear in
`v5_execution_steps.csv`.  `global` and `dcs` were valid stages in the
formula registry but had **no corresponding row** in the execution steps CSV.
The scheduler silently returned an empty list for them instead of raising.

**Impact (before fix):**
- `fx_s{s}_{c}_froth_h` (status `manual_closure`) was never executed —
  directly violating V5 rule C005.
- `online_froth_proxy` and `online_load_proxy` (DCS proxies) were not dispatched.
- 17 `global` definition formulas were not dispatched (these are inline helpers;
  `global` is intentionally kept out of execution steps since `definition`-role
  formulas are inlined by formula evaluators, not dispatched as a standalone stage).

**Fix applied:**
1. Added `360,dcs,"Compute DCS proxy signals and froth fault closures."` to
   `v5_execution_steps.csv`.  The `dcs` stage now runs between `flotation`
   (350) and `lab` (400).
2. Added startup validation in `ExecutionScheduler.__init__`: raises
   `ValueError` if any registry stage has `executable`-role formulas not
   covered by an execution step, preventing silent omission in the future.
3. Updated all affected tests.

**New tests added:**
- `test_dcs_stage_in_execution_plan`
- `test_dcs_stage_formulas_not_empty`
- `test_dcs_stage_positioned_after_flotation`
- `test_fx_froth_h_manual_closure_in_dcs_stage`
- `test_all_registry_executable_formulas_in_scheduler`

---

### BUG-2 · `ExternalInputRegistry` cannot be used as the sole parent-resolution guard

**Status: ⚠️ DOCUMENTED (architectural — needs PR-3 evaluator)**

`ExternalInputRegistry.assert_registered("C_feed")` raises
`UnregisteredInputError`, even though `C_feed` is a **valid derived variable**
defined by formula `V5_0002`.

`ExternalInputRegistry` only indexes entries from `v5_external_inputs.csv`.
A formula evaluator resolving parents must check **both**:
- `ExternalInputRegistry.is_registered(name)` for external/parameter parents
- `name in formula_registry.by_lhs` for formula-derived parents

**Fix applied:** Updated the module docstring of `external_input_registry.py`
with an explicit "Scope limitation" section explaining this architectural
boundary and the required combined resolution pattern.

---

## Medium Bugs — FIXED

### BUG-3 · `StateStore.get_or_none()` was ambiguous for `None` values

**Status: ✅ FIXED**

`get_or_none()` returned `None` for both a variable set to `None` and a
variable never written, making these cases indistinguishable.

**Fix applied:** Added `StateStore.has(name: str) -> bool` — an explicit
"is this variable in the current step?" check with no ambiguity.  Updated
`get_or_none` docstring with a warning about the `None`-value ambiguity.

---

### BUG-4 · DCS buffer cleared by `advance()` with no flush hook

**Status: ✅ FIXED**

`advance()` cleared `dcs_buffer` unconditionally, causing silent data loss if
the output writer read the buffer after advancing.

**Fix applied:**
1. `StateStore.advance()` now saves `dcs_buffer` to `previous_dcs` before
   clearing, so the writer can still read the last step's DCS values after
   advancing.
2. Added `StateStore.flush_dcs() -> dict` — the recommended pattern: call
   this before `advance()` to consume and clear the buffer in one atomic
   operation.

---

### BUG-5 · `StateStore` only retains one step of history

**Status: ⚠️ DOCUMENTED (known limitation — needs PR-3/later)**

`advance()` only retains `t-1` history.  Multi-step lag (`t-k`, k>1) requires
an external `DelayBuffer`.  Documented in the `advance()` docstring.

---

## Low Severity — FIXED

### NOTE-2 · `StateStore.snapshot()` was incomplete

**Status: ✅ FIXED**

Added `snapshot_full() -> dict` returning `{"current", "previous",
"dcs_buffer", "previous_dcs"}`.

### NOTE-4 · `ExternalInputRegistry` had no duplicate parent guard

**Status: ✅ FIXED**

Added `ValueError` on duplicate `parent` names during `__init__` construction.

### NOTE-1, NOTE-3, NOTE-5

**Status: ⚠️ DOCUMENTED**

- NOTE-1 (`__contains__` semantics): documented in `__contains__` docstring.
- NOTE-3 (no intra-stage topological sort): noted in `execution_scheduler.py` as a future PR-3 item.
- NOTE-5 (evaluator exceptions leave partial state): noted in `run_step` docstring.

---

## Summary Table — PR-2 Bugs

| ID | Severity | Fixed? | Module |
|----|----------|--------|--------|
| BUG-1 | Critical | ✅ Fixed | `execution_scheduler.py`, `v5_execution_steps.csv` |
| BUG-2 | Critical | ⚠️ Documented | `external_input_registry.py` |
| BUG-3 | Medium | ✅ Fixed | `state_store.py` |
| BUG-4 | Medium | ✅ Fixed | `state_store.py` |
| BUG-5 | Medium | ⚠️ Documented | `state_store.py` |
| NOTE-1 | Low | ⚠️ Documented | `state_store.py` |
| NOTE-2 | Low | ✅ Fixed | `state_store.py` |
| NOTE-3 | Low | ⚠️ Documented | `execution_scheduler.py` |
| NOTE-4 | Low | ✅ Fixed | `external_input_registry.py` |
| NOTE-5 | Low | ⚠️ Documented | `execution_scheduler.py` |

---

## Follow-on Bugs — Discovered by Angle-Script Probing (2026-05-15)

These bugs were found during post-PR-2 regression testing of the PR-3 evaluation engine.
All are fixed in the same session.

### BUG-A · `_eval_and_store()` silently dropped `None`-returning formulas

**Status: ✅ FIXED**  
**File:** `sim/v5/engine.py`

**Root cause:**  
`_eval_and_store()` checked `if result is not None` before writing to the store.
A formula returning Python `None` was silently discarded — the LHS was never written
and the failure was invisible to callers.

**Fix applied:**  
`None` result is now recorded in `engine.skipped` with a descriptive message.
The variable is *not* written to the store (correct), but the absence is now visible.

---

### BUG-B · `FormulaEvaluator.unsupported` / `failed` dicts were never populated

**Status: ✅ FIXED**  
**File:** `sim/v5/formula_evaluator.py`

**Root cause:**  
The `eval_formula()` method re-raised `NameError` and `Exception` without adding
the failing LHS to `self.unsupported` or `self.failed`.
The tracking dicts always stayed empty regardless of how many formulas failed.

**Fix applied:**  
Each `except` branch now writes to the corresponding dict before re-raising,
so callers can inspect evaluation failures independently of the exception chain.

---

### BUG-C · `DCSOutputRegistry` compound-row registration overwrote individual rows

**Status: ✅ FIXED**  
**File:** `sim/v5/dcs_registry.py`

**Root cause:**  
Single-pass registration split `dcs_name` on `"/"` and used the prefix as the only
key.  For a row like `"agg_mag_tailings_valve1/2"`, the prefix `"agg_mag_tailings_valve1"`
overwrote a separately-defined row with the same exact name, making that row
unreachable via `get()`.

**Fix applied:**  
Two-pass registration: pass 1 registers every row by its exact `dcs_name`; pass 2
adds split-prefix aliases only via `setdefault()` (never overwriting).

---

### BUG-D · `preprocess_rhs()` did not convert semicolons to commas

**Status: ✅ FIXED**  
**File:** `sim/v5/formula_evaluator.py`

**Root cause:**  
V5 spec uses `";"` as an alternate argument separator in function calls
(e.g. `F(45e-6;d80_i,n_rr)`).  Python requires `","`, so every formula with a
semicolon-separated argument list produced a `SyntaxError` inside `eval()`.
`F325_i` was the primary affected formula.

**Fix applied:**  
`preprocess_rhs()` now replaces all `";"` with `","` before compilation.

---

### BUG-F · `StateStore.advance()` erased variables not written in the current step

**Status: ✅ FIXED**  
**File:** `sim/v5/state_store.py`

**Root cause:**  
`advance()` replaced `previous` with a shallow copy of `current`.  Variables with
long time-constants (temperatures, matrix-clog, etc.) that were not recomputed
every step silently disappeared from the store after their first missed step.

**Fix applied:**  
`advance()` now *merges* `current` into `previous` (`{**previous, **current}`).
Variables not recomputed in a step retain their last-known value.

---

### BUG-G · Engine warning fired for expected template-placeholder skips

**Status: ✅ FIXED**  
**File:** `sim/v5/engine.py`

**Root cause:**  
`run()` emitted a `RuntimeWarning` whenever `self.skipped` was non-empty.
Template-placeholder formulas (unexpanded `{s,c}` subscripts) are *expected* to
be skipped at the skeleton stage; wrapping them in a warning created false alarms
that masked genuine runtime failures.

**Fix applied:**  
The warning is now filtered: it fires only if there are *unexpected* skips (those
whose message does not contain `"template placeholder"`).  The warning message
also includes the `template_placeholders=N` count for transparency.

---

## Summary Table — Follow-on Bugs

| ID | Severity | Fixed? | Module |
|----|----------|--------|--------|
| BUG-A | Medium | ✅ Fixed | `engine.py` |
| BUG-B | Medium | ✅ Fixed | `formula_evaluator.py` |
| BUG-C | Medium | ✅ Fixed | `dcs_registry.py` |
| BUG-D | High | ✅ Fixed | `formula_evaluator.py` |
| BUG-F | High | ✅ Fixed | `state_store.py` |
| BUG-G | Low | ✅ Fixed | `engine.py` |

**Regression tests added:** 9 new tests in `tests/test_v5_stage_execution.py`
(`TestBugRegressions` class).

---

*Generated by manual review + angle-script probing.  Fixes applied 2026-05-15.*

---

## PR-2 Second-pass Findings (2026-05-15, script-angle + manual logic walkthrough)

本轮按“换角度脚本测试 + 手工推演”新增发现 2 个问题（均**尚未修复**，先记录给后续 PR 处理）。

### BUG-PR2-R2-1 · `ExecutionScheduler` 对「仅 definition 公式但无 execution step」阶段无告警，导致静默漏调度

**Status: ⚠️ OPEN**  
**File:** `sim/v5/execution_scheduler.py` (guard at lines 85-90)

**现象（脚本复现）：**
- 构造一个临时 registry，新增 stage=`ghost_stage_def_only` 的 `definition` 公式；
- 不改 `v5_execution_steps.csv`；
- `ExecutionScheduler(mut_registry)` **不抛错**，且该 stage 不在 `ordered_stages()`，对应公式被静默遗漏。

**根本原因：**
当前覆盖校验只检查 `formula_role == "executable"`，没有覆盖 `_RUNTIME_ROLES` 里的 `"definition"`：

```python
missing_exec = [f for f in formulas if f.formula_role == "executable"]
if missing_exec:
    uncovered.append(stage)
```

但同文件定义的运行期角色是：
```python
_RUNTIME_ROLES = frozenset({"executable", "definition"})
```

**影响：**
- 一旦未来某阶段只含 `definition`（但设计上需要参与运行）且漏配 execution step，会被悄悄吞掉；
- 调度完整性保护不一致，容易形成“看似启动正常、实则漏执行”的隐性错误。

**建议：**
- 覆盖校验从 `"executable"` 扩展为 `_RUNTIME_ROLES`；
- 或显式定义并校验“哪些 definition 允许不进入 execution step（如 global helper）”。

---

### BUG-PR2-R2-2 · `run_step(stages=...)` 对拼写错误阶段静默 no-op，缺少 fail-fast

**Status: ⚠️ OPEN**  
**File:** `sim/v5/execution_scheduler.py` (run_step lines 174-179)

**现象（脚本复现）：**
- 调用 `scheduler.run_step(..., stages=['boundray'])`（`boundary` 拼写错误）；
- 无异常，执行结果 `called_count=0`，整步变成静默空跑。

**根本原因：**
`run_step` 仅做集合过滤，不验证 `stages` 参数是否都存在于调度计划。

**影响：**
- 上层调用出现拼写错误时不会暴露，可能让仿真/回放管道“成功返回但未执行任何阶段”；
- 对排障不友好，属于典型 silent failure。

**建议：**
- 在 `run_step` 入口校验 `stages` 子集关系，遇到未知 stage 直接抛 `ValueError`；
- 异常信息应包含未知阶段名和可选合法阶段列表。

---

## 本轮新增问题汇总（未修复）

| ID | Severity | Fixed? | Module |
|----|----------|--------|--------|
| BUG-PR2-R2-1 | High | ⚠️ Open | `execution_scheduler.py` |
| BUG-PR2-R2-2 | Medium | ⚠️ Open | `execution_scheduler.py` |
