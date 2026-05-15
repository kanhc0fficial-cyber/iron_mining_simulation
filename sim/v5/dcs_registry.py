"""V5 DCS Output Registry.

Provides :class:`DCSOutputRegistry`, which indexes all DCS point rows from
``v5_dcs_outputs.csv`` (already loaded into :class:`FormulaRegistry`) and
provides helper methods for the PR-4 constraint checks.

Design rules enforced here
--------------------------
C003  Every DCS point must have a non-empty ``physical_parent``.
C001  A DCS point's parent chain must not include ``y_fx_xin*`` variables.

Usage
-----
    from sim.v5.spec_loader import load_spec
    from sim.v5.dcs_registry import DCSOutputRegistry

    registry = load_spec()
    dcs_reg = DCSOutputRegistry(registry)

    row = dcs_reg.get("agg_mag_level")       # DCSOutputRow
    dcs_reg.assert_has_physical_parent("agg_mag_level")  # raises if missing
    all_names = dcs_reg.all_dcs_names()      # frozenset
"""
from __future__ import annotations

import re
from typing import Dict, FrozenSet, List, Optional

from sim.v5.spec_loader import DCSOutputRow, FormulaRegistry


# Pattern matching y_fx_xin* labels
_LABEL_PATTERN = re.compile(r"^y_fx_xin")


class DCSRegistryError(ValueError):
    """Raised for DCS registry constraint violations."""


class DCSOutputRegistry:
    """Indexed view of V5 DCS output point rows from ``v5_dcs_outputs.csv``.

    Parameters
    ----------
    formula_registry :
        A loaded :class:`~sim.v5.spec_loader.FormulaRegistry`.

    Attributes
    ----------
    rows : list[DCSOutputRow]
        All DCS output rows in declaration order.
    by_name : dict[str, DCSOutputRow]
        ``dcs_name`` → :class:`~sim.v5.spec_loader.DCSOutputRow`.
    """

    def __init__(self, formula_registry: FormulaRegistry) -> None:
        self.rows: List[DCSOutputRow] = list(formula_registry.dcs_outputs)

        self.by_name: Dict[str, DCSOutputRow] = {}

        # Pass 1: register every row by its exact dcs_name so that individual
        # rows are never overwritten by a compound row that shares a prefix.
        for row in self.rows:
            self.by_name[row.dcs_name] = row

        # Pass 2: register split prefixes only if the prefix is not already
        # taken by a dedicated row (e.g. "agg_mag_tailings_valve1" is a real
        # row, so the prefix from "agg_mag_tailings_valve1/2" must not
        # overwrite it).
        for row in self.rows:
            key = row.dcs_name.split("/")[0].strip()
            if key != row.dcs_name:
                self.by_name.setdefault(key, row)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get(self, dcs_name: str) -> Optional[DCSOutputRow]:
        """Return the :class:`DCSOutputRow` for *dcs_name*, or ``None``."""
        return self.by_name.get(dcs_name)

    def all_dcs_names(self) -> FrozenSet[str]:
        """Return the set of all registered DCS point names."""
        return frozenset(self.by_name)

    # ------------------------------------------------------------------
    # Constraint checks
    # ------------------------------------------------------------------

    def assert_has_physical_parent(self, dcs_name: str) -> None:
        """Raise :class:`DCSRegistryError` if *dcs_name* lacks a physical_parent.

        Implements constraint C003.

        Raises
        ------
        DCSRegistryError
            If *dcs_name* is not registered or has an empty ``physical_parent``.
        """
        row = self.by_name.get(dcs_name)
        if row is None:
            raise DCSRegistryError(
                f"DCS point '{dcs_name}' is not registered in v5_dcs_outputs.csv."
            )
        if not row.physical_parent or not row.physical_parent.strip():
            raise DCSRegistryError(
                f"DCS point '{dcs_name}' has no physical_parent (C003 violation)."
            )

    def validate_all_have_physical_parent(self) -> List[str]:
        """Return a list of DCS names that violate the physical_parent rule (C003).

        Returns
        -------
        list[str]
            Names of DCS rows with empty or missing ``physical_parent``.
        """
        violators: List[str] = []
        for row in self.rows:
            pp = row.physical_parent or ""
            # Skip compound entries like "agg_mag_tailings_valve1/2" as their
            # parents are semicolon-joined; treat as valid if any is non-empty.
            if not pp.strip():
                violators.append(row.dcs_name)
        return violators

    def validate_no_label_parents(
        self, formula_registry: FormulaRegistry
    ) -> List[str]:
        """Return DCS names whose formula parents include ``y_fx_xin*`` (C001).

        Checks the formula ``parents`` field for each DCS LHS found in the
        :class:`FormulaRegistry`.  Template names (containing ``{``) are
        matched by the underlying lhs key.

        Returns
        -------
        list[str]
            LHS names of DCS formulas whose parent lists contain y_fx_xin*.
        """
        violations: List[str] = []
        dcs_lhs_names = {
            row.lhs
            for row in formula_registry.formulas
            if row.state_type == "dcs"
        }
        for lhs in dcs_lhs_names:
            parents = formula_registry.parents_of.get(lhs, ())
            for parent in parents:
                if _LABEL_PATTERN.match(parent):
                    violations.append(lhs)
                    break
        return violations
