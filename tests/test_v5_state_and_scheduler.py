"""Tests for PR-2: StateStore, ExternalInputRegistry, ExecutionScheduler.

Covers the PR-2 requirements:
- execution steps order: boundary -> magnetic -> tower_mill -> flotation -> dcs -> lab -> label
- unregistered parent access fails
- previous_state_reference can be read from StateStore at previous step
- external input classification can be queried
- stage formulas don't include concept/reference roles
- all executable formulas in the registry are dispatched by the scheduler
"""
from __future__ import annotations

import pytest

from sim.v5.spec_loader import load_spec, FormulaRegistry
from sim.v5.state_store import StateStore, StateStoreError
from sim.v5.external_input_registry import ExternalInputRegistry, UnregisteredInputError
from sim.v5.execution_scheduler import ExecutionScheduler


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> FormulaRegistry:
    return load_spec()


@pytest.fixture(scope="module")
def scheduler(registry) -> ExecutionScheduler:
    return ExecutionScheduler(registry)


@pytest.fixture(scope="module")
def ext_inputs(registry) -> ExternalInputRegistry:
    return ExternalInputRegistry(registry)


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class TestStateStore:
    def test_set_and_get(self):
        store = StateStore()
        store.set("alpha", 1.23)
        assert store.get("alpha") == pytest.approx(1.23)

    def test_get_missing_raises(self):
        store = StateStore()
        with pytest.raises(StateStoreError):
            store.get("nonexistent_variable")

    def test_get_or_none_missing(self):
        store = StateStore()
        assert store.get_or_none("x") is None

    def test_contains(self):
        store = StateStore()
        store.set("x", 5)
        assert "x" in store
        assert "y" not in store

    def test_advance_moves_current_to_previous(self):
        store = StateStore()
        store.set("C_feed", 0.65)
        store.advance()
        assert store.get_previous("C_feed") == pytest.approx(0.65)

    def test_previous_state_reference_readable_after_advance(self):
        """previous_state_reference can be read from StateStore at previous step."""
        store = StateStore()
        store.set("C_feed_prev", 0.63)
        store.advance()
        store.set("C_feed_prev", 0.68)  # new current
        prev = store.get_previous("C_feed_prev")
        assert prev == pytest.approx(0.63)

    def test_current_cleared_after_advance(self):
        store = StateStore()
        store.set("mu", 42.0)
        store.advance()
        with pytest.raises(StateStoreError):
            store.get("mu")

    def test_get_previous_missing_raises(self):
        store = StateStore()
        with pytest.raises(StateStoreError):
            store.get_previous("never_written")

    def test_get_previous_or_default(self):
        store = StateStore()
        assert store.get_previous_or_default("x", default=0.0) == 0.0
        store.set("x", 7.0)
        store.advance()
        assert store.get_previous_or_default("x", default=0.0) == pytest.approx(7.0)

    def test_dcs_buffer_set_and_get(self):
        store = StateStore()
        store.set_dcs("P_blower", 102.5)
        assert store.get_dcs("P_blower") == pytest.approx(102.5)

    def test_dcs_buffer_missing_raises(self):
        store = StateStore()
        with pytest.raises(StateStoreError):
            store.get_dcs("unknown_dcs_signal")

    def test_dcs_buffer_cleared_on_advance(self):
        store = StateStore()
        store.set_dcs("P_blower", 99.0)
        store.advance()
        with pytest.raises(StateStoreError):
            store.get_dcs("P_blower")

    def test_snapshot_returns_copy(self):
        store = StateStore()
        store.set("a", 1)
        snap = store.snapshot()
        snap["a"] = 999
        assert store.get("a") == 1  # original unmodified

    def test_multiple_variables_independent(self):
        store = StateStore()
        store.set("x", 1.0)
        store.set("y", 2.0)
        store.advance()
        store.set("x", 3.0)
        assert store.get("x") == pytest.approx(3.0)
        assert store.get_previous("x") == pytest.approx(1.0)
        assert store.get_previous("y") == pytest.approx(2.0)

    def test_has_returns_true_for_current(self):
        store = StateStore()
        store.set("q", 3.14)
        assert store.has("q") is True

    def test_has_returns_false_for_missing(self):
        store = StateStore()
        assert store.has("nonexistent") is False

    def test_has_returns_false_after_advance(self):
        """has() only checks current step — returns False after advance."""
        store = StateStore()
        store.set("z", 5.0)
        store.advance()
        assert store.has("z") is False
        assert store.get_previous("z") == pytest.approx(5.0)

    def test_flush_dcs_returns_buffer_and_clears(self):
        store = StateStore()
        store.set_dcs("P1", 10.0)
        store.set_dcs("P2", 20.0)
        flushed = store.flush_dcs()
        assert flushed == {"P1": 10.0, "P2": 20.0}
        with pytest.raises(StateStoreError):
            store.get_dcs("P1")  # buffer was cleared

    def test_flush_dcs_empty_buffer(self):
        store = StateStore()
        flushed = store.flush_dcs()
        assert flushed == {}

    def test_advance_saves_previous_dcs(self):
        """previous_dcs holds the last step's DCS buffer after advance."""
        store = StateStore()
        store.set_dcs("sig", 99.0)
        store.advance()
        assert store.previous_dcs == {"sig": 99.0}

    def test_advance_clears_dcs_buffer_but_previous_dcs_readable(self):
        """After advance(), dcs_buffer is cleared but previous_dcs still has values."""
        store = StateStore()
        store.set_dcs("sig", 42.0)
        store.advance()
        with pytest.raises(StateStoreError):
            store.get_dcs("sig")  # live buffer is cleared
        assert store.previous_dcs["sig"] == pytest.approx(42.0)

    def test_snapshot_full_returns_all_buffers(self):
        store = StateStore()
        store.set("x", 1.0)
        store.set_dcs("d1", 7.0)
        store.advance()
        store.set("y", 2.0)
        full = store.snapshot_full()
        assert full["current"] == {"y": 2.0}
        assert full["previous"] == {"x": 1.0}
        assert full["previous_dcs"] == {"d1": 7.0}
        assert full["dcs_buffer"] == {}

    def test_snapshot_full_is_copy(self):
        store = StateStore()
        store.set("a", 5)
        full = store.snapshot_full()
        full["current"]["a"] = 999
        assert store.get("a") == 5  # original unmodified


