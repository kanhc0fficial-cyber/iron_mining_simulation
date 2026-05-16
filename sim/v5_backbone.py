from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sim.v5_spec import V5ExecutableFormula, load_v5_clean_spec


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_{}]*")
_KNOWN_CALL_NAMES = frozenset(
    {
        "abs",
        "clip",
        "exp",
        "log",
        "log1p",
        "max",
        "min",
        "pow",
        "sigmoid",
        "sqrt",
        "sum",
        "thermal_derate",
    }
)


@dataclass(frozen=True)
class V5PlanFormula:
    formula_id: str
    stage: str
    lhs: str
    rhs: str
    parents: tuple[str, ...]
    source_v4_line: str


@dataclass(frozen=True)
class V5ExecutionPlanItem:
    step_order: int
    stage: str
    description: str
    formulas: tuple[V5PlanFormula, ...]


@dataclass
class V5ExecutionContext:
    external_inputs: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    values: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    executable_formulas: dict[str, V5PlanFormula] = field(default_factory=dict)
    dcs_outputs: dict[str, float | int | str | bool | None] = field(default_factory=dict)

    def set_external_inputs(self, values: dict[str, float | int | str | bool | None]) -> None:
        self.external_inputs = dict(values)

    def set_value(self, name: str, value: float | int | str | bool | None) -> None:
        self.values[name] = value

    def set_dcs_output(self, name: str, value: float | int | str | bool | None) -> None:
        self.dcs_outputs[name] = value


class V5BackboneError(ValueError):
    pass


class V5MissingExternalInputError(V5BackboneError):
    pass


class V5MissingParentValueError(V5BackboneError):
    pass


class V5ExecutionBackbone:
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.spec = load_v5_clean_spec(repo_root=repo_root)
        self.external_input_names = frozenset(row.parent for row in self.spec.external_inputs)
        self.formulas_by_lhs = {row.lhs: row for row in self.spec.formulas}
        self.dcs_output_names = frozenset(row.dcs_name for row in self.spec.dcs_outputs)
        self.execution_plan = self._build_execution_plan()
        self.formula_index = {
            formula.lhs: formula
            for step in self.execution_plan
            for formula in step.formulas
        }

    def create_context(
        self,
        external_inputs: dict[str, float | int | str | bool | None] | None = None,
        values: dict[str, float | int | str | bool | None] | None = None,
        dcs_outputs: dict[str, float | int | str | bool | None] | None = None,
    ) -> V5ExecutionContext:
        return V5ExecutionContext(
            external_inputs=dict(external_inputs or {}),
            values=dict(values or {}),
            executable_formulas=dict(self.formula_index),
            dcs_outputs=dict(dcs_outputs or {}),
        )

    def formulas_in_stage_order(self) -> list[V5PlanFormula]:
        formulas: list[V5PlanFormula] = []
        for item in self.execution_plan:
            formulas.extend(item.formulas)
        return formulas

    def ensure_formula_parents_present(
        self,
        context: V5ExecutionContext,
        formula: V5PlanFormula,
    ) -> tuple[str, ...]:
        missing_external: list[str] = []
        missing_parent_values: list[str] = []
        for dep in formula.parents:
            if dep in context.values:
                continue
            if dep in context.external_inputs:
                continue
            if dep in self.external_input_names:
                missing_external.append(dep)
                continue
            if dep in context.executable_formulas:
                missing_parent_values.append(dep)
                continue
            missing_external.append(dep)

        if missing_external:
            raise V5MissingExternalInputError(
                f"Missing external input(s) {sorted(set(missing_external))} for formula "
                f"{formula.formula_id} (lhs={formula.lhs}, stage={formula.stage})."
            )
        if missing_parent_values:
            raise V5MissingParentValueError(
                f"Missing parent value(s) {sorted(set(missing_parent_values))} for formula "
                f"{formula.formula_id} (lhs={formula.lhs}, stage={formula.stage})."
            )
        return formula.parents

    def _build_execution_plan(self) -> list[V5ExecutionPlanItem]:
        formulas_by_stage: dict[str, list[V5ExecutableFormula]] = {}
        for formula in self.spec.formulas:
            formulas_by_stage.setdefault(formula.stage, []).append(formula)

        plan: list[V5ExecutionPlanItem] = []
        seen_stages: set[str] = set()
        for step in sorted(self.spec.execution_steps, key=lambda row: int(row.step_order)):
            if step.stage in seen_stages:
                continue
            seen_stages.add(step.stage)
            stage_formulas = formulas_by_stage.get(step.stage, [])
            ordered = sorted(stage_formulas, key=self._formula_order_key)
            plan.append(
                V5ExecutionPlanItem(
                    step_order=int(step.step_order),
                    stage=step.stage,
                    description=step.description,
                    formulas=tuple(self._to_plan_formula(f) for f in ordered),
                )
            )
        return plan

    @staticmethod
    def _to_plan_formula(formula: V5ExecutableFormula) -> V5PlanFormula:
        return V5PlanFormula(
            formula_id=formula.formula_id,
            stage=formula.stage,
            lhs=formula.lhs,
            rhs=formula.rhs,
            parents=extract_formula_dependencies(formula.parents, formula.rhs),
            source_v4_line=formula.source_v4_line,
        )

    @staticmethod
    def _formula_order_key(formula: V5ExecutableFormula) -> tuple[int, str]:
        if formula.source_v4_line.isdigit():
            return int(formula.source_v4_line), formula.formula_id
        return 10**9, formula.formula_id


def extract_formula_dependencies(parents_text: str, rhs: str) -> tuple[str, ...]:
    if parents_text.strip():
        return tuple(token.strip() for token in parents_text.split(";") if token.strip())

    ordered: list[str] = []
    for token in _IDENTIFIER_PATTERN.findall(rhs):
        if token in _KNOWN_CALL_NAMES or token == "e":
            continue
        if token not in ordered:
            ordered.append(token)
    return tuple(ordered)
