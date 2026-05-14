from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
V4 = ROOT / "DESIGN_V4_FACTORY_CAUSAL_SIMULATION.md"
V4_REGISTRY = ROOT / "V4_FORMULA_REGISTRY.csv"

V5_MD = ROOT / "DESIGN_V5_CLEAN.md"
V5_FORMULAS = ROOT / "v5_formulas.csv"
V5_EXECUTABLE_FORMULAS = ROOT / "v5_executable_formulas.csv"
V5_VARIABLES = ROOT / "v5_variables.csv"
V5_DCS = ROOT / "v5_dcs_outputs.csv"
V5_EDGES = ROOT / "v5_causal_edges.csv"
V5_STEPS = ROOT / "v5_execution_steps.csv"
V5_MIGRATION = ROOT / "v5_migration_from_v4.csv"
V5_CONFLICTS = ROOT / "v5_conflicts_to_review.csv"
V5_MANUAL = ROOT / "v5_manual_formulas.csv"
V5_VALIDATION = ROOT / "V5_MIGRATION_VALIDATION.md"
V5_CONSTRAINTS = ROOT / "v5_implementation_constraints.csv"


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*(?:_\{[^}]+\})?")
MEAS_RE = re.compile(r"^\s*(?P<lhs>[A-Za-z0-9_{}]+)\s*=\s*meas\((?P<phys>[^)]+)\)")
TABLE_DCS_RE = re.compile(r"\|\s*`(?P<dcs>[^`]+)`\s*\|")
GROUPED_DCS_RE = re.compile(r"(?P<prefix>[A-Za-z0-9_{}]+)_\{(?P<items>[^}]+)\}_(?P<suffix>[A-Za-z0-9_{}]+)")

DRUGS = ["td_rough", "td_clean", "k6_rough", "naoh", "cao"]

RESERVED = {
    "clip",
    "max",
    "min",
    "exp",
    "log",
    "log1p",
    "sqrt",
    "sigmoid",
    "sum",
    "sum_i",
    "sum_j",
    "mean",
    "delay",
    "ZOH",
    "sat_act",
    "round",
    "if",
    "else",
    "for",
    "in",
    "dt",
    "eps",
    "N",
    "text",
    "true",
    "false",
}

DROP_LHS = {"DCS", "forbidden", "allowed_upstream_lab"}
DROP_LHS_PREFIXES = ("ifevent_", "ifevent")
NON_EXECUTABLE_WORDS = {
    " or ",
    " must ",
    " meaning",
    " state ",
    " load,",
    " unless ",
}

CANONICAL_OVERRIDES = {
    "quality_proxy_s": {
        "rhs": "w_tm_lab*ffill_reported(lab_tm_overflow_tfe)+w_mag_lab*ffill_reported(lab_mag_mixed_conc_tfe)+w_load*standardize(agg_tm_motor_current_lag)+w_pressure*standardize(agg_tm_cyclone_feed_pressure_lag)+w_froth*standardize(mean_froth_h_lag)",
        "notes": "Manual override: V4 rhs_excerpt was truncated at standardize(mean_froth_h_lag).",
    },
    "Q_feed_meter_phys": {
        "rhs": "Q_feed_s1_total+Q_feed_s2_total",
        "notes": "Manual override: feed meter follows actual thickener underflow to flotation, not a setpoint-only proxy.",
    },
    "Q_feed_s1_total": {
        "rhs": "Q_NT_under_s1",
        "notes": "Manual override: series 1 flotation feed is thickener underflow.",
    },
    "Q_feed_s2_total": {
        "rhs": "Q_NT_under_s2",
        "notes": "Manual override: series 2 flotation feed is thickener underflow.",
    },
}

