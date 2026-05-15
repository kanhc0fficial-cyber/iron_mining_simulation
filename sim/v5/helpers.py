"""Core helper functions for V5 formula evaluation.

These helpers are injected into the eval() namespace used by
:class:`~sim.v5.formula_evaluator.FormulaEvaluator` when it interprets
formula RHS strings from ``v5_executable_formulas.csv``.

All functions are intentionally kept pure (no state side-effects) so they
can be used safely inside a controlled eval() namespace.
"""
from __future__ import annotations

import math
import random as _random_module
from typing import Any, Union

_EPS = 1e-10

# ---------------------------------------------------------------------------
# Basic math helpers
# ---------------------------------------------------------------------------


def clip(val: float, lo: float, hi: float) -> float:
    """Clip *val* to the closed interval [*lo*, *hi*]."""
    return max(float(lo), min(float(hi), float(val)))


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    x = float(x)
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def safe_log(x: float, eps: float = _EPS) -> float:
    """Natural log with a floor at *eps* to avoid domain errors."""
    return math.log(max(float(x), eps))


def safe_log1p(x: float, eps: float = _EPS) -> float:
    """log1p with a floor so the argument stays > -1."""
    return math.log1p(max(float(x), -1.0 + eps))


def safe_sqrt(x: float) -> float:
    """Square root that clamps negative arguments to zero."""
    return math.sqrt(max(float(x), 0.0))


def safe_exp(x: float, x_max: float = 500.0) -> float:
    """exp() with argument clipped to avoid overflow."""
    return math.exp(min(float(x), x_max))


# ---------------------------------------------------------------------------
# Thermal derating
# ---------------------------------------------------------------------------


def thermal_derate(T: float, T_ref: float = 50.0, alpha: float = 0.002) -> float:
    """Thermal derating factor.

    Returns ``clip(1 - alpha*(T - T_ref), 0.5, 1.0)`` so that at nominal
    temperature the factor is 1.0 and it degrades linearly with heat.

    This is the helper called in the B_eff formula:
    ``B_eff = B_max*(1-exp(-I_exc/I_ref))*thermal_derate(T_coil)``
    """
    return clip(1.0 - alpha * max(0.0, float(T) - T_ref), 0.5, 1.0)


# ---------------------------------------------------------------------------
# Measurement passthrough and realistic sensor model
# ---------------------------------------------------------------------------


def meas(val: Any) -> float:
    """DCS measurement passthrough.

    Returns *val* as a float.  In the full simulation a small sensor noise
    would be added; for the V5 engine skeleton this is a clean passthrough.
    """
    if val is None:
        return float("nan")
    return float(val)


def meas_sensor(
    val: Any,
    *,
    sigma_noise: float = 0.0,
    drift_rate: float = 0.0,
    drift_time: float = 0.0,
    clip_lo: float = float("-inf"),
    clip_hi: float = float("inf"),
    fault_active: bool = False,
    fault_value: float = float("nan"),
    rng=None,
) -> float:
    """Realistic DCS sensor model: noise + drift + clipping + fault window.

    This is the full-featured measurement function used when a DCS point needs
    more than a clean passthrough.  It implements PR-4 requirement: *"支持
    meas(…): 噪声、漂移、clipping、missing/fault window"*.

    Parameters
    ----------
    val :
        True physical value.  ``None`` maps to NaN.
    sigma_noise :
        Standard deviation of zero-mean Gaussian measurement noise.
        Set to 0 (default) to disable noise.
    drift_rate :
        Bias drift per second.  A positive value means the sensor over-reads
        linearly with time.
    drift_time :
        Cumulative elapsed simulation time in seconds used to compute the
        drift offset: ``drift_offset = drift_rate * drift_time``.
    clip_lo :
        Lower saturation limit.  Values below this are clamped.
    clip_hi :
        Upper saturation limit.  Values above this are clamped.
    fault_active :
        When ``True`` the sensor is in a fault window and ``fault_value`` is
        returned unconditionally (missing/stuck/fault injection).
    fault_value :
        Value returned during a fault window.  ``float("nan")`` models a
        missing/off-line sensor (default).
    rng :
        Optional :class:`random.Random` instance for reproducibility.

    Returns
    -------
    float
        Measured value after noise, drift, clipping, and fault processing.
    """
    if fault_active:
        return float(fault_value)

    if val is None:
        return float("nan")

    measured = float(val)

    # Add drift offset
    measured += drift_rate * drift_time

    # Add Gaussian noise
    if sigma_noise != 0.0:
        _rng = rng if rng is not None else _random_module
        measured += _rng.gauss(0.0, float(sigma_noise))

    # Clipping / saturation
    if not math.isnan(measured):
        measured = max(float(clip_lo), min(float(clip_hi), measured))

    return measured


# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


def noise(mu: float = 0.0, sigma: float = 0.0, rng=None) -> float:
    """Gaussian noise helper — replaces ``N(mu, sigma)`` in formula RHS.

    Parameters
    ----------
    mu :
        Mean of the distribution (usually 0).
    sigma :
        Standard deviation.
    rng :
        Optional :class:`random.Random` instance for reproducibility.
        Defaults to the module-level ``random`` instance.
    """
    if sigma == 0.0:
        return float(mu)
    _rng = rng if rng is not None else _random_module
    return float(mu) + _rng.gauss(0.0, float(sigma))


# ---------------------------------------------------------------------------
# Forward-fill for lab reports
# ---------------------------------------------------------------------------


def ffill_reported(val: Any) -> float:
    """Forward-fill for lab-reported values.

    Returns *val* if it is a valid number, otherwise returns ``NaN``.
    Consumers (e.g. quality_proxy_s) should treat ``NaN`` as "not yet
    available" and carry forward the last valid value at the call site.
    """
    if val is None:
        return float("nan")
    fval = float(val)
    if math.isnan(fval):
        return float("nan")
    return fval


# ---------------------------------------------------------------------------
# Lab sample template
# ---------------------------------------------------------------------------


def lab_sample_template(
    x_val: float,
    sample_time: float,
    report_time: float,
    sigma_sampling: float,
    sigma_assay: float,
    *,
    step_time: float = 0.0,
    rng=None,
) -> float:
    """Generate a lab sample result.

    Returns the sample result ``100*x_val + N(0, sigma_sampling) +
    N(0, sigma_assay)`` once *step_time* >= *report_time*.  Returns ``NaN``
    if the result is not yet available.

    Parameters
    ----------
    x_val :
        True process value at the sampling point (e.g. true TFe fraction).
    sample_time :
        Simulation time at which the sample was taken.
    report_time :
        Simulation time at which the result is available.
    sigma_sampling :
        Sampling error standard deviation (in the same units as the
        reported value, i.e. percentage points when x_val is 0–1 scale).
    sigma_assay :
        Assay / measurement error standard deviation.
    step_time :
        Current simulation time (keyword-only).  Defaults to 0 so the
        sample is available immediately in simplified test scenarios.
    rng :
        Optional :class:`random.Random` instance.
    """
    if float(step_time) < float(report_time):
        return float("nan")
    _rng = rng if rng is not None else _random_module
    n_s = _rng.gauss(0.0, float(sigma_sampling)) if sigma_sampling else 0.0
    n_a = _rng.gauss(0.0, float(sigma_assay)) if sigma_assay else 0.0
    return 100.0 * float(x_val) + n_s + n_a


# ---------------------------------------------------------------------------
# Topology helper for flotation feed rates
# ---------------------------------------------------------------------------


def topology_feed_j_rate(
    stage_index: int,
    series: int,
    Q_feed_s: float,
    feed_grade_j_s: float,
    **kwargs: Any,
) -> float:
    """Compute the feed mass flow of component j into a flotation stage.

    .. todo::
        **BUG-PR9-F / Stub** — current implementation is a scalar approximation
        that ignores cell-to-cell cascade relationships.

        The full V5 spec requires a cascade model where each cell's inflow equals
        the previous cell's outflow:

        .. code-block:: text

            Q_in[0]  = Q_total_s
            Q_in[c]  = Q_out[c-1]   (outflow = inflow - mass floated off)

        Until the cascade model is implemented, all cells receive the same feed
        rate, underestimating the downstream cell depletion.

    Parameters
    ----------
    stage_index :
        Flotation cell index (0-based within the series).
    series :
        Series index (0-based).
    Q_feed_s :
        Total volumetric feed rate to the series (m³/h or t/h).
    feed_grade_j_s :
        Mass fraction of component j in the feed.
    """
    return float(Q_feed_s) * float(feed_grade_j_s)


# ---------------------------------------------------------------------------
# Index-summation helpers
# ---------------------------------------------------------------------------

def sum_j(*args: float) -> float:
    """Sum over j index (mineral components)."""
    return sum(float(a) for a in args)


def sum_c(*args: float) -> float:
    """Sum over c index (flotation cells in a series)."""
    return sum(float(a) for a in args)


def sum_s(*args: float) -> float:
    """Sum over s index (flotation series)."""
    return sum(float(a) for a in args)


def sum_k(*args: float) -> float:
    """Sum over k index (generic)."""
    return sum(float(a) for a in args)


