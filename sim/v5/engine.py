"""V5 SimulationEngine — staged formula execution backbone.

This module provides :class:`V5SimulationEngine`, which drives the V5
simulation by executing formulas in the stage order defined in
``v5_execution_steps.csv``.

Stage order (from the spec):
    boundary → magnetic → tower_mill → flotation → dcs → lab → label

Special rule for ``y_fx_xin*`` (label-only variables)
-------------------------------------------------------
The V5 spec requires that ``y_fx_xin_s`` and ``y_fx_xin_s_true`` are
generated **only** in the ``label`` step (rule C006 / PR-3 requirement).
These formulas are tagged ``stage=flotation`` in the CSV because they depend
on flotation-stage outputs, but the engine skips them during the flotation
stage and runs them explicitly during the label stage.

Usage
-----
    from sim.v5.spec_loader import load_spec
    from sim.v5.engine import V5SimulationEngine, DEFAULT_PARAMS

    registry = load_spec()
    engine = V5SimulationEngine(registry, params=DEFAULT_PARAMS)
    engine.run(n_steps=5)

    b_eff = engine.store.get("B_eff")
"""
from __future__ import annotations

import random as _random_module
import warnings
from typing import Any, Dict, FrozenSet, List, Optional, Set

from sim.v5.execution_scheduler import ExecutionScheduler
from sim.v5.formula_evaluator import (
    FormulaEvaluationError,
    FormulaEvaluator,
    UnsupportedFormulaError,
)
from sim.v5.spec_loader import FormulaRegistry, FormulaRow
from sim.v5.state_store import StateStore


# ---------------------------------------------------------------------------
# Label-only variables (must NOT be computed before the label stage)
# ---------------------------------------------------------------------------

#: Variables that are tagged ``flotation`` in the CSV but must only be
#: executed during the **label** stage (C006 rule).
LABEL_ONLY_LHS: FrozenSet[str] = frozenset({"y_fx_xin_s", "y_fx_xin_s_true"})

# ---------------------------------------------------------------------------
# Minimal default parameter set
# ---------------------------------------------------------------------------

