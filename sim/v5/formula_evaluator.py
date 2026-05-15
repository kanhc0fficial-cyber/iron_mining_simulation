"""V5 formula evaluator — evaluates a single FormulaRow RHS.

The evaluator converts formula RHS strings (as stored in
``v5_executable_formulas.csv``) into Python-evaluable expressions, then
executes them inside a controlled namespace built from:

1. Core helper functions (clip, sigmoid, lab_sample_template, …).
2. Static parameters supplied at construction time.
3. Previous-step state from :class:`~sim.v5.state_store.StateStore`.
4. Current-step state already computed in this timestep.

Usage
-----
    from sim.v5.spec_loader import load_spec
    from sim.v5.state_store import StateStore
    from sim.v5.formula_evaluator import FormulaEvaluator

    registry = load_spec()
    store = StateStore()
    evaluator = FormulaEvaluator(params={"B_max": 1.5, "I_exc": 10.0, ...})

    formula = registry.by_lhs["B_eff"]
    result = evaluator.eval_formula(formula, store)   # float
    store.set("B_eff", result)

Notes on indexed formulas
-------------------------
Many V5 formulas use ``_j``, ``_{s,c}``, ``_i`` etc. subscripts to
indicate they are evaluated once per index value (mineral component, cell,
feed line).  The skeleton evaluator treats those as *scalar* names — i.e.
``capture_j`` is a single variable, not a list.  A full implementation
would expand indices; this skeleton correctly executes all non-indexed and
scalar-subscripted formulas so that the engine can run test timesteps.

Unsupported formulas
--------------------
When a formula RHS references a helper or variable that cannot be resolved
the evaluator raises :class:`UnsupportedFormulaError`.  This is an
*explicit* error — it is **not** silently skipped (rule: 不要静默跳过).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from sim.v5.helpers import build_helpers_namespace
from sim.v5.spec_loader import FormulaRow


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FormulaEvaluationError(RuntimeError):
    """Raised when a formula RHS cannot be evaluated."""


class UnsupportedFormulaError(FormulaEvaluationError):
    """Raised when formula RHS requires an unrecognised name or helper.

    This differs from :class:`FormulaEvaluationError` (generic runtime
    errors) in that the failure is due to a *missing symbol* — indicating
    that the formula needs an explicit helper implementation.
    """


# ---------------------------------------------------------------------------
# RHS preprocessing
# ---------------------------------------------------------------------------


def preprocess_rhs(rhs: str) -> str:
    """Transform a V5 formula RHS string into valid Python.

    Transformations applied
    -----------------------
    * ``^`` → ``**``  (exponentiation)
    * ``N(mu, sigma)`` → ``N(mu, sigma)``  (already mapped in namespace;
      this step is a no-op since ``N`` is in the helper namespace)
    * Strip inline comments (``# …``) that appear after the expression.
    * Strip leading/trailing whitespace.

    Template-variable detection
    ---------------------------
    V5 formula names use ``{s,c}``-style placeholders (e.g. ``Q_air_{s,c}``)
    to indicate indexed formulas.  Python cannot parse these as identifiers, so
    any RHS that still contains un-expanded brace-subscripts raises
    :class:`UnsupportedFormulaError` **before** the expression is passed to
    ``eval()``.  This prevents opaque ``SyntaxError`` crashes and allows the
    engine to count template formulas separately from missing-symbol failures.
    """
    if not rhs or rhs.strip().upper() in {"NAN", "NAN;", ""}:
        return "float('nan')"

    # Detect un-expanded template placeholders like {s,c}, {s}, {c}, {0,1}
    if re.search(r"\{[^}]+\}", rhs):
        raise UnsupportedFormulaError(
            f"Formula RHS contains un-expanded template placeholder: {rhs!r}. "
            "The formula must be instantiated for each index value before evaluation."
        )

    # Replace ^ with ** for exponentiation (V5 spec uses ^ like math notation)
    expr = rhs.replace("^", "**")

    # Strip trailing inline comments
    expr = re.sub(r"\s*#[^\n]*$", "", expr).strip()

    # Replace V5 spec semicolons used as argument separators with Python commas.
    # The V5 formula spec uses ";" as an alternative separator inside function
    # calls (e.g. F(45e-6;d80_i,n_rr)).  Python requires commas.
    expr = expr.replace(";", ",")

    return expr


# ---------------------------------------------------------------------------
# FormulaEvaluator
# ---------------------------------------------------------------------------


class FormulaEvaluator:
    """Evaluates V5 formula RHS strings against the current simulation state.

    Parameters
    ----------
    params :
        Static parameter dictionary (external inputs of type *parameter*,
        *previous_state_reference* defaults, and global constants such as
        ``eps`` and ``dt``).  These are merged into the namespace at the
        lowest priority (state values override params).
    dt :
        Simulation time step in seconds (default 60 s).
    rng :
        Optional :class:`random.Random` instance for reproducible noise.

    Attributes
    ----------
    executed_lhs : set[str]
        LHS names of formulas successfully evaluated in the current run.
    unsupported : dict[str, str]
        LHS → error message for formulas that raised
        :class:`UnsupportedFormulaError` (missing symbol / helper).
    failed : dict[str, str]
        LHS → error message for formulas that raised
        :class:`FormulaEvaluationError` (other runtime errors).
    """

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        dt: float = 60.0,
        rng=None,
    ) -> None:
        self._params: Dict[str, Any] = dict(params) if params else {}
        self._dt = float(dt)
        self._rng = rng
        self._helpers_ns: Dict[str, Any] = build_helpers_namespace(rng=rng)

        self.executed_lhs: set = set()
        self.unsupported: Dict[str, str] = {}
        self.failed: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Namespace building
    # ------------------------------------------------------------------

    def build_namespace(self, store, step_time: float = 0.0) -> Dict[str, Any]:
        """Build the eval namespace for one formula evaluation.

        Priority (highest overwrites lowest):
        1. ``helpers`` (clip, sigmoid, …)
        2. ``params`` (physical constants, controller gains, …)
        3. ``previous`` state (store.previous, also added as ``X_prev``)
        4. ``current`` state (store.current — values already computed this step)
        5. Global constants (``eps``, ``dt``, ``_step_time``)

        The ``X_prev`` injection ensures that V5 naming convention
        ``matrix_clog_prev`` resolves to ``store.previous["matrix_clog"]``
        even when only ``matrix_clog`` is a key in the previous-state dict.

        .. note::
            Previous-state values are also injected as plain ``X`` (in addition
            to ``X_prev``) so that carry-over state variables (temperatures,
            slow dynamics) remain accessible in formulas that have not yet been
            computed this step.  This means that if an upstream formula fails or
            is skipped, its downstream consumers will silently fall back to the
            last-known value rather than raising ``NameError``.  Callers that
            need to detect stale-dependency usage should inspect the ``skipped``
            dict on the engine after each step.
        """
        from sim.v5.helpers import lab_sample_template as _lab_sample_template_fn

        ns: Dict[str, Any] = {}

        # 1. Helpers
        ns.update(self._helpers_ns)

        # 2. Static params
        ns.update(self._params)

        # 3. Previous state — both as X and as X_prev
        for k, v in store.previous.items():
            ns[k] = v
            ns[f"{k}_prev"] = v

        # 4. Current step values (override previous for same-named keys)
        ns.update(store.current)

        # 5. Well-known constants and builtins
        ns["eps"] = 1e-10
        ns["dt"] = self._dt
        ns["_step_time"] = step_time

        # BUG-PR9-B fix: override the lab_sample_template wrapper so that
        # step_time is the *actual* current simulation clock, not the wrapper's
        # default 0.0.  Without this, any report_time > 0 would leave the lab
        # formula permanently returning NaN regardless of how many steps have run.
        _st = step_time
        _rng = self._rng

        def _lab_step_bound(x_val, sample_time, report_time, sigma_sampling, sigma_assay):
            return _lab_sample_template_fn(
                x_val, sample_time, report_time, sigma_sampling, sigma_assay,
                step_time=_st, rng=_rng,
            )

        ns["lab_sample_template"] = _lab_step_bound

        return ns

    # ------------------------------------------------------------------
    # Formula evaluation
    # ------------------------------------------------------------------

    def eval_formula(
        self,
        formula: FormulaRow,
        store,
        step_time: float = 0.0,
    ) -> Any:
        """Evaluate the RHS of *formula* and return the result.

        Parameters
        ----------
        formula :
            A :class:`~sim.v5.spec_loader.FormulaRow` from the V5 registry.
        store :
            :class:`~sim.v5.state_store.StateStore` holding the current
            and previous simulation state.
        step_time :
            Current simulation clock in seconds (used by time-dependent
            helpers such as :func:`~sim.v5.helpers.lab_sample_template`).

        Returns
        -------
        Any
            The evaluated result (usually a ``float``).

        Raises
        ------
        UnsupportedFormulaError
            When a name in the formula RHS cannot be resolved — the formula
            needs an explicit helper or initialisation value.
        FormulaEvaluationError
            For any other evaluation error.
        """
        rhs = formula.rhs
        if not rhs or rhs.strip().upper() in {"NAN", "NAN;"}:
            return float("nan")

        expr = preprocess_rhs(rhs)
        ns = self.build_namespace(store, step_time=step_time)

        try:
            result = eval(expr, {"__builtins__": {}}, ns)  # noqa: S307
            self.executed_lhs.add(formula.lhs)
            return result
        except NameError as exc:
            err = (
                f"Formula '{formula.lhs}' (id={formula.formula_id}) "
                f"references an unresolved name: {exc}. "
                "Add the missing variable to the initial state, static params, "
                "or implement an explicit helper."
            )
            self.unsupported[formula.lhs] = err
            raise UnsupportedFormulaError(err) from exc
        except ZeroDivisionError as exc:
            err = (
                f"Formula '{formula.lhs}' (id={formula.formula_id}) "
                f"caused a zero-division error: {exc}."
            )
            self.failed[formula.lhs] = err
            raise FormulaEvaluationError(err) from exc
        except Exception as exc:
            err = (
                f"Formula '{formula.lhs}' (id={formula.formula_id}) "
                f"failed during evaluation: {type(exc).__name__}: {exc}. "
                f"RHS after preprocessing: {expr!r}"
            )
            self.failed[formula.lhs] = err
            raise FormulaEvaluationError(err) from exc

    def reset_tracking(self) -> None:
        """Clear execution-tracking sets between runs."""
        self.executed_lhs.clear()
        self.unsupported.clear()
        self.failed.clear()
