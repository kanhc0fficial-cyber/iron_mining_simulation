"""V5 ExternalInputRegistry — validated registry of external input parents.

The registry is initialised from the :class:`~sim.v5.spec_loader.FormulaRegistry`
(which in turn reads ``v5_external_inputs.csv``).  Once built, any lookup of
an unregistered name raises :class:`UnregisteredInputError`, enforcing rule
C004 / PR-2 requirement: *"未注册变量访问必须报错"*.

Usage
-----
    from sim.v5.spec_loader import load_spec
    from sim.v5.external_input_registry import ExternalInputRegistry

    registry = load_spec()
    inputs = ExternalInputRegistry(registry)

    cls = inputs.get_classification("B_max")      # "parameter"
    inputs.assert_registered("B_max")             # no-op if registered
    inputs.assert_registered("invented_var")      # raises UnregisteredInputError
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List

from sim.v5.spec_loader import ExternalInputRow, FormulaRegistry


class UnregisteredInputError(KeyError):
    """Raised when an unregistered external parent is accessed."""


class ExternalInputRegistry:
    """Indexed view of the V5 external input parents from ``v5_external_inputs.csv``.

    Parameters
    ----------
    formula_registry :
        A loaded :class:`~sim.v5.spec_loader.FormulaRegistry`.  The
        ``external_inputs`` attribute is used to build this registry.

    Attributes
    ----------
    rows : list[ExternalInputRow]
        All external input rows in declaration order.
    by_parent : dict[str, ExternalInputRow]
        parent name -> ExternalInputRow.
    by_classification : dict[str, list[ExternalInputRow]]
        classification -> list of ExternalInputRow.
    """

    def __init__(self, formula_registry: FormulaRegistry) -> None:
        self.rows: List[ExternalInputRow] = list(formula_registry.external_inputs)

        self.by_parent: Dict[str, ExternalInputRow] = {}
        self.by_classification: Dict[str, List[ExternalInputRow]] = {}

        for row in self.rows:
            self.by_parent[row.parent] = row
            self.by_classification.setdefault(row.classification, []).append(row)

    # ------------------------------------------------------------------
    # Registration checks
    # ------------------------------------------------------------------

    def is_registered(self, name: str) -> bool:
        """Return ``True`` if *name* is a registered external parent."""
        return name in self.by_parent

    def assert_registered(self, name: str) -> None:
        """Raise :class:`UnregisteredInputError` if *name* is not registered.

        This is the primary guard enforcing the V5 rule that temporary /
        invented variables must not be introduced.

        Raises
        ------
        UnregisteredInputError
        """
        if name not in self.by_parent:
            raise UnregisteredInputError(
                f"Variable '{name}' is not a registered external input in "
                "v5_external_inputs.csv. Do not invent unregistered parents."
            )

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_classification(self, name: str) -> str:
        """Return the classification string for *name*.

        Raises
        ------
        UnregisteredInputError
            If *name* is not registered.
        """
        self.assert_registered(name)
        return self.by_parent[name].classification

    def get_row(self, name: str) -> ExternalInputRow:
        """Return the full :class:`ExternalInputRow` for *name*.

        Raises
        ------
        UnregisteredInputError
            If *name* is not registered.
        """
        self.assert_registered(name)
        return self.by_parent[name]

    def parents_by_classification(self, classification: str) -> FrozenSet[str]:
        """Return the set of parent names with the given *classification*."""
        rows = self.by_classification.get(classification, [])
        return frozenset(r.parent for r in rows)

    def all_registered(self) -> FrozenSet[str]:
        """Return the set of all registered parent names."""
        return frozenset(self.by_parent)