#: A minimal set of parameter defaults that allows the engine to run small
#: test simulations.  These cover:
#:
#: * Global constants (``eps``, ``dt``).
#: * Magnetic stage promoted formulas (B_eff, capture_j, E_pulse, …).
#: * Boundary stage key variables (M_wet_i, C_i, …).
#: * Tower-mill pool variables.
#: * Flotation stage minimum (feed rates, reagent, …).
#: * Lab sampling parameters.
#: * Label variables (y_fx_xin precursor).
DEFAULT_PARAMS: Dict[str, Any] = {
    # -----------------------------------------------------------------------
    # Global constants
    # -----------------------------------------------------------------------
    "eps": 1e-10,
    "dt": 60.0,
    "pi": 3.141592653589793,

    # -----------------------------------------------------------------------
    # Boundary stage — feed line parameters (3 lines: i=1,2,3 or 1,2,3)
    # -----------------------------------------------------------------------
    "M_nom_1": 265.0, "M_nom_2": 265.0, "M_nom_3": 265.0,
    "M_nom_i": 265.0,
    "M_wet_1": 265.0, "M_wet_2": 265.0, "M_wet_3": 265.0,
    "M_wet_i": 265.0,
    "M_min_i": 200.0, "M_max_i": 300.0,
    "availability_i": 1.0,
    "availability_iin{0,1},i": 1.0,
    "xi_common": 0.0, "xi_i": 0.0,
    "C_nom": 0.37, "k_load_C": 0.001,
    "k_clay_C": 0.01,
    "clay_i": 0.05, "clay_1": 0.05, "clay_2": 0.05, "clay_3": 0.05,
    "xi_C_i": 0.0,
    "C_min": 0.25, "C_max": 0.45,
    "G_base_i": 0.315, "G_base_1": 0.315, "G_base_2": 0.315, "G_base_3": 0.315,
    "k_mag_G": 0.1, "k_clay_G": -0.02, "xi_G_i": 0.0,
    "G_min": 0.28, "G_max": 0.38,
    "r_mag_i": 0.65, "r_mag_1": 0.65, "r_mag_2": 0.65, "r_mag_3": 0.65,
    "r_mag_ref": 0.65,
    "r_hem_i": 0.10, "r_hem_1": 0.10, "r_hem_2": 0.10, "r_hem_3": 0.10,
    "r_carb_i": 0.05, "r_carb_1": 0.05, "r_carb_2": 0.05, "r_carb_3": 0.05,
    "r_sil_i": 0.20, "r_sil_1": 0.20, "r_sil_2": 0.20, "r_sil_3": 0.20,
    "TFe_i": 0.315, "TFe_1": 0.315, "TFe_2": 0.315, "TFe_3": 0.315,
    "rho_fe_mag": 5.17, "rho_fe_hem": 5.26, "rho_fe_carb": 3.96, "rho_fe_sil": 3.50,
    "rho_gangue": 2.65,
    "d80_i": 0.074, "d80_1": 0.074, "d80_2": 0.074, "d80_3": 0.074,
    "n_rr": 0.8,
    "L0_fe": 0.60, "k_L_wi": 0.10, "WI_i": 15.0, "WI_ref": 15.0,
    "k_L_size": 0.05, "k_L_clay": -0.08,
    "L0_gangue": 0.55, "k_Lg_wi": 0.08, "k_Lg_size": 0.04,
    "T_amb": 20.0, "k_ore_temp": 0.5, "T_ore_feed": 20.0,
    "k_water_temp": 0.5, "T_process_water": 18.0,
    "Cp_slurry_i": 3500.0, "Cp_slurry_1": 3500.0, "Cp_slurry_2": 3500.0, "Cp_slurry_3": 3500.0,
    "water_pressure": 0.40,
    "k_feo_mag": 0.31, "k_feo_carb": 0.48, "k_feo_hem": 0.10,
    "WI_1": 15.0, "WI_2": 15.0, "WI_3": 15.0, "WI_i": 15.0,
    "logit": 0.0,  # placeholder for F200 formula
    "e": 2.718281828,

    # -----------------------------------------------------------------------
    # Magnetic stage — promoted formulas (B_eff, capture_j, etc.)
    # -----------------------------------------------------------------------
    # B_eff
    "B_max": 1.50,
    "I_exc": 10.0,
    "I_exc_prev": 10.0,
    "I_exc_sp": 10.0,
    "I_ref": 5.0,
    "T_coil": 25.0,
    "T_coil_prev": 25.0,
    "T_coil_ss": 25.0,
    "tau_coil": 300.0,

    # capture_j
    "a0_j": 0.50,
    "aB_j": 0.30,
    "B_ref": 1.0,
    "aL_j": 0.20,
    "Liberation_j": 0.80,
    "L_ref": 0.50,
    "aSize_j": 0.10,
    "F200": 0.75,
    "F200_ref": 0.70,
    "aC_j": 0.10,
    "C": 0.37,
    "C_ref": 0.37,
    "aQ_j": 0.05,
    "Q_feed": 100.0,
    "Q_ref": 100.0,

    # E_pulse
    "f_pul": 60.0,
    "f_pul_prev": 60.0,
    "f_pul_sp": 60.0,
    "f_pul_opt": 60.0,
    "sigma_pul": 10.0,
    "tau_pul_act": 30.0,
    "f_pul_nom": 60.0,
    "Kcoarse_pul": 0.0, "Kclay_pul": 0.0, "Kslime_pul": 0.0,
    "F325": 0.70,
    "F325_mixed": 0.70,

    # E_ring
    "f_ring": 2.0,
    "f_ring_prev": 2.0,
    "f_ring_sp": 2.0,
    "f_ring_opt": 2.0,
    "sigma_ring": 0.5,
    "k_clog": 0.10,
    "matrix_clog": 0.0,
    "matrix_clog_prev": 0.0,
    "tau_ring_act": 30.0,
    "f_ring_nom": 2.0,
    "Kclog_ring": 0.0, "Kcoarse_ring": 0.0,
    "Kclog_ring_I": 0.0,
    "I0_ring": 5.0, "kf_ring": 0.01, "krho_ring": 0.01,

    # E_level
    "L_mag": 0.5,
    "sigma_L": 0.20,
    "L_mag_sp": 0.5,

    # Entr
    "e0": 0.05,
    "eC": 0.01,
    "ef25": 0.01,
    "f25": 0.30,
    "eclay": 0.01,
    "clay": 0.05,
    "eL": 0.01,
    "e_pul": 0.001,
    "f_pul_min": 30.0,
    "f_pul_ref": 60.0,
    "e_max": 0.30,

    # R_hm_j
    "Rmax_j": 0.95,

    # conc_j, tail_j
    "feed_j": 50.0,
    "Gangue": 100.0,
    "entr_share_j": 0.20,

    # Other magnetic parameters
    "Q_feed_water": 30.0,
    "k_w0": 0.15, "k_w_clog": 0.05,
    "Q_conc_water": 5.0,
    "c0": 0.01, "c_clay": 0.1, "c_f25": 0.05, "c_C": 0.02, "c_load": 0.01, "Q_ref_clog": 100.0,
    "c_flush_Q": 0.02, "Q_flush_prev": 5.0, "Q_flush_ref": 5.0,
    "c_pul_clog": -0.01,
    "I_nom": 10.0, "Kdiff_I": 0.1, "Kmag_I": 0.1, "r_mag": 0.65, "r_mag_ref_ctrl": 0.65,
    "I_exc_max": 20.0, "I_exc_min": 0.0,
    "tau_exc_act": 10.0,
    "A_mag": 0.5,
    "Q_tail_1": 40.0, "Q_tail_2": 20.0,
    "Cv_tail1": 0.1, "Cv_tail2": 0.1,
    "u_tail": 0.5, "u_tail_prev": 0.5,
    "u_tail_2": 0.5, "u_tail_2_prev": 0.5,
    "u_tail_total_sp": 0.5,
    "split_tail_1": 0.6, "split_tail_1_prev": 0.6, "split_tail_1_nom": 0.6,
    "K_asym_tail": 0.0, "matrix_clog_ref": 0.0,
    "Cv_flush": 0.05, "u_flush": 0.5, "u_flush_prev": 0.5, "u_flush_sp": 0.5,
    "tau_flush_valve": 5.0, "u_flush_nom": 0.5,
    "Kclog_flush_u": 0.0, "Kload_flush_u": 0.0,
    "N_flush_base": 1.0, "Kclog_flush_N": 0.0, "Kload_flush_N": 0.0, "N_flush_max": 4.0,
    "tau_tail_valve": 10.0, "K_L_tail": 0.5,
    "u_tail_nom": 0.5, "u_tail_1_sp": 0.5,
    "tau_tail_valve_2": 10.0, "u_tail_2_sp": 0.5,
    "u_tail_max": 1.0, "u_tail_min": 0.0,
    "specific_gravity": 1.4,
    "rho_water": 1000.0, "rho_slurry": 1400.0,
    "w_low_mag": 0.5, "w_low_lib": 0.5, "Liberation": 0.8,
    "u_bd_nom": 0.3, "Kclog_bd": 0.1, "Ktimer_bd": 0.0, "event_bd_timer": 0.0,
    "magnetic_difficulty": 0.0,
    "R0_coil": 0.5, "alpha_Cu": 0.004, "T_ref": 25.0,
    "k_loss_coil": 0.01, "k_cool_coil": 0.001,
    "k_pipe_cooling": 0.01,
    "grid_voltage": 380.0, "k_drop_ring": 0.1,
    "I0_ring": 5.0,
    "Kflow_flush": 0.0, "Kload_flush_sp": 0.0,
    "Kload_ring_sp": 0.0,
    "M_conc_solid": 0.0,  # init, will be computed
    "Q_conc": 0.0,        # init
    "Q_tail": 0.0,        # init
    "P_coil_loss": 0.0,   # init
    "Q_cooling_water": 0.01,
    "Q_flush": 0.0,       # init
    "N_flush_open": 1.0,  # init
    "P_flush_phys": 0.40,
    "V_exc_phys": 5.0,
    "R_coil": 0.5,
    "agg_mag_level": 0.5,
    "k_flush_Q": 0.01, "k_flush_open": 0.01,
    "u_blowdown_phys": 0.3,
    "tau_exc_act": 10.0,
    "Liberation_mixed": 0.80,
    "Liberation_fe_mixed": 0.80,
    "Liberation_gangue_mixed": 0.55,

    # -----------------------------------------------------------------------
    # Tower mill stage
    # -----------------------------------------------------------------------
    "C_feed_prev": 0.37,
    "tau_cyc_pool": 120.0,
    "C_feed_in": 0.37,
    "M_mag_conc_solid": 50.0,
    "M_tm_discharge_solid_prev": 30.0,
    "M_mag_conc_wet": 100.0,
    "M_tm_discharge_wet_prev": 80.0,
    "M_water_add": 20.0,
    "M_sand": 100.0,
    "M_mill_water_in": 30.0,
    "P_mech": 1000.0,
    "WI_mill": 15.0,
    "kE": 0.1, "k_over": 0.02,
    "F325_discharge_prev": 0.70,
    "F325_discharge_inst": 0.70,
    "tau_mill_residence": 600.0,
    "F325_feed_prev": 0.65,
    "F325_feed_in": 0.65,
    "F325_mag_conc": 0.65,
    "F325_discharge": 0.70,
    "k_fine_enrich": 1.10, "alpha_ov": 0.30,
    "F325_feed": 0.65,
    "F325_sand": 0.60,
    "F325_overflow": 0.80,
    "f_ov_pump_sp": 50.0,
    "I0_ov": 2.0, "kf_ov": 0.001, "kQ_ov": 0.01, "krho_ov": 0.001,
    "Q_ov_pump": 50.0, "rho_overflow": 1300.0,
    "f_pump": 50.0, "I0_pump": 5.0, "kf_pump": 0.002, "kQ_pump": 0.01,
    "krho_pump": 0.001, "kmu_pump": 0.001,
    "Q_pump": 80.0, "rho_feed": 1400.0, "mu_slurry": 0.002,
    "V_motor": 380.0, "pf": 0.85, "eta": 0.88,
    "Liberation_fe_discharge_prev": 0.70,
    "Liberation_fe_discharge_inst": 0.70,
    "Liberation_fe_feed_prev": 0.65,
    "Liberation_fe_feed_in": 0.65,
    "Liberation_fe_mag_conc": 0.65,
    "Liberation_fe_discharge": 0.70,
    "Liberation_fe_sand": 0.65,
    "Liberation_fe_overflow": 0.75,
    "Liberation_fe_feed": 0.65,
    "liberation_exponent": 0.5, "k_lib_fe": 0.1, "k_lib_fe_enrich": 1.05,
    "Liberation_gangue_discharge_prev": 0.55,
    "Liberation_gangue_discharge_inst": 0.55,
    "Liberation_gangue_feed_prev": 0.50,
    "Liberation_gangue_feed_in": 0.50,
    "Liberation_gangue_mag_conc": 0.50,
    "Liberation_gangue_discharge": 0.55,
    "Liberation_gangue_sand": 0.50,
    "Liberation_gangue_overflow": 0.60,
    "Liberation_gangue_feed": 0.50,
    "k_lib_gangue": 0.08, "k_lib_gangue_enrich": 1.03,
    "tau_cyc_pool": 120.0,
    "Q_pump_pool_s_1": 80.0, "Q_pump_pool_s_2": 80.0, "Q_pump_pool_s_3": 80.0,
    "Q_pump_pool_{s,1}": 80.0, "Q_pump_pool_{s,2}": 80.0, "Q_pump_pool_{s,3}": 80.0,
    "rho_solid_mix": 4.5,
    "rho_slurry": 1400.0,

    # -----------------------------------------------------------------------
    # Flotation stage — minimal defaults
    # -----------------------------------------------------------------------
    "Q_total_s": 100.0,
    "Q_feed_s": 100.0,
    "Q_feed_s_prev": 100.0,
    "feed_grade_j_s": 0.37,
    "final_conc_s": 0.65,
    "M_NT_in_solid_s": 100.0, "M_NT_ref": 100.0,
    "L_NT_s": 0.5, "L_NT_ref": 0.5,
    "C_NT_nom": 0.45, "Kbed_NT": 0.1, "Kload_NT": 0.01, "C_NT_max": 0.60, "C_NT_min": 0.30,
    "C_under_sp_s": 0.45,
    "C_under_s_prev": 0.45,
    "tau_NT_C": 120.0,
    "k_cao_ca": 0.01,
    "dose_cao_kg_t_s": 0.5,
    "P_amb_pressure": 0.1,
    "P_blower_pressure_b": 0.15,
    "DeltaP_blower_Pa_b": 5000.0,
    "k1_c": 0.5, "k2_c": 0.5,
    "Q_air_low_c": 10.0, "Q_air_high_c": 30.0,
    "Q_air_{s,c}": 20.0,
    "dose_collector_{s,c}": 5.0,
    "dose_depressant_{s,c}": 3.0,
    "dose_frother_{s,c}": 2.0,
    "h0": 0.10, "h_lib": 0.10, "h_sil": 0.05, "h_carb": 0.05,
    "Liberation_gangue": 0.55,
    "r_sil": 0.20, "r_carb": 0.05,
    "h_clay": -0.02,
    "b0": 0.50, "b_carb": 0.02, "b_sil": 0.01, "b_clay": -0.01, "b_C": 0.05,
    "b_f25": 0.02,
    "mu_water": 0.001,
    "k_C_mu": 2.5, "k_clay_mu": 0.5,
    "rho_water": 1000.0,
    "I_FXJ0": 22.0, "C_v_lv": 0.21,
    "P_blower_b": 1000.0,
    "quality_proxy_s": 0.60,  # init

    # -----------------------------------------------------------------------
    # DCS stage
    # -----------------------------------------------------------------------
    "froth_h_{s,c}": 0.15,
    "event_froth_fault_{s,c}": 0.0,
    "fx_s{s}_{c}_froth_h": 0.0,  # init
    # DCS proxy lag inputs (needed by online_froth_proxy and online_load_proxy)
    "froth_h_lag": 0.15,
    "air_flow_lag": 20.0,
    "reagent_freq_lag": 5.0,
    "tm_motor_current_lag": 22.0,
    "cyclone_pressure_lag": 0.12,
    "feed_flow_lag": 265.0,
    "fault_value": 0.0,
    "h_froth_{s,c}": 0.15,

    # -----------------------------------------------------------------------
    # Lab stage
    # -----------------------------------------------------------------------
    "_x_tm_overflow_tfe": 0.60,
    "sample_time_tm_overflow_tfe": 0.0,
    "report_time_tm_overflow_tfe": 0.0,
    "sigma_sampling_tm": 0.001,
    "sigma_assay_tfe": 0.001,
    "_x_mag_mixed_conc_tfe": 0.65,
    "sample_time_mag_mixed_conc_tfe": 0.0,
    "report_time_mag_mixed_conc_tfe": 0.0,
    "sigma_sampling_mag": 0.001,

    # -----------------------------------------------------------------------
    # Label stage / y_fx_xin
    # -----------------------------------------------------------------------
    "sigma_y": 0.005,
    # y_fx_xin_s_true = TFe(final_conc_s) — final_conc_s already set above

    # -----------------------------------------------------------------------
    # quality_proxy helpers
    # -----------------------------------------------------------------------
    "w_tm_lab": 0.5,
    "w_mag_lab": 0.5,
    "lab_tm_overflow_tfe": float("nan"),  # init NaN (will be set by lab stage)
    "lab_mag_mixed_conc_tfe": float("nan"),

    # -----------------------------------------------------------------------
    # Misc parameters used by many formulas
    # -----------------------------------------------------------------------
    "sigma_tfe_pct": 0.16,
    "sigma_f200_pct": 0.70,
    "_x_eryi_line": 0.315,
    "_tfe": 0.315,
    "_f200": 0.75,
    "i": 1,  # template index default
    "sigma_f200": 0.005,
}


