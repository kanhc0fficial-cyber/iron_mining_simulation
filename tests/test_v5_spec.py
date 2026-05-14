from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.v5_spec import load_v5_clean_spec


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_minimal_v5_files(base_dir: Path, formulas: list[dict[str, str]]) -> None:
    spec_dir = base_dir / "redesign_formula_docs"
    spec_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        spec_dir / "v5_executable_formulas.csv",
        ["formula_id", "stage", "lhs", "rhs", "parents"],
        formulas,
    )
    _write_csv(
        spec_dir / "v5_dcs_outputs.csv",
        ["dcs_name", "physical_parent", "migration_status", "notes"],
        [
            {
                "dcs_name": "dcs_1",
                "physical_parent": "x_1",
                "migration_status": "migrated",
                "notes": "",
            }
        ],
    )
    _write_csv(
        spec_dir / "v5_execution_steps.csv",
        ["step_order", "stage", "description"],
        [{"step_order": "010", "stage": "boundary", "description": "desc"}],
    )
    _write_csv(
        spec_dir / "v5_external_inputs.csv",
        ["parent", "classification", "used_by_lhs", "stages", "source_v4_lines", "notes"],
        [
            {
                "parent": "k1",
                "classification": "parameter",
                "used_by_lhs": "x_1",
                "stages": "boundary",
                "source_v4_lines": "1",
                "notes": "",
            }
        ],
    )


def test_load_v5_clean_spec_from_repository_root() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    spec = load_v5_clean_spec(repo_root)

    assert len(spec.formulas) > 0
    assert len(spec.dcs_outputs) > 0
    assert len(spec.execution_steps) > 0
    assert len(spec.external_inputs) > 0


def test_v5_loader_duplicate_formula_id_fails(tmp_path: Path) -> None:
    _write_minimal_v5_files(
        tmp_path,
        formulas=[
            {"formula_id": "V5_0001", "stage": "boundary", "lhs": "x_1", "rhs": "1", "parents": ""},
            {"formula_id": "V5_0001", "stage": "boundary", "lhs": "x_2", "rhs": "2", "parents": ""},
        ],
    )

    with pytest.raises(ValueError, match="duplicate formula_id"):
        load_v5_clean_spec(tmp_path)


def test_v5_loader_duplicate_lhs_fails(tmp_path: Path) -> None:
    _write_minimal_v5_files(
        tmp_path,
        formulas=[
            {"formula_id": "V5_0001", "stage": "boundary", "lhs": "x_1", "rhs": "1", "parents": ""},
            {"formula_id": "V5_0002", "stage": "boundary", "lhs": "x_1", "rhs": "2", "parents": ""},
        ],
    )

    with pytest.raises(ValueError, match="duplicate lhs"):
        load_v5_clean_spec(tmp_path)


def test_v5_loader_missing_required_column_fails(tmp_path: Path) -> None:
    spec_dir = tmp_path / "redesign_formula_docs"
    spec_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        spec_dir / "v5_executable_formulas.csv",
        ["formula_id", "stage", "lhs", "parents"],
        [{"formula_id": "V5_0001", "stage": "boundary", "lhs": "x_1", "parents": ""}],
    )
    _write_csv(
        spec_dir / "v5_dcs_outputs.csv",
        ["dcs_name", "physical_parent", "migration_status", "notes"],
        [{"dcs_name": "dcs_1", "physical_parent": "x_1", "migration_status": "migrated", "notes": ""}],
    )
    _write_csv(
        spec_dir / "v5_execution_steps.csv",
        ["step_order", "stage", "description"],
        [{"step_order": "010", "stage": "boundary", "description": "desc"}],
    )
    _write_csv(
        spec_dir / "v5_external_inputs.csv",
        ["parent", "classification", "used_by_lhs", "stages", "source_v4_lines", "notes"],
        [{"parent": "k1", "classification": "parameter", "used_by_lhs": "x_1", "stages": "boundary", "source_v4_lines": "1", "notes": ""}],
    )

    with pytest.raises(ValueError, match="missing required columns: rhs"):
        load_v5_clean_spec(tmp_path)


def test_v5_loader_empty_required_identifier_fails(tmp_path: Path) -> None:
    _write_minimal_v5_files(
        tmp_path,
        formulas=[
            {"formula_id": "", "stage": "boundary", "lhs": "x_1", "rhs": "1", "parents": ""},
        ],
    )

    with pytest.raises(ValueError, match="empty required field 'formula_id'"):
        load_v5_clean_spec(tmp_path)
