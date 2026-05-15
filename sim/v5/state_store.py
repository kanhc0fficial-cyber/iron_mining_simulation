"""V5 StateStore — variable value store with time-step history.

The StateStore tracks the current and previous time-step values for every
simulation variable.  It also holds a DCS output buffer and exposes helpers
for lag/delayed reads so that formula evaluators can resolve
``previous_state_reference`` parents without special-casing.

Usage
-----
    from sim.v5.state_store import StateStore

    store = StateStore()
    store.set("C_feed", 0.65)
    store.advance()            # move current -> previous
    store.set("C_feed", 0.68)
    prev = store.get_previous("C_feed")   # 0.65
    curr = store.get("C_feed")            # 0.68
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class StateStoreError(KeyError):
    """Raised when an unregistered variable is accessed."""


class StateStore:
    """In-memory store for simulation state variables across one time step.

    Variables do *not* need to be pre-registered; they are created on first
    write.  However, reading a variable that has never been written raises
    :class:`StateStoreError` so that the engine can detect missing parents
    early.

    Attributes
    ----------
    current : dict[str, Any]
        Values for the current time step.
    previous : dict[str, Any]
        Values from the previous time step (populated by :meth:`advance`).
    dcs_buffer : dict[str, Any]
        Buffer for DCS output values; written by formula evaluators and read
        by the output writer.
    """

    def __init__(self) -> None:
        self.current: Dict[str, Any] = {}
        self.previous: Dict[str, Any] = {}
        self.dcs_buffer: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Current step access
    # ------------------------------------------------------------------

    def set(self, name: str, value: Any) -> None:
        """Write *value* to the current time step for variable *name*."""
        self.current[name] = value

    def get(self, name: str) -> Any:
        """Return the current-step value for *name*.

        Raises
        ------
        StateStoreError
            If *name* has not been written in the current step.
        """
        if name not in self.current:
            raise StateStoreError(
                f"Variable '{name}' not found in current state. "
                "Ensure it is computed before being read."
            )
        return self.current[name]

    def get_or_none(self, name: str) -> Optional[Any]:
        """Return the current-step value or *None* if not yet written."""
        return self.current.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self.current

    # ------------------------------------------------------------------
    # Previous step access (previous_state_reference resolution)
    # ------------------------------------------------------------------

    def get_previous(self, name: str) -> Any:
        """Return the previous-step value for *name*.

        This resolves ``previous_state_reference`` parents in the V5 spec.

        Raises
        ------
        StateStoreError
            If *name* has no previous value (first time step or never written).
        """
        if name not in self.previous:
            raise StateStoreError(
                f"Variable '{name}' not found in previous state. "
                "Either the simulation has not advanced yet or the variable "
                "was never written in the prior step."
            )
        return self.previous[name]

    def get_previous_or_default(self, name: str, default: Any = None) -> Any:
        """Return the previous-step value or *default* if none exists."""
        return self.previous.get(name, default)

    # ------------------------------------------------------------------
    # Time-step advancement
    # ------------------------------------------------------------------

    def advance(self) -> None:
        """Advance the store to the next time step.

        Copies ``current`` into ``previous``, then clears ``current`` so
        that it can be repopulated by the next evaluation cycle.  The
        ``dcs_buffer`` is also cleared ready for the next step's DCS writes.
        """
        self.previous = dict(self.current)
        self.current = {}
        self.dcs_buffer = {}

    # ------------------------------------------------------------------
    # DCS buffer
    # ------------------------------------------------------------------

    def set_dcs(self, name: str, value: Any) -> None:
        """Write a DCS output value to the buffer."""
        self.dcs_buffer[name] = value

    def get_dcs(self, name: str) -> Any:
        """Return a DCS output value from the buffer.

        Raises
        ------
        StateStoreError
            If *name* is not in the DCS buffer.
        """
        if name not in self.dcs_buffer:
            raise StateStoreError(
                f"DCS output '{name}' not found in DCS buffer."
            )
        return self.dcs_buffer[name]

    # ------------------------------------------------------------------
    # Snapshot (for testing / debug)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy of the current state dict."""
        return dict(self.current)