# ---------------------------------------------------------------------------
# ExternalInputRegistry
# ---------------------------------------------------------------------------

class TestExternalInputRegistry:
    def test_initialises_from_registry(self, ext_inputs):
        assert len(ext_inputs.rows) >= 800

    def test_known_parameter_registered(self, ext_inputs):
        # B_max is a parameter in v5_external_inputs.csv
        assert ext_inputs.is_registered("B_max")

    def test_get_classification_parameter(self, ext_inputs):
        cls = ext_inputs.get_classification("B_max")
        assert cls == "parameter"

    def test_get_classification_previous_state(self, ext_inputs):
        # C_feed_prev is a previous_state_reference
        cls = ext_inputs.get_classification("C_feed_prev")
        assert cls == "previous_state_reference"

    def test_assert_registered_passes(self, ext_inputs):
        # should not raise
        ext_inputs.assert_registered("B_max")

    def test_assert_registered_unregistered_raises(self, ext_inputs):
        """Unregistered parent access must raise UnregisteredInputError."""
        with pytest.raises(UnregisteredInputError):
            ext_inputs.assert_registered("this_is_not_a_real_variable_xyz")

    def test_is_registered_false(self, ext_inputs):
        assert not ext_inputs.is_registered("totally_made_up_var_abc123")

    def test_get_row_returns_external_input_row(self, ext_inputs):
        row = ext_inputs.get_row("B_max")
        assert row.parent == "B_max"
        assert row.classification == "parameter"

    def test_get_row_unregistered_raises(self, ext_inputs):
        with pytest.raises(UnregisteredInputError):
            ext_inputs.get_row("not_registered_at_all")

    def test_parents_by_classification_parameter(self, ext_inputs):
        params = ext_inputs.parents_by_classification("parameter")
        assert "B_max" in params
        assert len(params) >= 100

    def test_parents_by_classification_previous_state(self, ext_inputs):
        prev_refs = ext_inputs.parents_by_classification("previous_state_reference")
        assert "C_feed_prev" in prev_refs
        assert len(prev_refs) >= 10

    def test_all_registered_superset(self, ext_inputs):
        all_names = ext_inputs.all_registered()
        assert "B_max" in all_names
        assert "C_feed_prev" in all_names
        assert len(all_names) >= 800

    def test_external_input_classifications_queryable(self, ext_inputs):
        """External input classification can be queried (PR-2 requirement)."""
        known_classifications = {
            row.classification for row in ext_inputs.rows
        }
        # Must include the major expected categories
        assert "parameter" in known_classifications
        assert "previous_state_reference" in known_classifications
        assert "stream_or_state_input" in known_classifications


