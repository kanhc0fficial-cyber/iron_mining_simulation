"""V5 ExecutionScheduler — step-ordered stage dispatcher.

The scheduler reads ``v5_execution_steps.csv`` (via :class:`FormulaRegistry`)
and drives each simulation time step by:

1. Sorting execution steps by ``step_order`` (numeric ascending).
2. For each step, resolving the corresponding formula list from the registry
   (filtering to executable/definition/manual_* formula_roles only, to
   exclude ``concept`` and ``reference`` rows from runtime dispatch).
3. Calling a user-supplied evaluator for each formula, or providing the
   ordered lists for the caller to iterate.

Usage
-----
    from sim.v5.spec_loader import load_spec
    from sim.v5.execution_scheduler import ExecutionScheduler

    registry = load_spec()
    scheduler = ExecutionScheduler(registry)

    for stage in scheduler.ordered_stages():
        formulas = scheduler.formulas_for_stage(stage)
        ...
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from sim.v5.spec_loader import ExecutionStepRow, FormulaRegistry, FormulaRow


# Formula roles that are dispatched to the evaluator.  Rows tagged
# ``concept`` or ``reference`` exist only for documentation and must NOT
# enter runtime dispatch.
_RUNTIME_ROLES = frozenset({"executable", "definition"})

# Statuses with manual authority — must appear in the execution plan.
_MANUAL_STATUSES = frozenset({"manual_override", "manual_closure", "manual_promoted"})


class ExecutionScheduler:
    """Stage-ordered dispatcher for V5 formula execution.

    Parameters
    ----------
    registry :
        A loaded :class:`~sim.v5.spec_loader.FormulaRegistry`.

    Attributes
    ----------
    steps : list[ExecutionStepRow]
        Execution steps sorted by ``step_order`` (numeric ascending).
    """

    def __init__(self, registry: FormulaRegistry) -> None:
        self._registry = registry

        # Sort steps by numeric step_order (CSV stores them as strings like "010")
        self.steps: List[ExecutionStepRow] = sorted(
            registry.execution_steps,
            key=lambda s: int(s.step_order),
        )

        # Build stage -> sorted steps mapping
        self._steps_by_stage: Dict[str, List[ExecutionStepRow]] = {}
        for step in self.steps:
            self._steps_by_stage.setdefault(step.stage, []).append(step)

        # Build stage -> runtime formulas mapping (concept/reference excluded)
        self._formulas_by_stage: Dict[str, List[FormulaRow]] = {}
        for step in self.steps:
            stage = step.stage
            if stage not in self._formulas_by_stage:
                raw = registry.formulas_by_stage(stage)
                self._formulas_by_stage[stage] = [
                    f for f in raw if f.formula_role in _RUNTIME_ROLES
                ]

    # ------------------------------------------------------------------
    # Stage / step access
    # ------------------------------------------------------------------

    def ordered_stages(self) -> List[str]:
        """Return the unique stage names in ascending step_order.

        Duplicate stage names are deduplicated while preserving order; the
        result is the canonical pipeline order.
        """
        seen: set = set()
        result: List[str] = []
        for step in self.steps:
            if step.stage not in seen:
                seen.add(step.stage)
                result.append(step.stage)
        return result

    def steps_for_stage(self, stage: str) -> List[ExecutionStepRow]:
        """Return execution step rows for *stage* in step_order."""
        return list(self._steps_by_stage.get(stage, []))

    def formulas_for_stage(self, stage: str) -> List[FormulaRow]:
        """Return runtime formula rows for *stage*.

        ``concept`` and ``reference`` formula_role rows are excluded; only
        ``executable`` and ``definition`` rows are returned.
        """
        return list(self._formulas_by_stage.get(stage, []))

    # ------------------------------------------------------------------
    # Manual authority visibility
    # ------------------------------------------------------------------

    def manual_formulas_for_stage(self, stage: str) -> List[FormulaRow]:
        """Return manual_override/closure/promoted rows for *stage*.

        These rows must be visible in the execution plan (PR-2 requirement:
        *"manual_override/manual_closure/manual_promoted 标记在执行计划中可见"*).
        """
        return [
            f for f in self.formulas_for_stage(stage)
            if f.status in _MANUAL_STATUSES
        ]

    def all_manual_formulas(self) -> List[FormulaRow]:
        """Return all manual_override/closure/promoted rows across all stages."""
        result: List[FormulaRow] = []
        for stage in self.ordered_stages():
            result.extend(self.manual_formulas_for_stage(stage))
        return result

    # ------------------------------------------------------------------
    # Execution driver
    # ------------------------------------------------------------------

    def run_step(
        self,
        evaluator: Callable[[FormulaRow], None],
        stages: Optional[List[str]] = None,
    ) -> None:
        """Drive a single simulation time step.

        For each stage (in step_order), calls *evaluator* once per runtime
        formula in that stage.

        Parameters
        ----------
        evaluator :
            A callable that accepts a :class:`FormulaRow` and performs the
            actual formula evaluation (writing outputs to a
            :class:`~sim.v5.state_store.StateStore`, for example).
        stages :
            Optional whitelist of stage names to execute.  If ``None``,
            all stages are executed.
        """
        target_stages = set(stages) if stages is not None else None
        for stage in self.ordered_stages():
            if target_stages is not None and stage not in target_stages:
                continue
            for formula in self._formulas_by_stage.get(stage, []):
                evaluator(formula)
