"""V5 CSV spec loader and FormulaRegistry.

Loads the V5 clean specification CSV files and builds indexed, validated
data structures for use by the simulation engine.  This module does NOT
execute any formula RHS — it is purely structural loading and validation.

Usage
-----
    from sim.v5.spec_loader import load_spec

    registry = load_spec()          # uses default redesign_formula_docs/ path
    row = registry.by_lhs["B_eff"]  # FormulaRow namedtuple
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, FrozenSet, Iterator, List, NamedTuple, Optional, Sequence


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_DIR = _REPO_ROOT / "redesign_formula_docs"

# Name of the *forbidden* runtime file.  The loader raises immediately when
# a caller tries to point it at this file (rule C004).
_FORBIDDEN_FILENAME = "v5_formulas.csv"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class FormulaRow(NamedTuple):
    formula_id: str
    stage: str
    source_v4_line: str
    source_v4_section: str
    lhs: str
    rhs: str
    formula_line: str
    parents: FrozenSet[str]
    state_type: str
    formula_role: str
    observable: str
    status: str
    notes: str

    @classmethod
    def from_dict(cls, d: dict) -> "FormulaRow":
        raw_parents = d.get("parents", "") or ""
        parents = frozenset(p.strip() for p in raw_parents.split(";") if p.strip())
        return cls(
            formula_id=d["formula_id"],
            stage=d["stage"],
            source_v4_line=d.get("source_v4_line", ""),
            source_v4_section=d.get("source_v4_section", ""),
            lhs=d["lhs"],
            rhs=d.get("rhs", ""),
            formula_line=d.get("formula_line", ""),
            parents=parents,
            state_type=d.get("state_type", ""),
            formula_role=d.get("formula_role", ""),
            observable=d.get("observable", ""),
            status=d["status"],
            notes=d.get("notes", ""),
        )


class VariableRow(NamedTuple):
    variable: str
    stage: str
    state_type: str
    defined_by_formula_id: str
    source_v4_line: str
    observable: str
    notes: str

    @classmethod
    def from_dict(cls, d: dict) -> "VariableRow":
        return cls(
            variable=d["variable"],
            stage=d["stage"],
            state_type=d.get("state_type", ""),
            defined_by_formula_id=d.get("defined_by_formula_id", ""),
            source_v4_line=d.get("source_v4_line", ""),
            observable=d.get("observable", ""),
            notes=d.get("notes", ""),
        )


class ExternalInputRow(NamedTuple):
    parent: str
    classification: str
    used_by_lhs: FrozenSet[str]
    stages: FrozenSet[str]
    source_v4_lines: str
    notes: str

    @classmethod
    def from_dict(cls, d: dict) -> "ExternalInputRow":
        raw_lhs = d.get("used_by_lhs", "") or ""
        used_by = frozenset(l.strip() for l in raw_lhs.split(";") if l.strip())
        raw_stages = d.get("stages", "") or ""
        stages = frozenset(s.strip() for s in raw_stages.split(";") if s.strip())
        return cls(
            parent=d["parent"],
            classification=d["classification"],
            used_by_lhs=used_by,
            stages=stages,
            source_v4_lines=d.get("source_v4_lines", ""),
            notes=d.get("notes", ""),
        )


class DCSOutputRow(NamedTuple):
    dcs_name: str
    physical_parent: str
    listed_v4_lines: str
    meas_v4_line: str
    listed_sections: str
    meas_section: str
    migration_status: str
    notes: str

    @classmethod
    def from_dict(cls, d: dict) -> "DCSOutputRow":
        return cls(
            dcs_name=d["dcs_name"],
            physical_parent=d.get("physical_parent", ""),
            listed_v4_lines=d.get("listed_v4_lines", ""),
            meas_v4_line=d.get("meas_v4_line", ""),
            listed_sections=d.get("listed_sections", ""),
            meas_section=d.get("meas_section", ""),
            migration_status=d.get("migration_status", ""),
            notes=d.get("notes", ""),
        )


class ConstraintRow(NamedTuple):
    constraint_id: str
    category: str
    applies_to: str
    rule: str
    implementation_check: str
    source: str

    @classmethod
    def from_dict(cls, d: dict) -> "ConstraintRow":
        return cls(
            constraint_id=d["constraint_id"],
            category=d["category"],
            applies_to=d.get("applies_to", ""),
            rule=d.get("rule", ""),
            implementation_check=d.get("implementation_check", ""),
            source=d.get("source", ""),
        )


class CausalEdgeRow(NamedTuple):
    from_variable: str
    to_variable: str
    stage: str
    formula_id: str
    edge_type: str
    source_v4_line: str

    @classmethod
    def from_dict(cls, d: dict) -> "CausalEdgeRow":
        return cls(
            from_variable=d["from_variable"],
            to_variable=d["to_variable"],
            stage=d.get("stage", ""),
            formula_id=d.get("formula_id", ""),
            edge_type=d.get("edge_type", ""),
            source_v4_line=d.get("source_v4_line", ""),
        )


class ExecutionStepRow(NamedTuple):
    step_order: str
    stage: str
    description: str

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionStepRow":
        return cls(
            step_order=d["step_order"],
            stage=d["stage"],
            description=d.get("description", ""),
        )


# ---------------------------------------------------------------------------
# Allowed statuses / roles in the executable CSV
# ---------------------------------------------------------------------------

_ALLOWED_STATUSES = frozenset({
    "canonical",
    "manual_promoted",
    "manual_override",
    "manual_closure",
})

_REQUIRED_STATUSES = frozenset({
    "manual_override",
    "manual_closure",
    "manual_promoted",
})

_ALLOWED_ROLES = frozenset({"executable", "definition"})


# ---------------------------------------------------------------------------
# FormulaRegistry
# ---------------------------------------------------------------------------

class FormulaRegistry:
    """Indexed view of the V5 executable formula specification.

    Attributes
    ----------
    formulas : list[FormulaRow]
        All rows from v5_executable_formulas.csv.
    by_id : dict[str, FormulaRow]
        formula_id -> FormulaRow.
    by_lhs : dict[str, FormulaRow]
        lhs -> FormulaRow (unique; duplicate LHS triggers validation error).
    by_stage : dict[str, list[FormulaRow]]
        stage -> list of FormulaRow in declaration order.
    parents_of : dict[str, frozenset[str]]
        lhs -> frozenset of parent variable names.
    variables : list[VariableRow]
        All rows from v5_variables.csv.
    external_inputs : list[ExternalInputRow]
        All rows from v5_external_inputs.csv.
    dcs_outputs : list[DCSOutputRow]
        All rows from v5_dcs_outputs.csv.
    constraints : list[ConstraintRow]
        All rows from v5_implementation_constraints.csv.
    causal_edges : list[CausalEdgeRow]
        All rows from v5_causal_edges.csv.
    execution_steps : list[ExecutionStepRow]
        All rows from v5_execution_steps.csv.
    """

    def __init__(
        self,
        formulas: List[FormulaRow],
        variables: List[VariableRow],
        external_inputs: List[ExternalInputRow],
        dcs_outputs: List[DCSOutputRow],
        constraints: List[ConstraintRow],
        causal_edges: List[CausalEdgeRow],
        execution_steps: List[ExecutionStepRow],
    ) -> None:
        self.formulas = formulas
        self.variables = variables
        self.external_inputs = external_inputs
        self.dcs_outputs = dcs_outputs
        self.constraints = constraints
        self.causal_edges = causal_edges
        self.execution_steps = execution_steps

        # Build indexes
        self.by_id: Dict[str, FormulaRow] = {}
        self.by_lhs: Dict[str, FormulaRow] = {}
        self.by_stage: Dict[str, List[FormulaRow]] = defaultdict(list)
        self.parents_of: Dict[str, FrozenSet[str]] = {}

        for row in formulas:
            self.by_id[row.formula_id] = row
            self.by_stage[row.stage].append(row)
            self.parents_of[row.lhs] = row.parents

        for row in formulas:
            if row.lhs in self.by_lhs:
                raise SpecValidationError(
                    f"Duplicate LHS in executable formulas: '{row.lhs}' "
                    f"(ids {self.by_lhs[row.lhs].formula_id} and {row.formula_id})"
                )
            self.by_lhs[row.lhs] = row

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def formulas_by_stage(self, stage: str) -> List[FormulaRow]:
        """Return formulas for *stage* in declaration order."""
        return list(self.by_stage.get(stage, []))

    def dependency_list(self, lhs: str) -> FrozenSet[str]:
        """Return the parent set for *lhs*; empty frozenset if not found."""
        return self.parents_of.get(lhs, frozenset())

    def iter_by_status(self, status: str) -> Iterator[FormulaRow]:
        """Iterate formulas whose status matches *status*."""
        for row in self.formulas:
            if row.status == status:
                yield row

    def registered_external_parents(self) -> FrozenSet[str]:
        """Return the set of all registered external/input parent names."""
        return frozenset(ei.parent for ei in self.external_inputs)


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

class SpecValidationError(ValueError):
    """Raised when the loaded V5 spec violates a structural constraint."""


# ---------------------------------------------------------------------------
# SpecLoader
# ---------------------------------------------------------------------------

class SpecLoader:
    """Loads V5 CSV spec files from a given directory.

    Parameters
    ----------
    spec_dir : Path | str | None
        Path to the directory containing the V5 CSV files.
        Defaults to ``redesign_formula_docs/`` in the repository root.
    """

    EXECUTABLE_FORMULAS_FILE = "v5_executable_formulas.csv"
    EXECUTION_STEPS_FILE = "v5_execution_steps.csv"
    VARIABLES_FILE = "v5_variables.csv"
    EXTERNAL_INPUTS_FILE = "v5_external_inputs.csv"
    DCS_OUTPUTS_FILE = "v5_dcs_outputs.csv"
    CONSTRAINTS_FILE = "v5_implementation_constraints.csv"
    CAUSAL_EDGES_FILE = "v5_causal_edges.csv"

    def __init__(self, spec_dir: Optional[Path | str] = None) -> None:
        if spec_dir is None:
            spec_dir = _SPEC_DIR
        self._dir = Path(spec_dir).resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> FormulaRegistry:
        """Load all V5 CSV files, validate, and return a :class:`FormulaRegistry`.

        Raises
        ------
        SpecValidationError
            If any structural constraint is violated.
        FileNotFoundError
            If any required CSV file is missing.
        """
        self._reject_forbidden_files()

        formulas = self._load_formulas()
        variables = self._load_variables()
        external_inputs = self._load_external_inputs()
        dcs_outputs = self._load_dcs_outputs()
        constraints = self._load_constraints()
        causal_edges = self._load_causal_edges()
        execution_steps = self._load_execution_steps()

        # Build registry (duplicate-LHS check happens inside __init__)
        registry = FormulaRegistry(
            formulas=formulas,
            variables=variables,
            external_inputs=external_inputs,
            dcs_outputs=dcs_outputs,
            constraints=constraints,
            causal_edges=causal_edges,
            execution_steps=execution_steps,
        )

        # Additional structural validations
        self._validate_statuses_and_roles(formulas)
        self._validate_required_statuses_present(formulas)
        self._validate_parents(registry)

        return registry

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _reject_forbidden_files(self) -> None:
        """Raise if the spec directory contains an attempt to use the forbidden file."""
        forbidden = self._dir / _FORBIDDEN_FILENAME
        # Check whether a caller explicitly placed v5_formulas.csv as the
        # executable file by overriding the constant (defensive guard).
        if self.EXECUTABLE_FORMULAS_FILE == _FORBIDDEN_FILENAME:
            raise SpecValidationError(
                f"Runtime formula engine must not read '{_FORBIDDEN_FILENAME}'. "
                "Use 'v5_executable_formulas.csv' instead (rule C004)."
            )

    @staticmethod
    def _read_csv(path: Path) -> List[dict]:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def _load_formulas(self) -> List[FormulaRow]:
        path = self._dir / self.EXECUTABLE_FORMULAS_FILE
        rows = self._read_csv(path)
        return [FormulaRow.from_dict(r) for r in rows]

    def _load_variables(self) -> List[VariableRow]:
        path = self._dir / self.VARIABLES_FILE
        rows = self._read_csv(path)
        return [VariableRow.from_dict(r) for r in rows]

    def _load_external_inputs(self) -> List[ExternalInputRow]:
        path = self._dir / self.EXTERNAL_INPUTS_FILE
        rows = self._read_csv(path)
        return [ExternalInputRow.from_dict(r) for r in rows]

    def _load_dcs_outputs(self) -> List[DCSOutputRow]:
        path = self._dir / self.DCS_OUTPUTS_FILE
        rows = self._read_csv(path)
        return [DCSOutputRow.from_dict(r) for r in rows]

    def _load_constraints(self) -> List[ConstraintRow]:
        path = self._dir / self.CONSTRAINTS_FILE
        rows = self._read_csv(path)
        return [ConstraintRow.from_dict(r) for r in rows]

    def _load_causal_edges(self) -> List[CausalEdgeRow]:
        path = self._dir / self.CAUSAL_EDGES_FILE
        rows = self._read_csv(path)
        return [CausalEdgeRow.from_dict(r) for r in rows]

    def _load_execution_steps(self) -> List[ExecutionStepRow]:
        path = self._dir / self.EXECUTION_STEPS_FILE
        rows = self._read_csv(path)
        return [ExecutionStepRow.from_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_statuses_and_roles(formulas: Sequence[FormulaRow]) -> None:
        """Executable CSV must only contain authoritative statuses and roles."""
        bad_statuses = []
        bad_roles = []
        for row in formulas:
            if row.status not in _ALLOWED_STATUSES:
                bad_statuses.append((row.formula_id, row.lhs, row.status))
            if row.formula_role not in _ALLOWED_ROLES:
                bad_roles.append((row.formula_id, row.lhs, row.formula_role))
        if bad_statuses:
            items = "; ".join(f"{fid}({lhs})={s}" for fid, lhs, s in bad_statuses[:5])
            raise SpecValidationError(
                f"Executable CSV contains non-authoritative status rows: {items}"
            )
        if bad_roles:
            items = "; ".join(f"{fid}({lhs})={r}" for fid, lhs, r in bad_roles[:5])
            raise SpecValidationError(
                f"Executable CSV contains non-executable/definition formula_roles: {items}"
            )

    @staticmethod
    def _validate_required_statuses_present(formulas: Sequence[FormulaRow]) -> None:
        """manual_override, manual_closure, and manual_promoted must not be lost."""
        present = {row.status for row in formulas}
        missing = _REQUIRED_STATUSES - present
        if missing:
            raise SpecValidationError(
                f"Required manual statuses are missing from the executable CSV: {missing}"
            )

    @staticmethod
    def _validate_parents(registry: FormulaRegistry) -> None:
        """Every formula parent must be a known LHS or a registered external input."""
        known_lhs = frozenset(registry.by_lhs)
        known_external = registry.registered_external_parents()
        valid_parents = known_lhs | known_external

        orphan_parents: List[tuple] = []
        for row in registry.formulas:
            for parent in row.parents:
                if parent not in valid_parents:
                    orphan_parents.append((row.formula_id, row.lhs, parent))

        if orphan_parents:
            items = "; ".join(
                f"{fid}({lhs})->{p}" for fid, lhs, p in orphan_parents[:10]
            )
            raise SpecValidationError(
                f"Formula parents not registered as LHS or external input: {items}"
            )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def load_spec(spec_dir: Optional[Path | str] = None) -> FormulaRegistry:
    """Load the V5 clean spec from *spec_dir* and return a :class:`FormulaRegistry`.

    This is the intended entry point for the simulation engine.  It will
    raise :class:`SpecValidationError` on any structural violation.

    Parameters
    ----------
    spec_dir :
        Directory containing the V5 CSV files.  Defaults to
        ``redesign_formula_docs/`` relative to the repository root.
    """
    return SpecLoader(spec_dir).load()


def _reject_v5_formulas_csv(path: Path | str) -> None:
    """Guard: raise if *path* refers to the forbidden v5_formulas.csv file."""
    p = Path(path)
    if p.name == _FORBIDDEN_FILENAME:
        raise SpecValidationError(
            f"The runtime formula engine must not read '{_FORBIDDEN_FILENAME}'. "
            "Use 'v5_executable_formulas.csv' instead (rule C004)."
        )