def sum_b(*args: float) -> float:
    """Sum over b index (generic)."""
    return sum(float(a) for a in args)


def sum_i(*args: float) -> float:
    """Sum over i index (feed lines)."""
    return sum(float(a) for a in args)


# ---------------------------------------------------------------------------
# Stream helpers
# ---------------------------------------------------------------------------


def TFe(stream_or_val: Any) -> float:
    """Extract total Fe grade from a stream dict or return the raw float.

    When *stream_or_val* is a ``dict`` the function looks for an
    ``"tfe"`` or ``"TFe"`` key.  When it is a plain float it is returned
    directly (grade already extracted upstream).
    """
    if isinstance(stream_or_val, dict):
        if "tfe" in stream_or_val:
            return float(stream_or_val["tfe"])
        if "TFe" in stream_or_val:
            return float(stream_or_val["TFe"])
        # Compute from components if available
        fe_keys = ("Fe_mag", "Fe_hem", "Fe_carb", "Fe_sil")
        solid_keys = (*fe_keys, "Gangue")
        total_fe = sum(stream_or_val.get(k, 0.0) for k in fe_keys)
        total_solid = sum(stream_or_val.get(k, 0.0) for k in solid_keys)
        if total_solid <= _EPS:
            return 0.0
        return float(total_fe / total_solid)
    return float(stream_or_val)


# ---------------------------------------------------------------------------
# Convenience namespace builder
# ---------------------------------------------------------------------------

def build_helpers_namespace(rng=None) -> dict:
    """Return a dict mapping helper function names to implementations.

    This dict is merged into the eval() namespace before formula RHS
    evaluation so that formula strings such as ``clip(...)``,
    ``sigmoid(...)``, ``lab_sample_template(...)`` resolve correctly.

    Parameters
    ----------
    rng :
        Optional random-number generator.  When supplied, the ``noise``
        helper is wrapped to use *rng* for reproducible runs.
    """
    import math as _math

    def _noise(mu=0.0, sigma=0.0):
        return noise(mu, sigma, rng=rng)

    def _lab_sample_template(x_val, sample_time, report_time, sigma_sampling, sigma_assay,
                              step_time=0.0):
        return lab_sample_template(
            x_val, sample_time, report_time, sigma_sampling, sigma_assay,
            step_time=step_time, rng=rng,
        )

    ns: dict = {
        # Math primitives
        "abs": abs,
        "round": round,
        "max": max,
        "min": min,
        "exp": safe_exp,
        "log": safe_log,
        "log1p": safe_log1p,
        "sqrt": safe_sqrt,
        "pi": _math.pi,
        "inf": float("inf"),
        "nan": float("nan"),
        # V5 helpers
        "clip": clip,
        "sigmoid": sigmoid,
        "thermal_derate": thermal_derate,
        "meas": meas,
        "meas_sensor": meas_sensor,
        "N": _noise,
        "noise": _noise,
        "ffill_reported": ffill_reported,
        "lab_sample_template": _lab_sample_template,
        "topology_feed_j_rate": topology_feed_j_rate,
        "TFe": TFe,
        # Index summation
        "sum_j": sum_j,
        "sum_c": sum_c,
        "sum_s": sum_s,
        "sum_k": sum_k,
        "sum_b": sum_b,
        "sum_i": sum_i,
        # sat_act helper (actuator saturation, used in u_actual)
        "sat_act": lambda u_sp, u_min, u_max, tau_act: clip(u_sp, u_min, u_max),
        # integral helper stub (controller integral — returns 0 for skeleton)
        "integral": lambda error: 0.0,
        # Conditional helper: ifelse(condition, true_val, false_val)
        "ifelse": lambda cond, tv, fv: float(tv) if cond else float(fv),
        # standardized helper: placeholder normalization.
        # TODO BUG-PR9-F: returns a simple arithmetic mean of raw inputs.
        # A production implementation should z-score each input using rolling
        # (or step-initialised) statistics so that signals with different
        # physical units are properly normalised before aggregation.
        # Until fixed, online_froth_proxy / online_load_proxy outputs are
        # dimensionally inconsistent (different units mixed into one average).
        "standardized": lambda *args: sum(float(a) for a in args) / max(len(args), 1),
        # logit helper (used in F200_i formula)
        "logit": lambda p: safe_log(max(float(p), _EPS) / max(1.0 - float(p), _EPS)),
        # F helper stub for particle-size distribution (Rosin-Rammler)
        "F": lambda d, d80, n: float(1.0 - _math.exp(-(_math.log(2.0) * (float(d) / max(float(d80), _EPS)) ** float(n)))),
    }
    return ns
