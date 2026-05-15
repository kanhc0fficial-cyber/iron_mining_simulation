#!/usr/bin/env python3
"""
从“对抗式/变异式审查”角度检查当前 PR 的 V5 spec loader。

这个脚本不修改仓库代码；它通过：
1. 加载真实 V5 CSV；
2. 对临时副本做定向篡改；
3. 观察 loader 是否拒绝坏规格；
4. 补充少量 API 合约检查；

来帮助人工发现“现有测试没覆盖到”的 Bug / 遗漏。
"""

from __future__ import annotations

import csv
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = REPO_ROOT / "redesign_formula_docs"
sys.path.insert(0, str(REPO_ROOT))

from sim.v5.spec_loader import SpecValidationError, load_spec  # noqa: E402


CSV_FILES = (
    "v5_executable_formulas.csv",
    "v5_execution_steps.csv",
    "v5_variables.csv",
    "v5_external_inputs.csv",
    "v5_dcs_outputs.csv",
    "v5_implementation_constraints.csv",
    "v5_causal_edges.csv",
)


@dataclass
class AuditResult:
    name: str
    passed: bool
    summary: str
    severity: str = "info"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _copy_spec_tree(dst: Path) -> None:
    for name in CSV_FILES:
        shutil.copy2(SPEC_DIR / name, dst / name)


def _run_with_mutation(
    name: str,
    mutate: Callable[[Path], None],
    expected_exception: type[BaseException] | None,
    issue_summary: str,
) -> AuditResult:
    with tempfile.TemporaryDirectory(prefix="v5-spec-audit-") as tmp:
        tmpdir = Path(tmp)
        _copy_spec_tree(tmpdir)
        mutate(tmpdir)
        try:
            load_spec(tmpdir)
        except BaseException as exc:  # noqa: BLE001
            if expected_exception is not None and isinstance(exc, expected_exception):
                return AuditResult(name, True, f"正确拒绝坏规格：{type(exc).__name__}")
            return AuditResult(
                name,
                False,
                f"抛出非预期异常：{type(exc).__name__}: {exc}",
                severity="warning",
            )
        if expected_exception is None:
            return AuditResult(name, True, "按预期成功加载")
        return AuditResult(name, False, issue_summary, severity="warning")


def _baseline_load() -> AuditResult:
    registry = load_spec()
    return AuditResult(
        "baseline_load",
        True,
        f"真实规格加载成功：formulas={len(registry.formulas)}, "
        f"variables={len(registry.variables)}, external_inputs={len(registry.external_inputs)}",
    )


def _duplicate_lhs_mutation(tmpdir: Path) -> None:
    path = tmpdir / "v5_executable_formulas.csv"
    rows = _read_csv(path)
    dup = dict(rows[0])
    dup["formula_id"] = "AUDIT_DUP_LHS"
    rows.append(dup)
    _write_csv(path, rows)


def _invalid_status_mutation(tmpdir: Path) -> None:
    path = tmpdir / "v5_executable_formulas.csv"
    rows = _read_csv(path)
    rows[0]["status"] = "reference"
    _write_csv(path, rows)


def _missing_manual_override_mutation(tmpdir: Path) -> None:
    path = tmpdir / "v5_executable_formulas.csv"
    rows = _read_csv(path)
    rows = [row for row in rows if row["status"] != "manual_override"]
    _write_csv(path, rows)


def _unknown_parent_mutation(tmpdir: Path) -> None:
    path = tmpdir / "v5_executable_formulas.csv"
    rows = _read_csv(path)
    rows[0]["parents"] = f'{rows[0]["parents"]};AUDIT_UNKNOWN_PARENT'
    _write_csv(path, rows)


def _duplicate_formula_id_mutation(tmpdir: Path) -> None:
    path = tmpdir / "v5_executable_formulas.csv"
    rows = _read_csv(path)
    dup = dict(rows[0])
    dup["lhs"] = "AUDIT_DUPLICATE_FORMULA_ID_LHS"
    rows.append(dup)
    _write_csv(path, rows)


def _missing_variable_row_mutation(tmpdir: Path) -> None:
    variables_path = tmpdir / "v5_variables.csv"
    rows = _read_csv(variables_path)
    rows = [row for row in rows if row["variable"] != "B_eff"]
    _write_csv(variables_path, rows)


def _dependency_api_contract() -> AuditResult:
    registry = load_spec()
    deps = registry.dependency_list("quality_proxy_s")
    if isinstance(deps, (list, tuple)):
        return AuditResult("dependency_api_contract", True, "dependency_list 返回有序序列")
    return AuditResult(
        "dependency_api_contract",
        False,
        "dependency_list 返回 frozenset，丢失 CSV 中父节点顺序；更像集合而不是“dependency list”。",
        severity="warning",
    )


def run_audit() -> list[AuditResult]:
    results = [_baseline_load()]
    results.append(
        _run_with_mutation(
            "duplicate_lhs_rejected",
            _duplicate_lhs_mutation,
            SpecValidationError,
            "duplicate lhs 未被拒绝。",
        )
    )
    results.append(
        _run_with_mutation(
            "invalid_status_rejected",
            _invalid_status_mutation,
            SpecValidationError,
            "非权威 status 未被拒绝。",
        )
    )
    results.append(
        _run_with_mutation(
            "missing_manual_override_rejected",
            _missing_manual_override_mutation,
            SpecValidationError,
            "移除 manual_override 后仍然能加载，说明权威手工公式缺失未被检测。",
        )
    )
    results.append(
        _run_with_mutation(
            "unknown_parent_rejected",
            _unknown_parent_mutation,
            SpecValidationError,
            "未注册 parent 未被拒绝。",
        )
    )
    results.append(
        _run_with_mutation(
            "duplicate_formula_id_rejected",
            _duplicate_formula_id_mutation,
            SpecValidationError,
            "duplicate formula_id 未被拒绝；by_id 会静默覆盖，可能隐藏坏规格。",
        )
    )
    results.append(
        _run_with_mutation(
            "missing_variable_row_rejected",
            _missing_variable_row_mutation,
            SpecValidationError,
            "缺少变量行时仍然能加载；当前 loader 未校验 formulas/variables 跨表一致性。",
        )
    )
    results.append(_dependency_api_contract())
    return results


def main() -> int:
    results = run_audit()
    print("# V5 spec loader PR 审查脚本")
    print()
    warning_count = 0
    for result in results:
        status = "PASS" if result.passed else "WARN"
        print(f"- [{status}] {result.name}: {result.summary}")
        if not result.passed:
            warning_count += 1
    print()
    print(f"summary: warnings={warning_count}, total_checks={len(results)}")
    return 1 if warning_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