# ---------------------------------------------------------------------------
# ExecutionScheduler
# ---------------------------------------------------------------------------

class TestExecutionScheduler:
    def test_ordered_stages_correct_sequence(self, scheduler):
        """Execution steps order: boundary -> magnetic -> tower_mill -> flotation -> dcs -> lab -> label."""
        stages = scheduler.ordered_stages()
        expected = ["boundary", "magnetic", "tower_mill", "flotation", "dcs", "lab", "label"]
        assert stages == expected

    def test_steps_loaded(self, scheduler):
        assert len(scheduler.steps) >= 15

    def test_steps_sorted_by_step_order(self, scheduler):
        orders = [int(s.step_order) for s in scheduler.steps]
        assert orders == sorted(orders)

    def test_steps_for_stage_boundary(self, scheduler):
        steps = scheduler.steps_for_stage("boundary")
        assert len(steps) >= 2
        orders = [int(s.step_order) for s in steps]
        assert orders == sorted(orders)

    def test_steps_for_stage_flotation(self, scheduler):
        steps = scheduler.steps_for_stage("flotation")
        assert len(steps) >= 5

    def test_steps_for_stage_unknown_returns_empty(self, scheduler):
        assert scheduler.steps_for_stage("nonexistent_stage") == []

    def test_formulas_for_stage_not_empty(self, scheduler):
        for stage in ["boundary", "magnetic", "tower_mill", "flotation"]:
            formulas = scheduler.formulas_for_stage(stage)
            assert len(formulas) > 0, f"No formulas for stage '{stage}'"

    def test_stage_formulas_do_not_contain_concept_or_reference(self, scheduler):
        """Stage formulas must not include concept/reference roles (PR-2 requirement)."""
        for stage in scheduler.ordered_stages():
            for formula in scheduler.formulas_for_stage(stage):
                assert formula.formula_role not in {"concept", "reference"}, (
                    f"Stage '{stage}' formula {formula.formula_id} "
                    f"has disallowed role '{formula.formula_role}'"
                )

    def test_formulas_for_stage_all_have_executable_or_definition_role(self, scheduler):
        allowed_roles = {"executable", "definition"}
        for stage in scheduler.ordered_stages():
            for formula in scheduler.formulas_for_stage(stage):
                assert formula.formula_role in allowed_roles

    def test_manual_formulas_visible_in_plan(self, scheduler):
        """manual_override/closure/promoted rows are visible in execution plan."""
        manual_statuses = {"manual_override", "manual_closure", "manual_promoted"}
        all_manual = scheduler.all_manual_formulas()
        present_statuses = {f.status for f in all_manual}
        # All three manual status types must appear somewhere in the plan
        assert present_statuses == manual_statuses, (
            f"Expected all of {manual_statuses}, found {present_statuses}"
        )

    def test_manual_formulas_for_magnetic_stage(self, scheduler):
        manual = scheduler.manual_formulas_for_stage("magnetic")
        assert len(manual) > 0

    def test_run_step_calls_evaluator_for_each_formula(self, scheduler):
        called = []
        scheduler.run_step(lambda f: called.append(f.lhs))
        # Each formula should be called exactly once
        assert len(called) > 0
        assert len(called) == len(set(called)), "Duplicate formula lhs in run_step output"
        # Total should match the number of runtime formulas across all stages
        total_runtime = sum(
            len(scheduler.formulas_for_stage(stage))
            for stage in scheduler.ordered_stages()
        )
        assert len(called) == total_runtime

    def test_run_step_stage_filter(self, scheduler):
        called_stages: set = set()

        def evaluator(formula):
            # find which stage this formula belongs to
            for stage, formulas in scheduler._formulas_by_stage.items():
                if formula in formulas:
                    called_stages.add(stage)
                    break

        scheduler.run_step(evaluator, stages=["boundary"])
        assert called_stages == {"boundary"}

    def test_run_step_boundary_formulas_called_before_magnetic(self, scheduler):
        """boundary formulas are called before magnetic in run_step order."""
        seen_stages: list = []

        def evaluator(formula):
            # record stage on first encounter of each stage
            for stage, formulas in scheduler._formulas_by_stage.items():
                if formula in formulas:
                    if not seen_stages or seen_stages[-1] != stage:
                        seen_stages.append(stage)
                    break

        scheduler.run_step(evaluator)
        # Only stages with runtime formulas appear; label has none so is absent
        stages_with_formulas = [
            s for s in ["boundary", "magnetic", "tower_mill", "flotation", "dcs", "lab", "label"]
            if scheduler.formulas_for_stage(s)
        ]
        assert seen_stages == stages_with_formulas

    def test_dcs_stage_in_execution_plan(self, scheduler):
        """dcs stage is present in execution plan (BUG-1 fix)."""
        assert "dcs" in scheduler.ordered_stages()

    def test_dcs_stage_formulas_not_empty(self, scheduler):
        """dcs stage has runtime formulas dispatched (BUG-1 fix)."""
        dcs_formulas = scheduler.formulas_for_stage("dcs")
        assert len(dcs_formulas) > 0

    def test_dcs_stage_positioned_after_flotation(self, scheduler):
        """dcs stage runs after flotation but before lab in pipeline order."""
        stages = scheduler.ordered_stages()
        flotation_idx = stages.index("flotation")
        dcs_idx = stages.index("dcs")
        lab_idx = stages.index("lab")
        assert flotation_idx < dcs_idx < lab_idx

    def test_fx_froth_h_manual_closure_in_dcs_stage(self, scheduler):
        """fx_s{s}_{c}_froth_h (manual_closure) is dispatched in dcs stage (C005 fix)."""
        dcs_formulas = scheduler.formulas_for_stage("dcs")
        lhs_set = {f.lhs for f in dcs_formulas}
        assert "fx_s{s}_{c}_froth_h" in lhs_set

    def test_all_registry_executable_formulas_in_scheduler(self, scheduler, registry):
        """Every 'executable' formula in the registry must be dispatched (BUG-1 guard)."""
        dispatched = {
            f.formula_id
            for stage in scheduler.ordered_stages()
            for f in scheduler.formulas_for_stage(stage)
        }
        for stage, formulas in registry.by_stage.items():
            for formula in formulas:
                if formula.formula_role == "executable":
                    assert formula.formula_id in dispatched, (
                        f"Executable formula {formula.formula_id} ({formula.lhs!r}, "
                        f"stage={stage!r}) is NOT dispatched by the scheduler."
                    )


