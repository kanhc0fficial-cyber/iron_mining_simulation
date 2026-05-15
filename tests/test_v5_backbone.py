from __future__ import annotations

from pathlib import Path

import pytest

from sim.v5_backbone import (
    V5ExecutionBackbone,
    V5MissingExternalInputError,
    V5MissingParentValueError,
)


@pytest.fixture(scope="module")
def backbone() -> V5ExecutionBackbone:
    repo_root = Path(__file__).resolve().parent.parent
    return V5ExecutionBackbone(repo_root=repo_root)


def test_execution_plan_is_step_ordered(backbone: V5ExecutionBackbone) -> None:
    orders = [step.step_order for step in backbone.execution_plan]
    stages = [step.stage for step in backbone.execution_plan]
    assert orders == sorted(orders)
    assert stages == ["boundary", "magnetic", "tower_mill", "flotation", "dcs", "lab", "label"]


def test_formula_records_traverse_stage_then_formula_order(backbone: V5ExecutionBackbone) -> None:
    formulas = backbone.formulas_in_stage_order()
    stage_positions = {step.stage: idx for idx, step in enumerate(backbone.execution_plan)}

    assert formulas, "Expected executable formulas in the execution plan."
    for prev, curr in zip(formulas, formulas[1:]):
        prev_stage_idx = stage_positions[prev.stage]
        curr_stage_idx = stage_positions[curr.stage]
        assert prev_stage_idx <= curr_stage_idx
        if prev_stage_idx == curr_stage_idx:
            prev_key = int(prev.source_v4_line) if prev.source_v4_line.isdigit() else 10**9
            curr_key = int(curr.source_v4_line) if curr.source_v4_line.isdigit() else 10**9
            assert prev_key <= curr_key


def test_missing_external_input_error_is_clear(backbone: V5ExecutionBackbone) -> None:
    formula = next(
        f
        for f in backbone.formulas_in_stage_order()
        if any(dep in backbone.external_input_names for dep in f.parents)
    )
    missing_dep = next(dep for dep in formula.parents if dep in backbone.external_input_names)
    context = backbone.create_context()

    with pytest.raises(V5MissingExternalInputError, match=missing_dep):
        backbone.ensure_formula_parents_present(context, formula)

    with pytest.raises(V5MissingExternalInputError) as excinfo:
        backbone.ensure_formula_parents_present(context, formula)
    message = str(excinfo.value)
    assert formula.formula_id in message
    assert formula.lhs in message
    assert formula.stage in message


def test_missing_parent_value_error_is_clear(backbone: V5ExecutionBackbone) -> None:
    formula = next(
        f
        for f in backbone.formulas_in_stage_order()
        if any(dep in backbone.formula_index for dep in f.parents)
        and all(dep in backbone.external_input_names or dep in backbone.formula_index for dep in f.parents)
    )
    context = backbone.create_context(
        external_inputs={name: 1.0 for name in backbone.external_input_names}
    )

    with pytest.raises(V5MissingParentValueError) as excinfo:
        backbone.ensure_formula_parents_present(context, formula)
    message = str(excinfo.value)
    assert formula.formula_id in message
    assert formula.lhs in message
    assert formula.stage in message


def test_dcs_sinks_are_distinct_from_executable_formulas(backbone: V5ExecutionBackbone) -> None:
    dcs_names = set(backbone.dcs_output_names)
    assert dcs_names

    context = backbone.create_context()
    context.set_dcs_output(next(iter(dcs_names)), 1.0)
    assert context.dcs_outputs
    assert context.executable_formulas
    assert context.dcs_outputs is not context.executable_formulas
