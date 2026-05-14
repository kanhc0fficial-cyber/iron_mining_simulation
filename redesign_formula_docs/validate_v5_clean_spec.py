from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FORMULAS = ROOT / "v5_formulas.csv"
EXECUTABLE_FORMULAS = ROOT / "v5_executable_formulas.csv"
VARIABLES = ROOT / "v5_variables.csv"
DCS = ROOT / "v5_dcs_outputs.csv"
MIGRATION = ROOT / "v5_migration_from_v4.csv"
VALIDATION = ROOT / "V5_CLEAN_AUTOCHECK.md"
UNRESOLVED = ROOT / "v5_unresolved_parent_classification.csv"
EXTERNAL_INPUTS = ROOT / "v5_external_inputs.csv"
CONCEPT_COVERAGE = ROOT / "v5_concept_coverage.csv"

REQUIRED_EDGES = {
    ("Q_NT_under_s", "Q_feed_s"),
    ("M_NT_under_solid_s", "M_feed_solid_s"),
    ("M_NT_under_water_s", "M_feed_water_s"),
    ("Q_feed_s", "Q_in_cell_{s,cx1}"),
    ("Q_feed_s", "feed_j_rate_{s,c}"),
    ("Q_pump_pool_{s,1}", "feed_j_rate_{s,c}"),
    ("Q_pump_pool_{s,2}", "feed_j_rate_{s,c}"),
    ("Q_pump_pool_{s,3}", "feed_j_rate_{s,c}"),
    ("mean_froth_h_lag", "quality_proxy_s"),
    ("lab_tm_overflow_tfe", "quality_proxy_s"),
    ("lab_mag_mixed_conc_tfe", "quality_proxy_s"),
    ("event_froth_fault_{s,c}", "fx_s{s}_{c}_froth_h"),
    ("_x_tm_overflow_tfe", "lab_tm_overflow_tfe"),
    ("_x_mag_mixed_conc_tfe", "lab_mag_mixed_conc_tfe"),
}

CONCEPT_SEMANTIC_MAPPINGS = {
    "B_eff": "magnetic_core_missing",
    "capture_j": "magnetic_core_missing",
    "E_pulse": "magnetic_core_missing",
    "E_ring": "magnetic_core_missing",
    "E_level": "magnetic_core_missing",
    "R_hm_j": "magnetic_core_missing",
    "conc_j": "magnetic_core_missing",
    "tail_j": "magnetic_core_missing",
    "Entr": "magnetic_core_missing",
    "I_pump": "covered_by:I_pump_phys",
    "I_tm": "covered_by:I_tm_phys",
    "I_NT": "covered_by:I_NT_s",
    "Q_j_ml_s": "covered_by:Q_{s,j}_ml_s",
    "dose_j_kg_t": "covered_by:dose_TD_s;dose_DF_K6_s;dose_naoh_kg_t_s;dose_cao_kg_t_s",
    "M_overflow_solid": "covered_by:M_tm_overflow_solid",
    "M_overflow_water": "covered_by:M_tm_overflow_water",
    "M_sand_solid": "covered_by:M_tm_sand_solid",
    "M_sand_water": "covered_by:M_tm_sand_water",
    "f_j": "covered_by:f_{s,j}",
    "f_j_sp": "covered_by:f_{s,j}_sp",
    "froth_error": "covered_by:dose_need_TD_rough_s",
    "rougher_feed": "covered_by:feed_j_rate_{s,c}",
    "tail_or_conc_j": "covered_by:tail_j_{s,c};froth_j_{s,c}",
    "x_phys": "design_constraint",
    "y_fx_xin1": "reference_only",
}

ALLOWED_EXTERNAL_PREFIXES = (
    "k",
    "K",
    "a",
    "b",
    "c",
    "d",
    "e",
    "w",
    "rho",
    "tau",
    "sigma",
    "theta",
    "PRBS",
    "operator",
    "event",
    "health",
    "ref",
    "nom",
    "min",
    "max",
    "I0",
    "V",
    "A",
    "Cv",
    "pf",
    "eta",
    "N",
    "xi",
    "split",
    "active",
    "s",
    "Rmax",
    "G",
    "Cp",
    "speed",
    "h",
    "f0",
    "L0",
    "R0",
)