# ---------------------------------------------------------------------------
# Integration: StateStore + ExternalInputRegistry
# ---------------------------------------------------------------------------

class TestStateAndRegistryIntegration:
    def test_previous_state_reference_parent_is_registered(self, ext_inputs):
        """All previous_state_reference entries should be findable via get_classification."""
        prev_refs = ext_inputs.parents_by_classification("previous_state_reference")
        for parent in prev_refs:
            assert ext_inputs.get_classification(parent) == "previous_state_reference"

    def test_state_store_simulates_previous_state_reference_pattern(self, ext_inputs):
        """Simulate the C_feed / C_feed_prev pattern used in V5 formulas."""
        store = StateStore()

        # Step 0: initialise C_feed
        store.set("C_feed", 0.63)
        store.advance()

        # Step 1: formula reads C_feed_prev (which is the previous C_feed)
        # In V5 spec, C_feed_prev is registered as previous_state_reference
        assert ext_inputs.is_registered("C_feed_prev")

        prev_val = store.get_previous("C_feed")
        # simulate: C_feed_prev = prev C_feed = 0.63
        assert prev_val == pytest.approx(0.63)

    def test_unregistered_parent_raises_when_checked(self, ext_inputs):
        """Accessing an unregistered parent via ExternalInputRegistry must fail."""
        with pytest.raises(UnregisteredInputError):
            ext_inputs.assert_registered("invented_temp_variable_xyz")