PROMOTED_CONCEPT_LHS = {
    "B_eff",
    "capture_j",
    "E_pulse",
    "E_ring",
    "E_level",
    "Entr",
    "R_hm_j",
    "conc_j",
    "tail_j",
    "overflow_j",
    "sand_j",
    "y_fx_xin_s_true",
    "y_fx_xin_s",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def stage_from_section(h2: str, h3: str) -> str:
    text = f"{h2} {h3}"
    if "入口" in text or "边界" in text:
        return "boundary"
    if "磁选" in text:
        return "magnetic"
    if "塔磨" in text or "旋流器" in text:
        return "tower_mill"
    if "浮选" in text:
        return "flotation"
    if "化验" in text:
        return "lab"
    if "DCS" in text:
        return "dcs"
    if "全局" in text or "基础" in text:
        return "global"
    return "system"


def formula_priority(row: dict[str, str]) -> tuple[int, int]:
    h2 = row["h2"]
    h3 = row["h3"]
    line = int(row["line"])
    # Executable DCS sections are canonical when duplicated.
    if h3.startswith("10."):
        return (0, line)
    # Boundary formulas are generally executable and not duplicated in 10.x.
    if h2.startswith("4."):
        return (1, line)
    # Global definitions are allowed as canonical if no executable formula exists.
    if h2.startswith("2.") or h2.startswith("3."):
        return (2, line)
    # Lab and validation formulas are retained only if unique.
    if h2.startswith("8.") or h2.startswith("9.") or h2.startswith("12."):
        return (3, line)
    # Concept sections are lower priority because V5 keeps them as prose only.
    return (4, line)


def is_formula_candidate(row: dict[str, str]) -> bool:
    lhs = row["lhs"].strip()
    if not lhs or lhs in DROP_LHS:
        return False
    if lhs.startswith(DROP_LHS_PREFIXES):
        return False
    if lhs.startswith("z_"):
        return False
    # Lines such as "F325_mixed =" are block-continuation headers, not complete formulas.
    if row["formula_line"].rstrip().endswith("="):
        return False
    low = f" {row['rhs_excerpt'].lower()} "
    if any(word in low for word in NON_EXECUTABLE_WORDS):
        return False
    return True


def normalize_formula(s: str) -> str:
    return re.sub(r"\s+", "", s.strip())


def parents_from_rhs(lhs: str, rhs: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tok in TOKEN_RE.findall(rhs):
        if tok in RESERVED or tok == lhs:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", tok) and len(tok) < 4:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def state_type(lhs: str) -> str:
    if lhs.startswith("d") and "/dt" in lhs:
        return "derivative"
    if lhs.startswith("fx_") or lhs.startswith("agg_") or lhs.startswith("MC"):
        return "dcs"
    if lhs.endswith("_sp"):
        return "setpoint"
    if lhs.endswith("_phys"):
        return "physical_signal"
    if lhs.endswith("_prev") or "_prev" in lhs:
        return "state_reference"
    if lhs.startswith("L_") or lhs.startswith("M_") or lhs.startswith("T_"):
        return "state"
    if lhs.startswith("Q_"):
        return "flow"
    if lhs.startswith("I_") or lhs.startswith("P_"):
        return "equipment_signal"
    return "derived"


def formula_role(row: dict[str, str]) -> str:
    h2 = row["h2"]
    h3 = row["h3"]
    lhs = row["lhs"]
    if lhs in PROMOTED_CONCEPT_LHS:
        return "executable"
    if h3.startswith("10.") or h2.startswith("4.") or h2.startswith("8."):
        return "executable"
    if "{s" in lhs or "{c" in lhs or "{k" in lhs or "{j" in lhs:
        return "template"
    if h2.startswith("2.") or h2.startswith("3."):
        return "definition"
    if h2.startswith(("5.", "6.", "7.")):
        return "concept_template"
    return "reference"


def extract_dcs_from_v4() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    text = V4.read_text(encoding="utf-8")
    lines = text.splitlines()
    listed: dict[str, dict[str, str]] = {}
    measured: dict[str, dict[str, str]] = {}
    current_h2 = ""
    current_h3 = ""
    for idx, line in enumerate(lines, start=1):
        if line.startswith("## "):
            current_h2 = line[3:].strip()
            current_h3 = ""
        elif line.startswith("### "):
            current_h3 = line[4:].strip()

        m = TABLE_DCS_RE.match(line)
        if m and m.group("dcs") not in {"DCS", "DCS 模板"}:
            listed.setdefault(
                m.group("dcs"),
                {
                    "dcs_name": m.group("dcs"),
                    "listed_v4_lines": str(idx),
                    "listed_sections": f"{current_h2} / {current_h3}",
                },
            )
        if "按第 10." in line and "`" in line:
            dcs_text = line.split("按第 10.", 1)[0].strip()
            if not dcs_text or dcs_text.endswith(":"):
                continue
            grouped = GROUPED_DCS_RE.search(dcs_text)
            if grouped and "," in grouped.group("items"):
                items = [x.strip() for x in grouped.group("items").split(",")]
                for item in items:
                    expanded = f"{grouped.group('prefix')}_{item}_{grouped.group('suffix')}"
                    listed.setdefault(
                        expanded,
                        {
                            "dcs_name": expanded,
                            "listed_v4_lines": str(idx),
                            "listed_sections": f"{current_h2} / {current_h3}",
                        },
                    )
            else:
                listed.setdefault(
                    dcs_text,
                    {
                        "dcs_name": dcs_text,
                        "listed_v4_lines": str(idx),
                        "listed_sections": f"{current_h2} / {current_h3}",
                    },
                )

        meas = MEAS_RE.match(line)
        if meas:
            measured[meas.group("lhs")] = {
                "dcs_name": meas.group("lhs"),
                "physical_parent": meas.group("phys").strip(),
                "meas_v4_line": str(idx),
                "meas_section": f"{current_h2} / {current_h3}",
            }

    # Expand known measurement templates used in V4.
    if "fx_s{s}_{drug}_freq" in measured:
        base = measured["fx_s{s}_{drug}_freq"]
        for drug in DRUGS:
            measured[f"fx_s{{s}}_{drug}_freq"] = {
                **base,
                "dcs_name": f"fx_s{{s}}_{drug}_freq",
                "physical_parent": f"f_{{s,{drug}}}",
            }
    if "fx_s{s}_{drug}_curr" in measured:
        base = measured["fx_s{s}_{drug}_curr"]
        for drug in DRUGS:
            measured[f"fx_s{{s}}_{drug}_curr"] = {
                **base,
                "dcs_name": f"fx_s{{s}}_{drug}_curr",
                "physical_parent": f"I_drug_j_phys_{{s,{drug}}}",
            }
    if "agg_mag_tailings_valve1" in measured and "agg_mag_tailings_valve2" in measured:
        measured["agg_mag_tailings_valve1/2"] = {
            "dcs_name": "agg_mag_tailings_valve1/2",
            "physical_parent": "u_tail;u_tail_2",
            "meas_v4_line": measured["agg_mag_tailings_valve1"]["meas_v4_line"]
            + ";"
            + measured["agg_mag_tailings_valve2"]["meas_v4_line"],
            "meas_section": measured["agg_mag_tailings_valve1"]["meas_section"],
        }
    return listed, measured


def make_execution_steps() -> list[dict[str, str]]:
    data = [
        ("010", "boundary", "Update exogenous ore OU states and line availability."),
        ("020", "boundary", "Compute per-line wet/solid flow, grade, size, density, liberation, temperature."),
        ("030", "boundary", "Mass-weight mix three feed lines into boundary Stream."),
        ("100", "magnetic", "Update magnetic controller setpoints and actuator states."),
        ("110", "magnetic", "Update matrix clog, magnetic field, capture, entrainment, concentrate/tail streams."),
        ("120", "magnetic", "Compute magnetic DCS physical signals and measurements."),
        ("200", "tower_mill", "Update cyclone feed pool CSTR mixed Stream from magnetic concentrate and delayed mill discharge."),
        ("210", "tower_mill", "Update cyclone feed pump controller, pump flow, pressure, and pump DCS signals."),
        ("220", "tower_mill", "Compute cyclone partition, overflow/sand Streams, and absolute water/solid balances."),
        ("230", "tower_mill", "Update sand water addition, mill density, circulating load, mill power."),
        ("240", "tower_mill", "Update mill discharge Stream through tau_mill_residence states."),
        ("250", "tower_mill", "Update thermal states and tower mill DCS measurements."),
        ("300", "flotation", "Update thickener inventory and flotation feed Stream."),
        ("310", "flotation", "Update reagent demand, pump actuators, actual dose and adsorption lag states."),
        ("320", "flotation", "Update pH/Ca2+, blower/header, air valves, gas holdup and froth height."),
        ("330", "flotation", "Update cell apparent level control and outflow."),
        ("340", "flotation", "Update CSTR component inventories, froth/tail rates and stream topology."),
        ("350", "flotation", "Update flotation DCS measurements and series power."),
        ("400", "lab", "Sample process lab variables using sample_time/report_time delays."),
        ("500", "label", "Generate final labels from physically delayed final concentrate streams only."),
    ]
    return [{"step_order": a, "stage": b, "description": c} for a, b, c in data]


def make_implementation_constraints() -> list[dict[str, str]]:
    return [
        {
            "constraint_id": "C001",
            "category": "leakage_guard",
            "applies_to": "DCS;controllers;features",
            "rule": "Do not use current or future final concentrate labels y_fx_xin* as parents of DCS, controllers, or online features.",
            "implementation_check": "Fail if any formula parent of a DCS/controller/feature matches y_fx_xin* except label generation rows.",
            "source": "V4 reference/design constraint",
        },
        {
            "constraint_id": "C002",
            "category": "label_timing",
            "applies_to": "labels",
            "rule": "Final labels must be generated only from physically delayed final concentrate streams and lab/report schedules.",
            "implementation_check": "Verify label timestamps are later than the process states they summarize.",
            "source": "V5 execution principle",
        },
        {
            "constraint_id": "C003",
            "category": "dcs_measurement",
            "applies_to": "v5_dcs_outputs.csv",
            "rule": "Every DCS point must be produced from a physical parent through meas(...) or an explicit fault-injection measurement equation.",
            "implementation_check": "Compare v5_dcs_outputs.csv against executable formula parents and fail on missing physical_parent.",
            "source": "V5 clean hard check",
        },
        {
            "constraint_id": "C004",
            "category": "single_source_formula",
            "applies_to": "formula engine",
            "rule": "The runtime formula engine must read v5_executable_formulas.csv, not v5_formulas.csv.",
            "implementation_check": "Verify executable CSV is the exact executable/definition/manual subset of v5_formulas.csv.",
            "source": "V5 clean hard check",
        },
        {
            "constraint_id": "C005",
            "category": "manual_authority",
            "applies_to": "manual_override;manual_closure",
            "rule": "Rows with status manual_override or manual_closure are authoritative implementation formulas even when source_v4_line is manual or overridden.",
            "implementation_check": "Fail if code regenerates these formulas from V4 or drops them because source_v4_line=manual.",
            "source": "V5 migration policy",
        },
        {
            "constraint_id": "C006",
            "category": "stream_timing",
            "applies_to": "Stream properties",
            "rule": "Ore properties and stream hidden states must propagate through delays, inventories, CSTRs, or explicit topology; they must not teleport from boundary to downstream units.",
            "implementation_check": "Verify required causal edges and required state-delay edges in validate_v5_clean_spec.py.",
            "source": "V5 execution principle",
        },
    ]


def manual_formulas(start_index: int) -> list[dict[str, str]]:
    specs = [
        (
            "flotation",
            "dose_TD_s",
            "(Q_{s,td_rough}_ml_s+Q_{s,td_clean}_ml_s)*3.6*rho_td_kg_L*active_td/max(M_feed_solid_tph_s,eps)",
            "Q_{s,td_rough}_ml_s;Q_{s,td_clean}_ml_s;rho_td_kg_L;active_td;M_feed_solid_tph_s",
            "derived",
            "Actual TD dose from metering pump flow; added in V5 to close dose -> effect chain.",
        ),
        (
            "flotation",
            "dose_DF_K6_s",
            "Q_{s,k6_rough}_ml_s*3.6*rho_k6_kg_L*active_k6/max(M_feed_solid_tph_s,eps)",
            "Q_{s,k6_rough}_ml_s;rho_k6_kg_L;active_k6;M_feed_solid_tph_s",
            "derived",
            "Actual K6/DF dose from pump flow. L_k6_s remains inventory sink unless starvation mode is enabled.",
        ),
        (
            "flotation",
            "dose_naoh_kg_t_s",
            "Q_{s,naoh}_ml_s*3.6*rho_naoh_kg_L*active_naoh/max(M_feed_solid_tph_s,eps)",
            "Q_{s,naoh}_ml_s;rho_naoh_kg_L;active_naoh;M_feed_solid_tph_s",
            "derived",
            "Actual NaOH dose from pump flow.",
        ),
        (
            "flotation",
            "dose_cao_kg_t_s",
            "Q_{s,cao}_ml_s*3.6*rho_cao_kg_L*active_cao/max(M_feed_solid_tph_s,eps)",
            "Q_{s,cao}_ml_s;rho_cao_kg_L;active_cao;M_feed_solid_tph_s",
            "derived",
            "Actual CaO dose from pump flow.",
        ),
        (
            "flotation",
            "Q_feed_s",
            "Q_NT_under_s",
            "Q_NT_under_s",
            "flow",
            "Connect thickener underflow volumetric flow to the real flotation feed for each series.",
        ),
        (
            "flotation",
            "M_feed_solid_s",
            "M_NT_under_solid_s",
            "M_NT_under_solid_s",
            "flow",
            "Connect thickener underflow solid flow to flotation reagent/load controllers.",
        ),
        (
            "flotation",
            "M_feed_water_s",
            "M_NT_under_water_s",
            "M_NT_under_water_s",
            "flow",
            "Connect thickener underflow water flow to flotation feed stream.",
        ),
        (
            "flotation",
            "C_s",
            "M_feed_solid_s/max(M_feed_solid_s+M_feed_water_s,eps)",
            "M_feed_solid_s;M_feed_water_s",
            "derived",
            "Series flotation feed concentration from the actual thickener underflow stream.",
        ),
        (
            "flotation",
            "M_feed_j_s",
            "M_feed_solid_s*grade_NT_under_j_s",
            "M_feed_solid_s;grade_NT_under_j_s",
            "flow",
            "Component feed rate entering the first flotation cell from thickener underflow.",
        ),
        (
            "flotation",
            "feed_grade_j_s",
            "M_feed_j_s/max(M_feed_solid_s,eps)",
            "M_feed_j_s;M_feed_solid_s",
            "derived",
            "Component grade of the actual flotation feed stream.",
        ),
        (
            "flotation",
            "floatability_difficulty_s",
            "w_carb*r_carb_s+w_sil*r_sil_s+w_fine*f25_s+w_coarse*(1-F325_s)+w_low_lib*(1-Liberation_gangue_s)+w_density*abs(C_s-C_opt)+w_clay*clay_s",
            "r_carb_s;r_sil_s;f25_s;F325_s;Liberation_gangue_s;C_s;clay_s",
            "derived",
            "Series-specific difficult-floatability score used by reagent controllers.",
        ),
        (
            "flotation",
            "selectivity_proxy_s",
            "q_pH*pH_s+q_Ca*Ca2_effect_s+q_slime*(1-f25_s)+q_lib*Liberation_gangue_s",
            "pH_s;Ca2_effect_s;f25_s;Liberation_gangue_s",
            "derived",
            "Series-specific selectivity proxy used by K6 demand.",
        ),
        (
            "flotation",
            "E_Ca2_sil_s",
            "1+a_Ca_sil*sigmoid((Ca2_effect_s-Ca_sil0)/s_Ca_sil)",
            "Ca2_effect_s;Ca_sil0;s_Ca_sil",
            "derived",
            "Series-specific Ca2+ effect for silicate flotation kinetics.",
        ),
        (
            "flotation",
            "E_Ca2_carb_s",
            "1+a_Ca_carb*sigmoid((Ca2_effect_s-Ca_carb0)/s_Ca_carb)",
            "Ca2_effect_s;Ca_carb0;s_Ca_carb",
            "derived",
            "Series-specific Ca2+ effect for carbonate flotation kinetics.",
        ),
        (
            "flotation",
            "M_cell_solid_prev_{s,c}",
            "sum_j(M_cell_j_prev_{s,c})",
            "M_cell_j_prev_{s,c}",
            "state_reference",
            "Total previous solid inventory inside flotation cell CSTR.",
        ),
        (
            "flotation",
            "feed_j_rate_{s,c}",
            "topology_feed_j_rate(stage=c,series=s,Q_feed_s=Q_feed_s,feed_grade_j_s=feed_grade_j_s,Q_pump_pool_1=Q_pump_pool_{s,1},Q_pump_pool_2=Q_pump_pool_{s,2},Q_pump_pool_3=Q_pump_pool_{s,3},recycle_grade_j_1=recycle_grade_j_{s,1},recycle_grade_j_2=recycle_grade_j_{s,2},recycle_grade_j_3=recycle_grade_j_{s,3})",
            "topology_feed_j_rate;Q_feed_s;feed_grade_j_s;Q_pump_pool_{s,1};Q_pump_pool_{s,2};Q_pump_pool_{s,3};recycle_grade_j_{s,1};recycle_grade_j_{s,2};recycle_grade_j_{s,3}",
            "flow",
            "Resolved by flotation topology and explicitly consumes middling return pump outputs.",
        ),
        (
            "flotation",
            "entrainment_j_rate_{s,c}",
            "entrainment_factor_{s,c}*Q_out_solid_{s,c}*entr_share_j_c",
            "entrainment_factor_{s,c};Q_out_solid_{s,c};entr_share_j_c",
            "flow",
            "Mechanical entrainment rate from CSTR pulp discharge and slime/clay entrainment factor.",
        ),
        (
            "flotation",
            "rho_froth_mix_{s,c}",
            "sum_j(froth_j_rate_{s,c})/max(sum_j(froth_j_rate_{s,c}/rho_j),eps)",
            "froth_j_rate_{s,c};rho_j",
            "derived",
            "Froth mixture density for Q_froth_cell conversion.",
        ),
        (
            "tower_mill",
            "rho_solid_mix_feed",
            "rho_solid_mix",
            "rho_solid_mix",
            "derived",
            "Alias for tower mill feed solid density until component-specific feed density is expanded.",
        ),
        (
            "dcs",
            "fx_s{s}_{c}_froth_h",
            "ifelse(event_froth_fault_{s,c},fault_value,meas(h_froth_{s,c}))",
            "event_froth_fault_{s,c};fault_value;meas;h_froth_{s,c}",
            "dcs",
            "Froth height DCS output with explicit fault injection edge.",
        ),
        (
            "lab",
            "lab_tm_overflow_tfe",
            "lab_sample_template(_x_tm_overflow_tfe,sample_time_tm_overflow_tfe,report_time_tm_overflow_tfe,sigma_sampling_tm,sigma_assay_tfe)",
            "lab_sample_template;_x_tm_overflow_tfe;sample_time_tm_overflow_tfe;report_time_tm_overflow_tfe;sigma_sampling_tm;sigma_assay_tfe",
            "lab",
            "Concrete instance of the lab sampling template for tower-mill overflow TFe.",
        ),
        (
            "lab",
            "lab_mag_mixed_conc_tfe",
            "lab_sample_template(_x_mag_mixed_conc_tfe,sample_time_mag_mixed_conc_tfe,report_time_mag_mixed_conc_tfe,sigma_sampling_mag,sigma_assay_tfe)",
            "lab_sample_template;_x_mag_mixed_conc_tfe;sample_time_mag_mixed_conc_tfe;report_time_mag_mixed_conc_tfe;sigma_sampling_mag;sigma_assay_tfe",
            "lab",
            "Concrete instance of the lab sampling template for magnetic mixed concentrate TFe.",
        ),
    ]
    rows: list[dict[str, str]] = []
    for offset, (stage, lhs, rhs, parents, state, notes) in enumerate(specs, start=1):
        rows.append(
            {
                "formula_id": f"V5M_{start_index+offset:04d}",
                "stage": stage,
                "source_v4_line": "manual",
                "source_v4_section": "manual V5 closure",
                "lhs": lhs,
                "rhs": rhs,
                "formula_line": f"{lhs} = {rhs}",
                "parents": parents,
                "state_type": state,
                "formula_role": "executable",
                "observable": "no",
                "status": "manual_closure",
                "notes": notes,
            }
        )
    return rows


def main() -> None:
    if not V4_REGISTRY.exists():
        raise SystemExit("Run v5_migration_audit.py first to create V4_FORMULA_REGISTRY.csv")

    v4_rows = read_csv(V4_REGISTRY)
    candidates = [r for r in v4_rows if is_formula_candidate(r)]
    by_lhs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        by_lhs[row["lhs"]].append(row)

    canonical_by_lhs: dict[str, dict[str, str]] = {}
    migration_rows: list[dict[str, str]] = []
    formula_rows: list[dict[str, str]] = []
    variable_rows: list[dict[str, str]] = []
    edge_rows: list[dict[str, str]] = []
    conflict_rows: list[dict[str, str]] = []

    for lhs, rows in sorted(by_lhs.items()):
        sorted_rows = sorted(rows, key=formula_priority)
        canonical = sorted_rows[0]
        canonical_by_lhs[lhs] = canonical
        distinct = {normalize_formula(r["formula_line"]) for r in rows}
        conflict = "yes" if len(distinct) > 1 else "no"
        if conflict == "yes" and len(rows) > 1:
            for row in rows:
                conflict_rows.append(
                    {
                        "lhs": lhs,
                        "v4_line": row["line"],
                        "v4_section": f"{row['h2']} / {row['h3']}",
                        "formula_line": row["formula_line"],
                        "canonical_v4_line": canonical["line"],
                        "canonical_formula_line": canonical["formula_line"],
                        "suggested_action": "keep_canonical" if row is canonical else "supersede_or_merge",
                    }
                )
        for row in rows:
            is_canon = row is canonical
            if is_canon:
                status = "migrated"
                decision = "canonical_formula"
            elif normalize_formula(row["formula_line"]) == normalize_formula(canonical["formula_line"]):
                status = "merged"
                decision = "duplicate_same_formula"
            else:
                status = "superseded"
                decision = "duplicate_conflict_executable_preferred"
            migration_rows.append(
                {
                    "v4_formula_id": row["formula_id"],
                    "v4_line": row["line"],
                    "v4_section": f"{row['h2']} / {row['h3']}",
                    "lhs": lhs,
                    "v4_formula_line": row["formula_line"],
                    "v5_formula_id": f"V5_{len(canonical_by_lhs):04d}" if is_canon else "",
                    "migration_status": status,
                    "decision": decision,
                    "conflict_group": conflict,
                    "canonical_v4_line": canonical["line"],
                    "notes": "",
                }
            )

    # Add dropped rows explicitly so every extracted V4 formula has a migration status.
    migrated_ids = {r["v4_formula_id"] for r in migration_rows}
    for row in v4_rows:
        if row["formula_id"] in migrated_ids:
            continue
        migration_rows.append(
            {
                "v4_formula_id": row["formula_id"],
                "v4_line": row["line"],
                "v4_section": f"{row['h2']} / {row['h3']}",
                "lhs": row["lhs"],
                "v4_formula_line": row["formula_line"],
                "v5_formula_id": "",
                "migration_status": "dropped",
                "decision": "non_executable_or_block_header",
                "conflict_group": "no",
                "canonical_v4_line": "",
                "notes": "Dropped from formula CSV; prose/source record remains in V4.",
            }
        )

    for i, (lhs, row) in enumerate(sorted(canonical_by_lhs.items()), start=1):
        fid = f"V5_{i:04d}"
        stage = stage_from_section(row["h2"], row["h3"])
        rhs = row["rhs_excerpt"]
        override = CANONICAL_OVERRIDES.get(lhs)
        status = "canonical"
        notes = ""
        if override:
            rhs = override["rhs"]
            status = "manual_override"
            notes = override["notes"]
        elif lhs in PROMOTED_CONCEPT_LHS:
            status = "manual_promoted"
            notes = "Manually promoted from concept/reference coverage review into executable formulas."
        parents = parents_from_rhs(lhs, rhs)
        formula_rows.append(
            {
                "formula_id": fid,
                "stage": stage,
                "source_v4_line": row["line"],
                "source_v4_section": f"{row['h2']} / {row['h3']}",
                "lhs": lhs,
                "rhs": rhs,
                "formula_line": f"{lhs} = {rhs}" if override else row["formula_line"],
                "parents": ";".join(parents),
                "state_type": state_type(lhs),
                "formula_role": formula_role(row),
                "observable": "yes" if state_type(lhs) == "dcs" else "no",
                "status": status,
                "notes": notes,
            }
        )
        variable_rows.append(
            {
                "variable": lhs,
                "stage": stage,
                "state_type": state_type(lhs),
                "defined_by_formula_id": fid,
                "source_v4_line": row["line"],
                "observable": "yes" if state_type(lhs) == "dcs" else "no",
                "notes": "",
            }
        )
        for parent in parents:
            edge_rows.append(
                {
                    "from_variable": parent,
                    "to_variable": lhs,
                    "stage": stage,
                    "formula_id": fid,
                    "edge_type": "formula_parent",
                    "source_v4_line": row["line"],
                }
            )

    existing_lhs = {row["lhs"] for row in formula_rows}
    manual_rows = [row for row in manual_formulas(len(formula_rows)) if row["lhs"] not in existing_lhs]
    formula_rows.extend(manual_rows)
    for row in manual_rows:
        variable_rows.append(
            {
                "variable": row["lhs"],
                "stage": row["stage"],
                "state_type": row["state_type"],
                "defined_by_formula_id": row["formula_id"],
                "source_v4_line": row["source_v4_line"],
                "observable": row["observable"],
                "notes": row["notes"],
            }
        )
        for parent in row["parents"].split(";"):
            if parent:
                edge_rows.append(
                    {
                        "from_variable": parent,
                        "to_variable": row["lhs"],
                        "stage": row["stage"],
                        "formula_id": row["formula_id"],
                        "edge_type": "manual_formula_parent",
                        "source_v4_line": "manual",
                    }
                )

    listed_dcs, measured_dcs = extract_dcs_from_v4()
    dcs_rows: list[dict[str, str]] = []
    all_dcs = sorted(set(listed_dcs) | set(measured_dcs))
    for dcs in all_dcs:
        listed = listed_dcs.get(dcs, {})
        measured = measured_dcs.get(dcs, {})
        dcs_rows.append(
            {
                "dcs_name": dcs,
                "physical_parent": measured.get("physical_parent", ""),
                "listed_v4_lines": listed.get("listed_v4_lines", ""),
                "meas_v4_line": measured.get("meas_v4_line", ""),
                "listed_sections": listed.get("listed_sections", ""),
                "meas_section": measured.get("meas_section", ""),
                "migration_status": "migrated" if measured else "needs_review",
                "notes": "" if measured else "Listed in V4 but no explicit meas(...) found by parser.",
            }
        )

    write_csv(
        V5_MIGRATION,
        sorted(migration_rows, key=lambda r: int(r["v4_line"])),
        [
            "v4_formula_id",
            "v4_line",
            "v4_section",
            "lhs",
            "v4_formula_line",
            "v5_formula_id",
            "migration_status",
            "decision",
            "conflict_group",
            "canonical_v4_line",
            "notes",
        ],
    )
    write_csv(
        V5_FORMULAS,
        formula_rows,
        [
            "formula_id",
            "stage",
            "source_v4_line",
            "source_v4_section",
            "lhs",
            "rhs",
            "formula_line",
            "parents",
            "state_type",
            "formula_role",
            "observable",
            "status",
            "notes",
        ],
    )
    executable_rows = [
        row
        for row in formula_rows
        if row["formula_role"] in {"executable", "definition"} or row["status"] == "manual_closure"
    ]
    write_csv(
        V5_EXECUTABLE_FORMULAS,
        executable_rows,
        [
            "formula_id",
            "stage",
            "source_v4_line",
            "source_v4_section",
            "lhs",
            "rhs",
            "formula_line",
            "parents",
            "state_type",
            "formula_role",
            "observable",
            "status",
            "notes",
        ],
    )
    write_csv(
        V5_MANUAL,
        manual_rows,
        [
            "formula_id",
            "stage",
            "source_v4_line",
            "source_v4_section",
            "lhs",
            "rhs",
            "formula_line",
            "parents",
            "state_type",
            "formula_role",
            "observable",
            "status",
            "notes",
        ],
    )
    write_csv(
        V5_VARIABLES,
        variable_rows,
        [
            "variable",
            "stage",
            "state_type",
            "defined_by_formula_id",
            "source_v4_line",
            "observable",
            "notes",
        ],
    )
    write_csv(
        V5_EDGES,
        edge_rows,
        [
            "from_variable",
            "to_variable",
            "stage",
            "formula_id",
            "edge_type",
            "source_v4_line",
        ],
    )
    write_csv(V5_STEPS, make_execution_steps(), ["step_order", "stage", "description"])
    write_csv(
        V5_CONSTRAINTS,
        make_implementation_constraints(),
        ["constraint_id", "category", "applies_to", "rule", "implementation_check", "source"],
    )
    write_csv(
        V5_CONFLICTS,
        conflict_rows,
        [
            "lhs",
            "v4_line",
            "v4_section",
            "formula_line",
            "canonical_v4_line",
            "canonical_formula_line",
            "suggested_action",
        ],
    )
    write_csv(
        V5_DCS,
        dcs_rows,
        [
            "dcs_name",
            "physical_parent",
            "listed_v4_lines",
            "meas_v4_line",
            "listed_sections",
            "meas_section",
            "migration_status",
            "notes",
        ],
    )

    status_counts = Counter(r["migration_status"] for r in migration_rows)
    duplicate_v5_lhs = [
        lhs for lhs, count in Counter(r["lhs"] for r in formula_rows).items() if count > 1
    ]
    dcs_needs_review = [r for r in dcs_rows if r["migration_status"] == "needs_review"]

    V5_MD.write_text(
        "\n".join(
            [
                "# 选矿仿真系统 v5 clean 规格",
                "",
                "本文档只保留不可结构化的设计原则、执行顺序和审查口径。公式、变量、DCS 点位、因果边和迁移台账存放在同目录 CSV 中，作为实现与 pytest 自动审查的唯一结构化来源。",
                "",
                "## 结构化文件",
                "",
                "- `v5_formulas.csv`: 唯一公式表。一个 `lhs` 只能有一个 canonical 公式。",
                "- `v5_executable_formulas.csv`: 实现和 pytest 默认读取的执行公式表，不包含概念模板。",
                "- `v5_variables.csv`: 变量注册表。记录变量所属工序、状态类型、可观测性和定义公式。",
                "- `v5_dcs_outputs.csv`: DCS 点位表。每个 DCS 应有物理父节点和 `meas(...)` 来源。",
                "- `v5_causal_edges.csv`: 由公式右侧父变量抽取的候选因果边，供 DAG/pytest 初筛。",
                "- `v5_execution_steps.csv`: 每分钟仿真的执行顺序。",
                "- `v5_migration_from_v4.csv`: V4 公式迁移台账。每条 V4 公式必须有迁移状态。",
                "- `v5_manual_formulas.csv`: V5 为闭合关键因果链而新增的人工公式，主要用于实际药剂剂量和浮选 CSTR 缺口。",
                "- `v5_external_inputs.csv`: 未由公式生成但被公式引用的父节点注册表。每个父节点必须被分类为参数、上游流状态、设备状态、控制器内部量、实验室输入或模板索引。",
                "- `v5_implementation_constraints.csv`: 不作为每分钟公式执行、但必须进入 pytest/实现红线的设计约束。",
                "",
                "## 执行原则",
                "",
                "1. Markdown 不再重复可执行公式；实现以 `v5_executable_formulas.csv` 为准。",
                "2. 概念章节只描述因果意图，不再作为代码来源。",
                "3. 所有 Stream 属性必须随物流、库存或一阶/CSTR 状态传递，禁止入口边界矿质瞬时穿越到下游。",
                "4. DCS 必须由物理父节点经测量方程得到，禁止 `y` 或当前最终精矿化验直接进入 DCS。",
                "5. K6 药箱液位默认是库存/DCS sink，不作为实际加药量父节点，除非显式启用断药场景。",
                "6. 一个变量只允许一个 canonical 公式；跨章节重复的概念公式只能保留为 prose 或迁移台账，不能进入执行表。",
                "7. 非公式父节点必须出现在 `v5_external_inputs.csv`，不能在实现中临时发明名称或默认常数。",
                "",
                "## 迁移状态口径",
                "",
                "- `migrated`: 作为 V5 canonical 公式保留。",
                "- `merged`: 与 canonical 公式重复，已合并。",
                "- `superseded`: 与 canonical 冲突或低优先级，被执行段公式替代。",
                "- `dropped`: 非执行公式、示例禁用公式或多行块头，不进入公式 CSV。",
                "- `needs_review`: DCS 或变量无法由脚本确认完整迁移，需要人工裁决。",
                "",
                "## 当前完整性口径",
                "",
                "生成与校验脚本共同维护以下硬约束：无重复 `lhs`、无重复公式 ID、变量表与公式表一一对应、DCS 点位均有物理父节点、V4 公式均有迁移状态、所有非公式父节点均已注册且无 `needs_review`。若后续新增公式，必须先更新 CSV，再运行 `validate_v5_clean_spec.py`。",
                "",
            ]
        ),
        encoding="utf-8",
    )

    validation_lines = [
        "# V5 Migration Validation",
        "",
        f"V4 extracted formula assignments: **{len(v4_rows)}**",
        f"V4 executable candidates: **{len(candidates)}**",
        f"V5 canonical formulas: **{len(formula_rows)}**",
        f"V5 executable formulas: **{len(executable_rows)}**",
        f"Manual closure formulas: **{len(manual_rows)}**",
        f"V5 variables: **{len(variable_rows)}**",
        f"V5 causal edges: **{len(edge_rows)}**",
        f"V5 DCS rows: **{len(dcs_rows)}**",
        "",
        "## Migration Status Counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        validation_lines.append(f"- `{status}`: {count}")
    validation_lines += [
        "",
        "## Structural Checks",
        "",
        f"- Duplicate `lhs` in `v5_formulas.csv`: **{len(duplicate_v5_lhs)}**",
        f"- DCS rows needing review: **{len(dcs_needs_review)}**",
        f"- V4 formulas without migration status: **0**",
        "",
        "## DCS Needs Review",
        "",
    ]
    if dcs_needs_review:
        for row in dcs_needs_review:
            validation_lines.append(
                f"- `{row['dcs_name']}` listed at {row['listed_v4_lines']} but no explicit meas(...) was parsed."
            )
    else:
        validation_lines.append("None.")
    V5_VALIDATION.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")

    print(f"Wrote {V5_MD}")
    print(f"Wrote {V5_FORMULAS}")
    print(f"Wrote {V5_EXECUTABLE_FORMULAS}")
    print(f"Wrote {V5_VARIABLES}")
    print(f"Wrote {V5_DCS}")
    print(f"Wrote {V5_EDGES}")
    print(f"Wrote {V5_STEPS}")
    print(f"Wrote {V5_CONSTRAINTS}")
    print(f"Wrote {V5_MIGRATION}")
    print(f"Wrote {V5_CONFLICTS}")
    print(f"Wrote {V5_MANUAL}")
    print(f"Wrote {V5_VALIDATION}")
    print(f"v4_formula_assignments={len(v4_rows)}")
    print(f"v5_canonical_formulas={len(formula_rows)}")
    print(f"duplicate_v5_lhs={len(duplicate_v5_lhs)}")
    print(f"dcs_needs_review={len(dcs_needs_review)}")


if __name__ == "__main__":
    main()