KNOWN_GLOBALS = {
    "dt",
    "eps",
    "T_amb",
    "T_ref",
    "WI_ref",
    "C_ref",
    "Q_ref",
    "P_ref",
    "rho_water",
    "rho_solid_mix",
    "mu_ref",
    "water_pressure",
    "grid_voltage",
    "cooling_water_pressure",
    "meas",
    "thermal_derate",
    "slurry_flow_from_mass",
    "logit",
    "weighted_mean_b",
    "mean_c",
    "sum_b",
    "sum_c",
    "sum_k",
    "sum_j",
    "sum_i",
    "noise",
    "n_rr",
    "liberation_potential",
    "feed_solid",
    "feed_water",
    "Gangue",
    "g",
    "partition_fine_j",
    "topology_feed_j_rate",
    "true_value_at_sample_point",
    "ffill_reported",
    "valve_from_air_sp",
    "process_noise",
    "fault_value",
    "report_delay",
    "final_conc_s",
    "flo_feed",
    "feed_j",
    "feed_j_rate",
    "TFe_1",
    "TFe_2",
    "TFe_3",
    "_x_eryi_line",
    "_tfe",
    "_f200",
    "_sp",
    "_ml_s",
}

EXPLICIT_EXTERNAL_CLASSIFICATION = {
    "Ca_carb0": "parameter",
    "Ca_sil0": "parameter",
    "feedforward_state": "controller_internal",
    "gas_holdup_max_c": "parameter",
    "H_lip_reference_c": "parameter",
    "H_pool_k": "parameter",
    "integral": "controller_internal",
    "intervention": "controller_internal",
    "lab_mag_mixed_conc_tfe": "lab_input",
    "lab_tm_overflow_tfe": "lab_input",
    "pipe_resistance_s1_1": "equipment_parameter",
    "pipe_resistance_s1_2": "equipment_parameter",
    "pipe_resistance_s2_1": "equipment_parameter",
    "pipe_resistance_s2_2": "equipment_parameter",
    "R_header0": "parameter",
    "reagent_supply_pressure_j": "utility_state_input",
    "u0_c": "parameter",
    "grade_NT_under_j_s": "stream_or_state_input",
    "_x_tm_overflow_tfe": "stream_or_state_input",
    "_x_mag_mixed_conc_tfe": "stream_or_state_input",
    "lab_sample_template": "known_global",
    "report_time_tm_overflow_tfe": "lab_schedule",
    "report_time_mag_mixed_conc_tfe": "lab_schedule",
}

