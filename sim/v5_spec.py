from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


V5_SPEC_DIR = "redesign_formula_docs"
CSV_FIRST_DATA_ROW_NUMBER = 2


@dataclass(frozen=True)
class V5ExecutableFormula:
    formula_id: str
    stage: str
    lhs: str
    rhs: str
    parents: str


@dataclass(frozen=True)
class V5DcsOutput:
    dcs_name: str
    physical_parent: str
    migration_status: str
    notes: str


@dataclass(frozen=True)
class V5ExecutionStep:
    step_order: str
    stage: str
    description: str


@dataclass(frozen=True)
class V5ExternalInput:
    parent: str
    classification: str
    used_by_lhs: str
    stages: str
    source_v4_lines: str
    notes: str


@dataclass(frozen=True)
class V5CleanSpec:
    formulas: list[V5ExecutableFormula]
    dcs_outputs: list[V5DcsOutput]
    execution_steps: list[V5ExecutionStep]
    external_inputs: list[V5ExternalInput]


REQUIRED_COLUMNS = {
    "v5_executable_formulas.csv": {"formula_id", "stage", "lhs", "rhs", "parents"},
    "v5_dcs_outputs.csv": {"dcs_name", "physical_parent", "migration_status", "notes"},
    "v5_execution_steps.csv": {"step_order", "stage", "description"},
    "v5_external_inputs.csv": {
        "parent",
        "classification",
        "used_by_lhs",
        "stages",
        "source_v4_lines",
        "notes",
    },
}


def _resolve_spec_dir(repo_root: Path | str | None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return root / V5_SPEC_DIR


def _read_and_validate_columns(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(required_columns - fieldnames)
        if missing:
            raise ValueError(f"{path.name}: missing required columns: {', '.join(missing)}")
        return list(reader)


def _require_non_empty(value: str, field_name: str, file_name: str, row_index: int) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(
            f"{file_name}: row {row_index} (including header) has empty required field '{field_name}'"
        )
    return stripped


def _validate_unique_formulas(formulas: list[V5ExecutableFormula]) -> None:
    formula_id_counts = Counter(row.formula_id for row in formulas)
    duplicate_formula_ids = sorted(formula_id for formula_id, count in formula_id_counts.items() if count > 1)
    if duplicate_formula_ids:
        raise ValueError(f"duplicate formula_id values: {', '.join(duplicate_formula_ids)}")

    lhs_counts = Counter(row.lhs for row in formulas)
    duplicate_lhs = sorted(lhs for lhs, count in lhs_counts.items() if count > 1)
    if duplicate_lhs:
        raise ValueError(f"duplicate lhs values: {', '.join(duplicate_lhs)}")


def load_v5_clean_spec(repo_root: Path | str | None = None) -> V5CleanSpec:
    spec_dir = _resolve_spec_dir(repo_root)
    formulas_file = "v5_executable_formulas.csv"
    dcs_file = "v5_dcs_outputs.csv"
    steps_file = "v5_execution_steps.csv"
    external_file = "v5_external_inputs.csv"

    formulas_rows = _read_and_validate_columns(
        spec_dir / formulas_file,
        REQUIRED_COLUMNS[formulas_file],
    )
    formulas = [
        V5ExecutableFormula(
            formula_id=_require_non_empty(row["formula_id"], "formula_id", formulas_file, i),
            stage=_require_non_empty(row["stage"], "stage", formulas_file, i),
            lhs=_require_non_empty(row["lhs"], "lhs", formulas_file, i),
            rhs=_require_non_empty(row["rhs"], "rhs", formulas_file, i),
            parents=row["parents"].strip(),
        )
        for i, row in enumerate(formulas_rows, start=CSV_FIRST_DATA_ROW_NUMBER)
    ]
    _validate_unique_formulas(formulas)

    dcs_rows = _read_and_validate_columns(spec_dir / dcs_file, REQUIRED_COLUMNS[dcs_file])
    dcs_outputs = [
        V5DcsOutput(
            dcs_name=_require_non_empty(row["dcs_name"], "dcs_name", dcs_file, i),
            physical_parent=_require_non_empty(row["physical_parent"], "physical_parent", dcs_file, i),
            migration_status=row["migration_status"].strip(),
            notes=row["notes"].strip(),
        )
        for i, row in enumerate(dcs_rows, start=CSV_FIRST_DATA_ROW_NUMBER)
    ]

    steps_rows = _read_and_validate_columns(spec_dir / steps_file, REQUIRED_COLUMNS[steps_file])
    execution_steps = [
        V5ExecutionStep(
            step_order=_require_non_empty(row["step_order"], "step_order", steps_file, i),
            stage=_require_non_empty(row["stage"], "stage", steps_file, i),
            description=_require_non_empty(row["description"], "description", steps_file, i),
        )
        for i, row in enumerate(steps_rows, start=CSV_FIRST_DATA_ROW_NUMBER)
    ]

    external_rows = _read_and_validate_columns(spec_dir / external_file, REQUIRED_COLUMNS[external_file])
    external_inputs = [
        V5ExternalInput(
            parent=_require_non_empty(row["parent"], "parent", external_file, i),
            classification=_require_non_empty(row["classification"], "classification", external_file, i),
            used_by_lhs=row["used_by_lhs"].strip(),
            stages=row["stages"].strip(),
            source_v4_lines=row["source_v4_lines"].strip(),
            notes=row["notes"].strip(),
        )
        for i, row in enumerate(external_rows, start=CSV_FIRST_DATA_ROW_NUMBER)
    ]

    return V5CleanSpec(
        formulas=formulas,
        dcs_outputs=dcs_outputs,
        execution_steps=execution_steps,
        external_inputs=external_inputs,
    )
