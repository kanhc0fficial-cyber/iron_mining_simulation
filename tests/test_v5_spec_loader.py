"""Tests for sim.v5.spec_loader — V5 CSV spec loader and FormulaRegistry."""
from __future__ import annotations

import pytest
from pathlib import Path

from sim.v5.spec_loader import (
    FormulaRegistry,
    SpecLoader,
    SpecValidationError,
    load_spec,
    _reject_v5_formulas_csv,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> FormulaRegistry:
    """Load the real V5 spec once for the whole module."""
    return load_spec()


# ---------------------------------------------------------------------------
# Loading: all V5 CSVs are readable
# ---------------------------------------------------------------------------

class TestSpecLoading:
    def test_loads_without_error(self, registry):
        assert registry is not None

    def test_formula_count_matches_autocheck(self, registry):
        # V5_CLEAN_AUTOCHECK.md reports 443 executable formulas; check >= 400
        # so the test remains valid as the spec evolves.
        assert len(registry.formulas) >= 400

    def test_variables_count_matches_autocheck(self, registry):
        # V5_CLEAN_AUTOCHECK.md reports 523 variables.
        assert len(registry.variables) >= 500

    def test_external_inputs_count_matches_autocheck(self, registry):
        # V5_CLEAN_AUTOCHECK.md reports 848 registered external/input parents.
        assert len(registry.external_inputs) >= 800

    def test_dcs_outputs_loaded(self, registry):
        # V5_CLEAN_AUTOCHECK.md reports 70 DCS rows.
        assert len(registry.dcs_outputs) >= 60

    def test_constraints_loaded(self, registry):
        assert len(registry.constraints) >= 6

    def test_causal_edges_loaded(self, registry):
        assert len(registry.causal_edges) > 0

    def test_execution_steps_loaded(self, registry):
        assert len(registry.execution_steps) > 0

    def test_all_stages_indexed(self, registry):
        expected_stages = {"boundary", "magnetic", "tower_mill", "flotation", "lab"}
        assert expected_stages <= set(registry.by_stage.keys())


# ---------------------------------------------------------------------------
# FormulaRegistry indexes
# ---------------------------------------------------------------------------

class TestFormulaRegistryIndexes:
    def test_by_id_covers_all_formulas(self, registry):
        assert len(registry.by_id) == len(registry.formulas)

    def test_by_lhs_covers_all_formulas(self, registry):
        assert len(registry.by_lhs) == len(registry.formulas)

    def test_no_duplicate_lhs(self, registry):
        # This is guaranteed by the registry constructor; just verify.
        lhs_values = [r.lhs for r in registry.formulas]
        assert len(lhs_values) == len(set(lhs_values))

    def test_by_stage_sum_equals_total(self, registry):
        total = sum(len(v) for v in registry.by_stage.values())
        assert total == len(registry.formulas)

    def test_parents_of_returns_tuple(self, registry):
        parents = registry.dependency_list("B_eff")
        assert isinstance(parents, tuple)
        assert len(parents) > 0

    def test_parents_of_unknown_lhs_returns_empty(self, registry):
        assert registry.dependency_list("__nonexistent__") == ()

    def test_registered_external_parents_nonempty(self, registry):
        ext = registry.registered_external_parents()
        assert len(ext) > 0


# ---------------------------------------------------------------------------
# Specific parent-set checks (from PR requirements)
# ---------------------------------------------------------------------------

class TestSpecificParents:
    def test_quality_proxy_s_includes_mean_froth_h_lag(self, registry):
        parents = registry.dependency_list("quality_proxy_s")
        assert "mean_froth_h_lag" in parents

    def test_feed_j_rate_includes_Q_pump_pool_s1(self, registry):
        parents = registry.dependency_list("feed_j_rate_{s,c}")
        assert "Q_pump_pool_{s,1}" in parents

    def test_feed_j_rate_includes_Q_pump_pool_s2(self, registry):
        parents = registry.dependency_list("feed_j_rate_{s,c}")
        assert "Q_pump_pool_{s,2}" in parents

    def test_feed_j_rate_includes_Q_pump_pool_s3(self, registry):
        parents = registry.dependency_list("feed_j_rate_{s,c}")
        assert "Q_pump_pool_{s,3}" in parents

    def test_froth_h_includes_event_froth_fault(self, registry):
        parents = registry.dependency_list("fx_s{s}_{c}_froth_h")
        assert "event_froth_fault_{s,c}" in parents


# ---------------------------------------------------------------------------
# Structural validation rules
# ---------------------------------------------------------------------------

class TestStructuralValidation:
    def test_no_forbidden_statuses_in_executable_csv(self, registry):
        allowed = {"canonical", "manual_promoted", "manual_override", "manual_closure"}
        for row in registry.formulas:
            assert row.status in allowed, (
                f"Row {row.formula_id} has forbidden status '{row.status}'"
            )

    def test_formula_roles_are_executable_or_definition(self, registry):
        allowed_roles = {"executable", "definition"}
        for row in registry.formulas:
            assert row.formula_role in allowed_roles, (
                f"Row {row.formula_id} has unexpected role '{row.formula_role}'"
            )

    def test_manual_override_formulas_present(self, registry):
        overrides = list(registry.iter_by_status("manual_override"))
        assert len(overrides) > 0, "manual_override formulas must not be lost"

    def test_manual_closure_formulas_present(self, registry):
        closures = list(registry.iter_by_status("manual_closure"))
        assert len(closures) > 0, "manual_closure formulas must not be lost"

    def test_manual_promoted_formulas_present(self, registry):
        promoted = list(registry.iter_by_status("manual_promoted"))
        assert len(promoted) > 0, "manual_promoted formulas must not be lost"

    def test_all_parents_are_registered(self, registry):
        """Every parent must resolve to a known LHS or registered external input."""
        known_lhs = frozenset(registry.by_lhs)
        known_ext = registry.registered_external_parents()
        valid = known_lhs | known_ext
        orphans = []
        for row in registry.formulas:
            for parent in row.parents:
                if parent not in valid:
                    orphans.append((row.formula_id, row.lhs, parent))
        assert orphans == [], (
            f"Unregistered parents found: {orphans[:5]}"
        )


# ---------------------------------------------------------------------------
# Rule C004: runtime entry must refuse v5_formulas.csv
# ---------------------------------------------------------------------------

class TestForbiddenFile:
    def test_reject_v5_formulas_csv_by_path(self):
        """_reject_v5_formulas_csv must raise on the forbidden filename."""
        with pytest.raises(SpecValidationError, match="v5_formulas.csv"):
            _reject_v5_formulas_csv(Path("/any/dir/v5_formulas.csv"))

    def test_reject_v5_formulas_csv_by_string(self):
        with pytest.raises(SpecValidationError, match="v5_formulas.csv"):
            _reject_v5_formulas_csv("redesign_formula_docs/v5_formulas.csv")

    def test_allow_v5_executable_formulas_csv(self):
        """_reject_v5_formulas_csv must NOT raise for the correct file."""
        _reject_v5_formulas_csv(Path("/any/dir/v5_executable_formulas.csv"))

    def test_spec_loader_executable_attribute_is_not_forbidden(self):
        """SpecLoader.EXECUTABLE_FORMULAS_FILE must never be the forbidden name."""
        assert SpecLoader.EXECUTABLE_FORMULAS_FILE != "v5_formulas.csv"

    def test_load_spec_does_not_use_v5_formulas_csv(self, tmp_path):
        """load_spec from a directory with only v5_formulas.csv should raise FileNotFoundError."""
        # Copy the forbidden file but NOT the executable file into tmp dir.
        import shutil
        from pathlib import Path as P

        spec_dir = P(__file__).parents[1] / "redesign_formula_docs"
        shutil.copy(spec_dir / "v5_formulas.csv", tmp_path / "v5_formulas.csv")
        # Attempting to load should fail because v5_executable_formulas.csv is absent.
        with pytest.raises(FileNotFoundError):
            load_spec(tmp_path)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    def test_formulas_by_stage_boundary(self, registry):
        rows = registry.formulas_by_stage("boundary")
        assert len(rows) > 0
        assert all(r.stage == "boundary" for r in rows)

    def test_formulas_by_stage_flotation(self, registry):
        rows = registry.formulas_by_stage("flotation")
        assert len(rows) > 0

    def test_formulas_by_stage_unknown_returns_empty(self, registry):
        assert registry.formulas_by_stage("__unknown_stage__") == []

    def test_iter_by_status_canonical(self, registry):
        canonical = list(registry.iter_by_status("canonical"))
        assert len(canonical) > 0

    def test_formula_row_has_rhs(self, registry):
        row = registry.by_lhs["B_eff"]
        assert row.rhs != ""

    def test_formula_row_has_stage(self, registry):
        row = registry.by_lhs["B_eff"]
        assert row.stage == "magnetic"