# ---------------------------------------------------------------------------
# V5SimulationEngine
# ---------------------------------------------------------------------------


class V5SimulationEngine:
    """Staged simulation engine driven by V5 CSV specifications.

    The engine runs the formula execution pipeline defined in
    ``v5_execution_steps.csv``, evaluating each formula via a controlled
    :class:`~sim.v5.formula_evaluator.FormulaEvaluator`.

    Parameters
    ----------
    registry :
        A loaded :class:`~sim.v5.spec_loader.FormulaRegistry`.
    params :
        Static parameter dictionary merged into every formula's eval
        namespace.  Falls back to :data:`DEFAULT_PARAMS` if ``None``.
    dt :
        Simulation time step in seconds (default 60 s).
    rng :
        Optional :class:`random.Random` instance for reproducibility.

    Attributes
    ----------
    store :
        The :class:`~sim.v5.state_store.StateStore` holding simulation state.
    step_count :
        Number of time steps completed.
    step_time :
        Current simulation clock in seconds.
    executed_lhs : set[str]
        LHS names successfully evaluated across all steps.
    skipped : dict[str, str]
        LHS → error message for formulas that could not be evaluated.
    """

    def __init__(
        self,
        registry: FormulaRegistry,
        params: Optional[Dict[str, Any]] = None,
        dt: float = 60.0,
        rng=None,
    ) -> None:
        self._registry = registry
        self._dt = float(dt)
        self._rng = rng

        # Build scheduler
        self._scheduler = ExecutionScheduler(registry)

        # Build evaluator
        merged_params = dict(DEFAULT_PARAMS)
        if params:
            merged_params.update(params)
        merged_params["dt"] = self._dt
        self._evaluator = FormulaEvaluator(params=merged_params, dt=self._dt, rng=rng)

        # State
        self.store = StateStore()
        self.step_count: int = 0
        self.step_time: float = 0.0

        # Tracking
        self.executed_lhs: Set[str] = set()
        self.skipped: Dict[str, str] = {}

        # Pre-fetch label-only formulas (tagged flotation in CSV but label-only).
        # Sort so y_fx_xin_s_true comes before y_fx_xin_s (dependency order).
        _label_candidates = [
            f for f in self._scheduler.formulas_for_stage("flotation")
            if f.lhs in LABEL_ONLY_LHS
        ]
        self._label_formulas: List[FormulaRow] = sorted(
            _label_candidates,
            key=lambda f: (0 if f.lhs == "y_fx_xin_s_true" else 1),
        )

        # Stage output tracking: set per-stage after each step
        self._stage_outputs: Dict[str, Set[str]] = {
            stage: set() for stage in self._scheduler.ordered_stages()
        }

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self, state: Dict[str, Any]) -> None:
        """Populate the StateStore with initial values.

        Parameters
        ----------
        state :
            Dictionary of variable name → initial value.  This is applied
            to the *current* step buffer so formulas can reference these
            values in the first step.
        """
        for k, v in state.items():
            self.store.set(k, v)

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def step(self) -> None:
        """Execute one simulation time step.

        1. Advance the StateStore (current → previous, clear current).
        2. Increment time counters.
        3. Execute each stage in order.
        """
        self.store.advance()
        self.step_count += 1
        self.step_time += self._dt

        for stage in self._scheduler.ordered_stages():
            self._run_stage(stage)

    def run(self, n_steps: int) -> None:
        """Execute *n_steps* consecutive simulation time steps.

        Parameters
        ----------
        n_steps :
            Number of steps to execute (must be ≥ 1).

        Warns
        -----
        RuntimeWarning
            Emitted after all steps complete if any formulas were skipped
            (i.e. could not be evaluated).  Inspect :attr:`skipped` for
            details.  The engine does not raise because some formulas are
            skeleton stubs that are intentionally unsupported at this stage.
        """
        for _ in range(n_steps):
            self.step()

        if self.skipped:
            # Distinguish expected template-placeholder skips (un-expanded
            # index subscripts like {s,c}) from unexpected runtime failures.
            # Only warn about unexpected failures to keep the signal meaningful.
            unexpected = {
                lhs: msg
                for lhs, msg in self.skipped.items()
                if "template placeholder" not in msg
            }
            template_count = len(self.skipped) - len(unexpected)
            if unexpected:
                warnings.warn(
                    f"V5SimulationEngine: {len(unexpected)} formula(s) could not be "
                    f"evaluated and were skipped (executed={len(self.executed_lhs)}, "
                    f"template_placeholders={template_count}). "
                    "Call engine.run_summary() for details.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            elif template_count:
                # All skips are expected template stubs — no warning needed,
                # but the information remains accessible via run_summary().
                pass

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def _run_stage(self, stage: str) -> None:
        """Dispatch formula execution for *stage*."""
        if stage == "label":
            self._run_label_stage()
            return

        formulas = self._scheduler.formulas_for_stage(stage)
        for formula in formulas:
            # Skip label-only vars in non-label stages (C006 rule)
            if formula.lhs in LABEL_ONLY_LHS:
                continue
            result = self._eval_and_store(formula)
            if result is not None:
                self._stage_outputs[stage].add(formula.lhs)

    def _run_label_stage(self) -> None:
        """Execute the label stage: only LABEL_ONLY_LHS formulas.

        ``y_fx_xin_s_true`` and ``y_fx_xin_s`` are tagged ``flotation`` in
        the CSV but are deliberately deferred to the label stage so they
        are never computed before the final concentrate streams are known.
        """
        for formula in self._label_formulas:
            result = self._eval_and_store(formula)
            if result is not None:
                self._stage_outputs["label"].add(formula.lhs)

    def _eval_and_store(self, formula: FormulaRow) -> Optional[Any]:
        """Evaluate *formula* and write the result to the state store.

        Returns the computed value on success, ``None`` on failure.
        Failures are recorded in :attr:`skipped` — they are **not** silently
        discarded.
        """
        try:
            result = self._evaluator.eval_formula(
                formula, self.store, step_time=self.step_time
            )
            if result is None:
                # A formula that returns Python None produced no output value.
                # Record it as skipped so callers can detect the gap instead of
                # silently losing the variable from the state store.
                self.skipped.setdefault(
                    formula.lhs,
                    "FormulaEvaluationError: formula returned None (no output produced)",
                )
                return None
            self.store.set(formula.lhs, result)
            self.executed_lhs.add(formula.lhs)
            return result
        except UnsupportedFormulaError as exc:
            # Explicit unsupported helper — logged, not silently skipped
            self.skipped[formula.lhs] = f"UnsupportedFormulaError: {exc}"
            return None
        except FormulaEvaluationError as exc:
            # Runtime error — logged, not silently skipped
            self.skipped[formula.lhs] = f"FormulaEvaluationError: {exc}"
            return None

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def stage_outputs(self, stage: str) -> Set[str]:
        """Return the set of LHS names updated in *stage* so far."""
        return frozenset(self._stage_outputs.get(stage, set()))

    def all_stage_names(self) -> List[str]:
        """Return ordered stage names from the scheduler."""
        return self._scheduler.ordered_stages()

    def manual_promoted_lhs(self) -> List[str]:
        """Return LHS names of all manual_promoted formulas in the registry."""
        return [
            f.lhs
            for f in self._registry.formulas
            if f.status == "manual_promoted"
        ]

    @property
    def skipped_count(self) -> int:
        """Number of formulas that could not be evaluated."""
        return len(self.skipped)

    def run_summary(self) -> str:
        """Return a human-readable execution summary string.

        Reports counts of executed vs skipped formulas, and a breakdown of
        skipped reasons (UnsupportedFormulaError vs FormulaEvaluationError).

        Returns
        -------
        str
            Multi-line summary text, suitable for printing or logging.
        """
        total = len(self.executed_lhs) + len(self.skipped)
        lines = [
            f"V5SimulationEngine run summary (step_count={self.step_count})",
            f"  executed : {len(self.executed_lhs)} / {total}",
            f"  skipped  : {len(self.skipped)} / {total}",
        ]
        if self.skipped:
            unsupported = sum(
                1 for v in self.skipped.values() if v.startswith("UnsupportedFormulaError")
            )
            eval_err = sum(
                1 for v in self.skipped.values() if v.startswith("FormulaEvaluationError")
            )
            lines.append(f"    └─ UnsupportedFormulaError : {unsupported}")
            lines.append(f"    └─ FormulaEvaluationError  : {eval_err}")
        return "\n".join(lines)
