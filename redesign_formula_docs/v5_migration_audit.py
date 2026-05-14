from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "DESIGN_V4_FACTORY_CAUSAL_SIMULATION.md"
REGISTRY = ROOT / "V4_FORMULA_REGISTRY.csv"
REPORT = ROOT / "V4_MIGRATION_AUDIT_REPORT.md"


HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
ASSIGN_RE = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_][A-Za-z0-9_{} ,]*|d[A-Za-z0-9_{} ,()]+/dt)\s*="
)
MEAS_RE = re.compile(r"^\s*(?P<lhs>[A-Za-z0-9_{}]+)\s*=\s*meas\((?P<phys>[^)]+)\)")
TABLE_DCS_RE = re.compile(r"\|\s*`(?P<dcs>[^`]+)`\s*\|")
INLINE_DCS_RE = re.compile(r"(?P<dcs>[A-Za-z0-9_{}]+)\s+按第\s+10\.\d+\s+节\s+`(?P<phys>[^`]+)`")


def normalize_lhs(lhs: str) -> str:
    lhs = lhs.strip()
    lhs = re.sub(r"\s+", "", lhs)
    return lhs


def iter_sections(lines: list[str]):
    current_h2 = ""
    current_h3 = ""
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            level, title = m.group(1), m.group(2)
            if level == "##":
                current_h2 = title
                current_h3 = ""
            else:
                current_h3 = title
        yield idx, current_h2, current_h3, line


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()

    rows: list[dict[str, str]] = []
    dcs_table: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    dcs_meas: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    assignment_sites: dict[str, list[dict[str, str]]] = defaultdict(list)

    in_fence = False
    fence_lang = ""
    block_id = 0
    current_block_start = 0
    block_lines: list[tuple[int, str, str, str]] = []
    current_h2 = ""
    current_h3 = ""

    section_by_line: dict[int, tuple[str, str]] = {}
    for idx, h2, h3, line in iter_sections(lines):
        section_by_line[idx] = (h2, h3)

    for idx, line in enumerate(lines, start=1):
        h2, h3 = section_by_line[idx]
        heading = HEADING_RE.match(line)
        if heading:
            current_h2 = h2
            current_h3 = h3

        table = TABLE_DCS_RE.match(line)
        if table and table.group("dcs") not in {"DCS", "DCS 模板"}:
            dcs_table[table.group("dcs")].append((idx, current_h2, current_h3))

        inline = INLINE_DCS_RE.search(line)
        if inline:
            dcs_table[inline.group("dcs")].append((idx, current_h2, current_h3))

        if line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_lang = line.strip()[3:].strip()
                block_id += 1
                current_block_start = idx
                block_lines = []
            else:
                j = 0
                while j < len(block_lines):
                    b_idx, b_h2, b_h3, b_line = block_lines[j]
                    assign = ASSIGN_RE.match(b_line)
                    if not assign:
                        j += 1
                        continue
                    lhs = normalize_lhs(assign.group("lhs"))
                    formula_parts = [b_line.strip()]
                    k = j + 1
                    while k < len(block_lines):
                        next_idx, _, _, next_line = block_lines[k]
                        if ASSIGN_RE.match(next_line):
                            break
                        if not next_line.strip():
                            break
                        if next_line.lstrip().startswith(("#", "//")):
                            break
                        if next_line.strip() in {"else:", "for j in {gangue,fe_sil,fe_carb,fe_mag,fe_hem}:"}:
                            break
                        # Continuation lines usually start with operators, commas, closing parens,
                        # or indentation. Keep them so multi-line formulas are not dropped.
                        if next_line.startswith((" ", "\t")) or next_line.strip().startswith(("+", "-", "*", "/", ")", "0,", "1,", "eps)", "f_", "u_", "Q_", "M_", "T_", "L_", "P_", "I_", "E_", "R_", "rho_", "mu_", "sigmoid", "clip", "/")):
                            formula_parts.append(next_line.strip())
                            k += 1
                            continue
                        break

                    formula_line = " ".join(formula_parts)
                    rhs = formula_line.split("=", 1)[1].strip() if "=" in formula_line else ""
                    row = {
                        "formula_id": f"F{block_id:04d}_{b_idx}",
                        "line": str(b_idx),
                        "h2": b_h2,
                        "h3": b_h3,
                        "block_start_line": str(current_block_start),
                        "fence_lang": fence_lang,
                        "lhs": lhs,
                        "rhs_excerpt": rhs,
                        "formula_line": formula_line,
                    }
                    rows.append(row)
                    assignment_sites[lhs].append(row)

                    meas = MEAS_RE.match(b_line)
                    if meas:
                        dcs_meas[meas.group("lhs")].append(
                            (b_idx, b_h2, b_h3, meas.group("phys").strip())
                        )
                    j = max(k, j + 1)

                in_fence = False
                fence_lang = ""
            continue

        if not in_fence:
            continue
        block_lines.append((idx, current_h2, current_h3, line))

    with REGISTRY.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "formula_id",
                "line",
                "h2",
                "h3",
                "block_start_line",
                "fence_lang",
                "lhs",
                "rhs_excerpt",
                "formula_line",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    duplicate_lhs = {
        lhs: sites
        for lhs, sites in assignment_sites.items()
        if len(sites) > 1
    }
    cross_section_duplicates = {
        lhs: sites
        for lhs, sites in duplicate_lhs.items()
        if len({(s["h2"], s["h3"]) for s in sites}) > 1
    }

    table_dcs = set(dcs_table)
    measured_dcs = set(dcs_meas)
    missing_meas = sorted(table_dcs - measured_dcs)
    extra_meas = sorted(measured_dcs - table_dcs)

    report_lines: list[str] = []
    report_lines.append("# V4 Migration Audit Report")
    report_lines.append("")
    report_lines.append(f"Source: `{SOURCE.name}`")
    report_lines.append(f"Formula assignments extracted: **{len(rows)}**")
    report_lines.append(f"Unique assigned LHS variables: **{len(assignment_sites)}**")
    report_lines.append(f"LHS assigned more than once: **{len(duplicate_lhs)}**")
    report_lines.append(
        f"LHS assigned in multiple sections/subsections: **{len(cross_section_duplicates)}**"
    )
    report_lines.append(f"DCS variables listed in tables/inline refs: **{len(table_dcs)}**")
    report_lines.append(f"DCS variables with explicit `=meas(...)`: **{len(measured_dcs)}**")
    report_lines.append(f"Listed DCS without explicit meas line: **{len(missing_meas)}**")
    report_lines.append(f"Explicit meas not listed in DCS tables: **{len(extra_meas)}**")
    report_lines.append("")

    report_lines.append("## Cross-Section Duplicate Assignments")
    report_lines.append("")
    if not cross_section_duplicates:
        report_lines.append("None detected.")
    else:
        for lhs, sites in sorted(cross_section_duplicates.items()):
            report_lines.append(f"### `{lhs}`")
            for site in sites:
                report_lines.append(
                    f"- line {site['line']}: {site['h2']} / {site['h3']} -> `{site['formula_line']}`"
                )
            report_lines.append("")

    report_lines.append("## Listed DCS Without Explicit `meas(...)`")
    report_lines.append("")
    if not missing_meas:
        report_lines.append("None detected.")
    else:
        for dcs in missing_meas:
            locs = "; ".join(
                f"line {line} {h2}/{h3}" for line, h2, h3 in dcs_table[dcs]
            )
            report_lines.append(f"- `{dcs}` ({locs})")
    report_lines.append("")

    report_lines.append("## Explicit `meas(...)` Not Listed In DCS Tables")
    report_lines.append("")
    if not extra_meas:
        report_lines.append("None detected.")
    else:
        for dcs in extra_meas:
            locs = "; ".join(
                f"line {line} {h2}/{h3} <- `{phys}`"
                for line, h2, h3, phys in dcs_meas[dcs]
            )
            report_lines.append(f"- `{dcs}` ({locs})")

    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"Wrote {REGISTRY}")
    print(f"Wrote {REPORT}")
    print(f"formula_assignments={len(rows)}")
    print(f"unique_lhs={len(assignment_sites)}")
    print(f"cross_section_duplicate_lhs={len(cross_section_duplicates)}")
    print(f"listed_dcs_without_meas={len(missing_meas)}")
    print(f"meas_without_table_listing={len(extra_meas)}")


if __name__ == "__main__":
    main()
