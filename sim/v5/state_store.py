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
        self.previous_dcs: Dict[str, Any] = {}

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
        """Return the current-step value or *None* if not yet written.

        .. warning::
            This method is ambiguous when a variable has been explicitly set to
            ``None``.  In that case ``get_or_none`` returns ``None`` for both
            *"not written"* and *"written with value None"*.  Use :meth:`has`
            for an unambiguous existence check.
        """
        return self.current.get(name)

    def has(self, name: str) -> bool:
        """Return ``True`` if *name* has been written in the current step.

        Unlike ``name in store`` (which is an alias for this method), the name
        ``has`` makes the semantics explicit: it tests the *current* step only.
        Variables that were written in a prior step and are accessible via
        :meth:`get_previous` are **not** considered present by this check.
        """
        return name in self.current

    def __contains__(self, name: str) -> bool:
        """Return ``True`` if *name* is present in the **current** step.

        .. note::
            This checks the current step only.  A variable that was written in
            the previous step (accessible via :meth:`get_previous`) is **not**
            considered present by this operator.  Use :meth:`has` for the same
            check with an explicit name.
        """
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
        that it can be repopulated by the next evaluation cycle.

        The DCS buffer is saved to ``previous_dcs`` before being cleared so
        that it remains readable after the advance (e.g. for a late-reading
        output writer).  Callers that need to flush the buffer *before*
        advancing should use :meth:`flush_dcs` instead.

        .. note::
            To avoid silent DCS data loss, prefer reading the DCS buffer
            (via :meth:`get_dcs` or :meth:`flush_dcs`) **before** calling
            ``advance()``.
        """
        self.previous = dict(self.current)
        self.current = {}
        self.previous_dcs = dict(self.dcs_buffer)
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

    def flush_dcs(self) -> Dict[str, Any]:
        """Return a copy of the DCS buffer and clear it.

        This is the recommended way for the output writer to consume the DCS
        buffer.  Calling :meth:`flush_dcs` before :meth:`advance` ensures no
        DCS values are lost.

        Returns
        -------
        dict
            Shallow copy of the DCS buffer at the time of the call.
        """
        snapshot = dict(self.dcs_buffer)
        self.dcs_buffer = {}
        return snapshot

    # ------------------------------------------------------------------
    # Snapshot (for testing / debug)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy of the current state dict."""
        return dict(self.current)

    def snapshot_full(self) -> Dict[str, Any]:
        """Return a dict containing shallow copies of all internal buffers.

        Useful for debugging and test assertions that need to inspect the full
        store state (current values, previous step values, and DCS buffer).

        Returns
        -------
        dict
            Keys: ``"current"``, ``"previous"``, ``"dcs_buffer"``,
            ``"previous_dcs"``.
        """
        return {
            "current": dict(self.current),
            "previous": dict(self.previous),
            "dcs_buffer": dict(self.dcs_buffer),
            "previous_dcs": dict(self.previous_dcs),
        }
