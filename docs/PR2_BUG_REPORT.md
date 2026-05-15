# PR 2 — Bug Report & Code Review Findings

**Scope:** `sim/v5/state_store.py`, `sim/v5/external_input_registry.py`,
`sim/v5/execution_scheduler.py`, `tests/test_v5_state_and_scheduler.py`

**Review method:** manual code reading + angle-script probing
(automated edge-case Python scripts executed against live module objects).

**Full test run:** 469 tests passed after installing numpy + pyarrow.

---

## Critical Bugs

### BUG-1 · `ExecutionScheduler` silently drops `global` and `dcs` stage formulas

**File:** `sim/v5/execution_scheduler.py`, `__init__`, line 70–77

**Symptom:**  
20 formulas in the registry are **never dispatched** by `run_step()` or
returned by `formulas_for_stage()`.  
These include:

| Stage | Count | Notable formulas |
|-------|-------|-----------------|
| `global` | 17 | `Fe_total`, `Stream`, `mu_slurry`, `rho_slurry`, `hydrophobic_potential`, `u_actual`, `u_sp`, … |
| `dcs` | 3 | `online_froth_proxy`, `online_load_proxy`, **`fx_s{s}_{c}_froth_h`** (manual_closure) |

**Root cause:**  
`_formulas_by_stage` is built only for stages that appear in
`v5_execution_steps.csv`.  `global` and `dcs` are valid stages in the
formula registry but have **no corresponding row** in the execution steps CSV.
The scheduler silently returns an empty list for them instead of raising.

**Impact:**
- `fx_s{s}_{c}_froth_h` (status `manual_closure`) is never executed —
  directly violating V5 rule C005.
- 17 `global` definition formulas (core stream/physics helpers like `Stream`,
  `M_solid`, `mu_slurry`) are never dispatched.  Any formula evaluator that
  relies on the scheduler to run them will silently skip them.
- `online_froth_proxy` and `online_load_proxy` (DCS proxies) are not dispatched.

**Evidence from probe script:**
```
Formulas in registry but NOT in scheduler: 20
  V5M_0521: 'fx_s{s}_{c}_froth_h' stage='dcs' status='manual_closure'
  V5_0052:  'Fe_total'             stage='global' status='canonical'
  ... (18 more)
```

**Suggested fix:**
Options:
1. Add `global` and `dcs` stages to `v5_execution_steps.csv` with appropriate
   step orders (e.g. `000` for global definitions, `360` for dcs proxies).
2. Or: in `ExecutionScheduler.__init__`, after building from step stages,
   also collect formulas from all registry stages and warn/raise on any stage
   not covered by the steps CSV.

---

### BUG-2 · `ExternalInputRegistry` cannot be used as the sole parent-resolution guard

**File:** `sim/v5/external_input_registry.py`

**Symptom:**  
`ExternalInputRegistry.assert_registered("C_feed")` raises
`UnregisteredInputError`, even though `C_feed` is a **valid derived variable**
defined by formula `V5_0002`.

**Root cause:**  
`ExternalInputRegistry` only indexes entries from `v5_external_inputs.csv`.
It has no awareness of formula LHS names.  If a future formula evaluator calls
`ext.assert_registered(parent)` for every parent before resolving it, it will
reject all derived variables.

The intended guard needs to be:
```
parent is valid if:
    parent in formula_registry.by_lhs   # derived/computed
    OR parent in external_input_registry.by_parent  # external/parameter
```

**Impact:**  
Not a bug today (no evaluator uses `assert_registered` for all parents yet),
but the class is architecturally incomplete as a parent-resolution guard.
The module docstring says it enforces "未注册变量访问必须报错" but this only
works correctly for external inputs, not for the full resolution chain.

**Evidence:**
```python
ext.is_registered("C_feed")  # False — but C_feed is a valid formula LHS
ext.is_registered("B_max")   # True  — external parameter, correct
```

**Suggested fix:**  
Add a `resolve(name, formula_registry)` method (or a combined
`ParentResolver` class) that checks both sources. Document clearly that
`assert_registered` only covers the external-input half of the V5 parent
namespace.

---

## Medium Bugs

### BUG-3 · `StateStore.get_or_none()` is ambiguous for `None` values

**File:** `sim/v5/state_store.py`, line 75–77

**Symptom:**  
If a variable is explicitly set to `None`, `get_or_none()` returns `None`.
If the variable has never been written, `get_or_none()` also returns `None`.
The two cases are indistinguishable.

**Evidence:**
```python
store.set('z', None)
store.get_or_none('z')       # None
store.get_or_none('missing') # None — same!
```

**Impact:**  
Formula evaluators using `get_or_none` as a "is this variable ready?" check
will silently treat `None`-valued variables as missing.  Could mask
initialization bugs.

**Suggested fix:**  
Use a sentinel value:
```python
_MISSING = object()

def get_or_none(self, name, default=None):
    return self.current.get(name, default)
```
Or add `has(name: str) -> bool` (distinct from `__contains__`) and document
that `get_or_none` is only safe when `None` is not a legal variable value.

---

### BUG-4 · `StateStore.advance()` drops DCS buffer without a flush hook

**File:** `sim/v5/state_store.py`, line 112–121

**Symptom:**  
`advance()` clears `dcs_buffer` unconditionally.  If the output writer has
not yet read the DCS buffer before `advance()` is called, all DCS values are
lost silently.

**Evidence:**
```python
store.set_dcs('sig1', 42.0)
store.advance()              # dcs_buffer cleared
store.get_dcs('sig1')        # StateStoreError — silently lost
```