CLASSIFICATION_NOTES = {
    "known_global": "Shared simulation constant or helper function.",
    "previous_state_reference": "Lagged state supplied by the simulator state store.",
    "parameter": "Calibration, geometry, or tuning parameter; not generated by process equations.",
    "equipment_parameter": "Fixed equipment geometry or resistance parameter.",
    "controller_internal": "Controller memory, feedforward flag, or intervention input.",
    "utility_state_input": "Plant utility condition supplied by the environment model.",
    "lab_input": "Delayed laboratory or analyzer input; available only through the sampling model.",
    "lab_schedule": "Laboratory sample/report timing supplied by the lab scheduler.",
    "stream_or_state_input": "Upstream stream or dynamic state entering this formula from process topology.",
    "ore_or_process_state": "Ore property or process state carried by streams or generated at boundary.",
    "equipment_or_control_state": "Equipment state or actuator signal generated by another execution block.",
    "template_variable": "Template index or symbolic family member resolved during code generation.",
    "template_index": "Short template index resolved during code generation.",
    "needs_review": "Unclassified parent; treat as possible missing formula or naming conflict.",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_external_parameter(token: str) -> bool:
    if token in EXPLICIT_EXTERNAL_CLASSIFICATION:
        return True
    if token in KNOWN_GLOBALS:
        return True
    if re.fullmatch(r"[A-Za-z]+", token) and len(token) <= 2:
        return True
    if token.endswith(("_prev", "_lag", "_delayed")):
        return True
    if token.endswith(("_ref", "_nom", "_min", "_max", "_low", "_high", "_opt")):
        return True
    return token.startswith(ALLOWED_EXTERNAL_PREFIXES)


def classify_unresolved(token: str) -> str:
    if token in EXPLICIT_EXTERNAL_CLASSIFICATION:
        return EXPLICIT_EXTERNAL_CLASSIFICATION[token]
    if token in KNOWN_GLOBALS:
        return "known_global"
    if re.fullmatch(r"[A-Za-z]+", token) and len(token) <= 2:
        return "template_index"
    if token.endswith(("_prev", "_lag", "_delayed")):
        return "previous_state_reference"
    if token.startswith(ALLOWED_EXTERNAL_PREFIXES) or token.endswith(
        ("_ref", "_nom", "_min", "_max", "_low", "_high", "_opt")
    ):
        return "parameter"
    if token.startswith(("I0", "V_", "A_", "Cv", "pf_", "eta_", "N_", "xi_", "split_", "active_")):
        return "parameter"
    if token.startswith(("s_", "s0", "Rmax", "G_base", "Cp_", "speed_", "h_ref", "h_froth_target", "f0", "L0_", "R0_")):
        return "parameter"
    if token.startswith(("M_", "Q_", "C_", "F", "Liberation_", "WI_", "T_", "rho_", "mu_")):
        return "stream_or_state_input"
    if token.startswith(("r_", "clay", "f25", "pH", "Ca2", "dose_")):
        return "ore_or_process_state"
    if token.startswith(("I_", "P_", "L_", "u_", "f_")):
        return "equipment_or_control_state"
    if "{" in token and "}" in token:
        return "template_variable"
    return "needs_review"


def concept_coverage_status(row: dict[str, str], executable_lhs: set[str]) -> tuple[str, str]:
    lhs = row["lhs"]
    if lhs in CONCEPT_SEMANTIC_MAPPINGS:
        mapping = CONCEPT_SEMANTIC_MAPPINGS[lhs]
        if mapping == "magnetic_core_missing":
            return "needs_promotion", "Magnetic separation concept formula has no concrete executable counterpart yet."
        if mapping == "design_constraint":
            return "design_constraint", "Reference rule for implementation/validation, not a timestep equation."
        if mapping == "reference_only":
            return "reference_only", "Documentation-only reference, not a timestep equation."
        return "semantic_covered", mapping
    if lhs in executable_lhs:
        return "exact_covered", lhs
    candidates = sorted(
        x
        for x in executable_lhs
        if x.startswith(lhs + "_") or x.startswith(lhs + "{") or x.startswith(lhs + "[") or lhs + "_{" in x
    )
    if candidates:
        return "templated_covered", ";".join(candidates[:12])
    if lhs.startswith("d") and "/dt" in lhs:
        suffix = lhs.replace("/dt", "")
        candidates = sorted(x for x in executable_lhs if suffix in x)
        if candidates:
            return "templated_covered", ";".join(candidates[:12])
    return "needs_review", "No executable counterpart found by heuristic."


def main() -> None:
    formulas_all = read_csv(FORMULAS)
    formulas = read_csv(EXECUTABLE_FORMULAS) if EXECUTABLE_FORMULAS.exists() else formulas_all
    variables = read_csv(VARIABLES)
    dcs = read_csv(DCS)
    migration = read_csv(MIGRATION)

    lhs_counts = Counter(row["lhs"] for row in formulas)
    duplicate_lhs = sorted(lhs for lhs, count in lhs_counts.items() if count > 1)

    formula_ids = Counter(row["formula_id"] for row in formulas)
    duplicate_formula_ids = sorted(fid for fid, count in formula_ids.items() if count > 1)

    var_names = {row["variable"] for row in variables if row["defined_by_formula_id"] in {f["formula_id"] for f in formulas}}
    formula_lhs = {row["lhs"] for row in formulas}
    variables_without_formula = sorted(var_names - formula_lhs)
    formulas_without_variable = sorted(formula_lhs - var_names)

    migration_without_status = [row for row in migration if not row["migration_status"]]
    migration_status_counts = Counter(row["migration_status"] for row in migration)

    dcs_needs_review = [row for row in dcs if row["migration_status"] != "migrated"]
    dcs_without_parent = [row for row in dcs if not row["physical_parent"]]
    executable_expected_ids = {
        row["formula_id"]
        for row in formulas_all
        if row["formula_role"] in {"executable", "definition"} or row["status"] == "manual_closure"
    }
    executable_actual_ids = {row["formula_id"] for row in formulas}
    executable_lhs = {row["lhs"] for row in formulas}
    executable_missing_ids = sorted(executable_expected_ids - executable_actual_ids)
    executable_extra_ids = sorted(executable_actual_ids - executable_expected_ids)
    concept_rows = [row for row in formulas_all if row["formula_role"] in {"concept_template", "reference"}]
    concept_coverage_rows = []
    for row in concept_rows:
        coverage_status, mapped_to = concept_coverage_status(row, executable_lhs)
        concept_coverage_rows.append(
            {
                "formula_id": row["formula_id"],
                "lhs": row["lhs"],
                "formula_role": row["formula_role"],
                "coverage_status": coverage_status,
                "mapped_to": mapped_to,
                "source_v4_line": row["source_v4_line"],
                "source_v4_section": row["source_v4_section"],
                "notes": row["notes"],
            }
        )
    concept_needs_review = [
        row for row in concept_coverage_rows if row["coverage_status"] in {"needs_review", "needs_promotion"}
    ]
    parent_edges = {
        (parent, row["lhs"])
        for row in formulas
        for parent in row["parents"].split(";")
        if parent
    }
    missing_required_edges = sorted(REQUIRED_EDGES - parent_edges)

    undefined_parents: dict[str, set[str]] = {}
    unresolved_rows: list[dict[str, str]] = []
    external_parent_rows: list[dict[str, str]] = []
    for row in formulas:
        parents = [p for p in row["parents"].split(";") if p]
        all_missing = {p for p in parents if p not in formula_lhs}
        missing = {p for p in all_missing if classify_unresolved(p) == "needs_review"}
        for parent in sorted(all_missing):
            classification = classify_unresolved(parent)
            external_parent_rows.append(
                {
                    "formula_id": row["formula_id"],
                    "lhs": row["lhs"],
                    "parent": parent,
                    "classification": classification,
                    "stage": row["stage"],
                    "source_v4_line": row["source_v4_line"],
                    "notes": CLASSIFICATION_NOTES[classification],
                }
            )
        if missing:
            undefined_parents[row["lhs"]] = missing
            for parent in sorted(missing):
                unresolved_rows.append(
                    {
                        "formula_id": row["formula_id"],
                        "lhs": row["lhs"],
                        "parent": parent,
                        "classification": classify_unresolved(parent),
                        "stage": row["stage"],
                        "source_v4_line": row["source_v4_line"],
                    }
                )

    needs_review_rows = [row for row in external_parent_rows if row["classification"] == "needs_review"]

    external_registry: dict[str, dict[str, str]] = {}
    for row in external_parent_rows:
        parent = row["parent"]
        current = external_registry.setdefault(
            parent,
            {
                "parent": parent,
                "classification": row["classification"],
                "used_by_lhs": "",
                "stages": "",
                "source_v4_lines": "",
                "notes": row["notes"],
            },
        )
        current["used_by_lhs"] = ";".join(sorted(set(filter(None, current["used_by_lhs"].split(";"))) | {row["lhs"]}))
        current["stages"] = ";".join(sorted(set(filter(None, current["stages"].split(";"))) | {row["stage"]}))
        current["source_v4_lines"] = ";".join(
            sorted(set(filter(None, current["source_v4_lines"].split(";"))) | {row["source_v4_line"]})
        )

    lines: list[str] = []
    lines.append("# V5 Clean Autocheck")
    lines.append("")
    lines.append(f"Canonical formulas: **{len(formulas_all)}**")
    lines.append(f"Executable formulas checked: **{len(formulas)}**")
    lines.append(f"Variables: **{len(variables)}**")
    lines.append(f"DCS rows: **{len(dcs)}**")
    lines.append(f"Migration rows: **{len(migration)}**")
    lines.append(f"Registered external/input parents: **{len(external_registry)}**")
    lines.append("")
    lines.append("## Hard Checks")
    lines.append("")
    lines.append(f"- Duplicate formula IDs: **{len(duplicate_formula_ids)}**")
    lines.append(f"- Duplicate LHS formulas: **{len(duplicate_lhs)}**")
    lines.append(f"- Variables without formula: **{len(variables_without_formula)}**")
    lines.append(f"- Formulas without variable row: **{len(formulas_without_variable)}**")
    lines.append(f"- Migration rows without status: **{len(migration_without_status)}**")
    lines.append(f"- DCS rows needing review: **{len(dcs_needs_review)}**")
    lines.append(f"- DCS rows without physical parent: **{len(dcs_without_parent)}**")
    lines.append(f"- Executable CSV missing required rows: **{len(executable_missing_ids)}**")
    lines.append(f"- Executable CSV has non-executable rows: **{len(executable_extra_ids)}**")
    lines.append(f"- Concept/reference rows needing coverage decision: **{len(concept_needs_review)}**")
    lines.append(f"- Formula rows with non-registered parents: **{len(undefined_parents)}**")
    lines.append(f"- External/input parents needing review: **{len(needs_review_rows)}**")
    lines.append(f"- Required causal edges missing: **{len(missing_required_edges)}**")
    lines.append("")
    lines.append("## Migration Status Counts")
    lines.append("")
    for status, count in sorted(migration_status_counts.items()):
        lines.append(f"- `{status}`: {count}")
    lines.append("")

    external_counts = Counter(row["classification"] for row in external_registry.values())
    lines.append("## External/Input Parent Classifications")
    lines.append("")
    for classification, count in sorted(external_counts.items()):
        lines.append(f"- `{classification}`: {count}")
    lines.append("")

    concept_counts = Counter(row["coverage_status"] for row in concept_coverage_rows)
    lines.append("## Concept/Reference Coverage")
    lines.append("")
    for coverage_status, count in sorted(concept_counts.items()):
        lines.append(f"- `{coverage_status}`: {count}")
    lines.append("")

    if duplicate_lhs:
        lines.append("## Duplicate LHS")
        for lhs in duplicate_lhs:
            lines.append(f"- `{lhs}`")
        lines.append("")

    if dcs_needs_review:
        lines.append("## DCS Needs Review")
        for row in dcs_needs_review:
            lines.append(f"- `{row['dcs_name']}`: {row['notes']}")
        lines.append("")

    if executable_missing_ids or executable_extra_ids:
        lines.append("## Executable CSV Coverage")
        for fid in executable_missing_ids:
            lines.append(f"- missing required executable row `{fid}`")
        for fid in executable_extra_ids:
            lines.append(f"- unexpected non-executable row `{fid}`")
        lines.append("")

    if concept_needs_review:
        lines.append("## Concept/Reference Rows Needing Decision")
        for row in concept_needs_review[:80]:
            lines.append(
                f"- `{row['lhs']}` ({row['formula_id']}, line {row['source_v4_line']}): {row['mapped_to']}"
            )
        if len(concept_needs_review) > 80:
            lines.append(f"- ... truncated {len(concept_needs_review)-80} additional rows")
        lines.append("")

    if missing_required_edges:
        lines.append("## Missing Required Causal Edges")
        for parent, child in missing_required_edges:
            lines.append(f"- `{parent}` -> `{child}`")
        lines.append("")

    if undefined_parents:
        lines.append("## Unresolved Parent Variables")
        lines.append("")
        lines.append("These are parents not defined by formulas and not yet accepted as registered inputs.")
        for lhs, parents in sorted(undefined_parents.items())[:120]:
            lines.append(f"- `{lhs}` <- {', '.join(sorted(parents))}")
        if len(undefined_parents) > 120:
            lines.append(f"- ... truncated {len(undefined_parents)-120} additional rows")
        lines.append("")

    VALIDATION.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with UNRESOLVED.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "formula_id",
                "lhs",
                "parent",
                "classification",
                "stage",
                "source_v4_line",
            ],
        )
        writer.writeheader()
        writer.writerows(unresolved_rows)
    with EXTERNAL_INPUTS.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "parent",
                "classification",
                "used_by_lhs",
                "stages",
                "source_v4_lines",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(sorted(external_registry.values(), key=lambda row: row["parent"]))
    with CONCEPT_COVERAGE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "formula_id",
                "lhs",
                "formula_role",
                "coverage_status",
                "mapped_to",
                "source_v4_line",
                "source_v4_section",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(concept_coverage_rows)
    print(f"Wrote {VALIDATION}")
    print(f"Wrote {UNRESOLVED}")
    print(f"Wrote {EXTERNAL_INPUTS}")
    print(f"Wrote {CONCEPT_COVERAGE}")
    print(f"duplicate_lhs={len(duplicate_lhs)}")
    print(f"dcs_needs_review={len(dcs_needs_review)}")
    print(f"unresolved_parent_rows={len(undefined_parents)}")
    print(f"external_inputs_needing_review={len(needs_review_rows)}")
    print(f"concept_rows_needing_decision={len(concept_needs_review)}")

    # Exit nonzero only for structural breakages that should never happen.
    if (
        duplicate_formula_ids
        or duplicate_lhs
        or migration_without_status
        or needs_review_rows
        or missing_required_edges
        or executable_missing_ids
        or executable_extra_ids
        or concept_needs_review
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