**Impact:**  
The PR-2 specification says `advance()` advances to the **next** time step.
The DCS buffer represents values for the **current** step that must be written
to the output file before advancing.  Clearing it in `advance()` creates a
race condition in the caller: the caller must read DCS before advancing, but
nothing enforces this order.

**Suggested fix:**  
Either:
- Save `dcs_buffer` into `previous_dcs` on advance (symmetric with
  `current`→`previous`), so the writer can still read last step's DCS.
- Or add a `flush_dcs() -> dict` method that returns and clears the buffer,
  and document that it must be called before `advance()`.

---

### BUG-5 · `StateStore` only retains one step of history (no lag support)

**File:** `sim/v5/state_store.py`

**Symptom:**  
`advance()` overwrites `previous` with the current step.  Any variable that
requires `t-2` or deeper lag (e.g. multi-step transport delays) cannot be
resolved.

**Evidence:**
```python
store.set('v', 1.0); store.advance()
store.set('v', 2.0); store.advance()
store.get_previous('v')  # 2.0 — step t-1 only; t-2 value 1.0 is lost
```

**Impact:**  
V5 formulas use "lag" and "delayed" references (e.g. buffer delays, transport
lags).  The current StateStore can only resolve `t-1` lag.  Formulas needing
`t-k` (k > 1) require a ring-buffer or explicit delay queue.  This is a
known future limitation but not currently documented.

**Suggested fix:**  
Document the single-step limitation explicitly.  For multi-step lag, a
`DelayBuffer` (already exists at `sim/utils/buffer.py`) should be used
alongside the StateStore.

---

## Low Severity / Design Notes

### NOTE-1 · `StateStore.__contains__` only checks `current`, not `previous`

**File:** `sim/v5/state_store.py`, line 79–80

After `advance()`, `"x" in store` returns `False` even though `x` is
available via `get_previous("x")`.  This is technically correct (the `in`
operator semantically means "is x writable/readable in the current step"),
but it can surprise callers who expect it to mean "has x ever been set."

**Suggested fix:**  
Document clearly in the docstring that `__contains__` is equivalent to
"is x in the current step."

---

### NOTE-2 · `StateStore.snapshot()` is incomplete — omits `previous` and `dcs_buffer`

**File:** `sim/v5/state_store.py`, line 149–151

`snapshot()` returns only `current`.  For debugging and test assertions,
callers often also need the previous step values and DCS buffer.

**Suggested fix:**  
Add `snapshot_full() -> dict` that returns
`{"current": ..., "previous": ..., "dcs_buffer": ...}`.

---

### NOTE-3 · `ExecutionScheduler.run_step()` does not enforce intra-step ordering

**File:** `sim/v5/execution_scheduler.py`, line 155–160

Within a single stage (e.g. `flotation`), `run_step()` iterates formulas in
the order returned by `FormulaRegistry.formulas_by_stage()`, which is
**declaration order in the CSV**.  If two formulas within the same stage have
a causal dependency (A→B), they must appear in the correct order in the CSV
to evaluate correctly.  The scheduler does not validate this.

**Suggested fix:**  
For each stage, perform a topological sort using `v5_causal_edges.csv` before
dispatching.  This is a PR-3/later task but should be noted.

---

### NOTE-4 · `ExternalInputRegistry` silently overwrites duplicate CSV rows

**File:** `sim/v5/external_input_registry.py`, line 56–58

If `v5_external_inputs.csv` ever contains two rows with the same `parent`
name, the second row silently overwrites the first in `by_parent`.

**Evidence from probe:** Currently 0 duplicates in the CSV. But no guard
exists.

**Suggested fix:**
```python
if row.parent in self.by_parent:
    raise ValueError(f"Duplicate external input parent: '{row.parent}'")
```

---

### NOTE-5 · `run_step()` evaluator exceptions propagate unhandled

**File:** `sim/v5/execution_scheduler.py`, line 159–160

If the evaluator raises, the exception propagates immediately, leaving the
StateStore in a partially-written state for that time step.  No rollback or
partial-step reporting mechanism exists.

**Evidence:**
```python
s.run_step(lambda f: raise ValueError("eval error"))
# → ValueError propagated, step partially executed
```

This is acceptable for now (fail-fast is correct), but should be documented.

---

## Summary Table

| ID | Severity | Module | Issue |
|----|----------|--------|-------|
| BUG-1 | Critical | `execution_scheduler.py` | `global`/`dcs` stage formulas (20 total) never dispatched — `fx_s{s}_{c}_froth_h` (manual_closure) silently dropped |
| BUG-2 | Critical | `external_input_registry.py` | Cannot guard formula-derived parents — only covers external inputs; not a complete parent resolver |
| BUG-3 | Medium | `state_store.py` | `get_or_none()` ambiguous when value is `None` |
| BUG-4 | Medium | `state_store.py` | DCS buffer cleared by `advance()` with no flush hook — silent data loss if writer reads after advance |
| BUG-5 | Medium | `state_store.py` | Only 1 step of history; multi-step lag not supported |
| NOTE-1 | Low | `state_store.py` | `__contains__` only checks `current` — undocumented |
| NOTE-2 | Low | `state_store.py` | `snapshot()` incomplete — omits `previous` and `dcs_buffer` |
| NOTE-3 | Low | `execution_scheduler.py` | No intra-stage topological sort; declaration order assumed correct |
| NOTE-4 | Low | `external_input_registry.py` | No duplicate parent guard |
| NOTE-5 | Low | `execution_scheduler.py` | Evaluator exceptions leave StateStore in partial state |

---

*Generated by manual review + angle-script probing, 2026-05-15.*
