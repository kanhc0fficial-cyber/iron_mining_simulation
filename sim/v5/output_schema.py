"""V5 minimal output schema.

Defines the stable column list for the V5 simulation engine's output file.
Only includes variables that the V5SimulationEngine reliably computes
(non-template, concrete names).

Columns are grouped by stage:
  - DCS: magnetic stage (agg_mag_*)
  - DCS: tower-mill stage (agg_tm_*)
  - Lab: lab assay results
  - Label: supervised labels (y_fx_xin*)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Magnetic separation DCS (10 points)
# ---------------------------------------------------------------------------
_MAG_DCS: list[str] = [
    "agg_mag_excit_voltage",
    "agg_mag_excit_current",
    "agg_mag_coil_temp",
    "agg_mag_tailings_valve1",
    "agg_mag_tailings_valve2",
    "agg_mag_blowdown_valve",
    "agg_mag_pulsation_freq",
    "agg_mag_ring_freq",
    "agg_mag_level",
    "agg_mag_flush_water_pressure",
]

# ---------------------------------------------------------------------------
# Tower-mill / cyclone DCS (4 points)
# ---------------------------------------------------------------------------
_TM_DCS: list[str] = [
    "agg_tm_cyclone_feed_flow",
    "agg_tm_cyclone_pump_freq",
    "agg_tm_motor_current",
    "agg_tm_overflow_pump_current",
]

# ---------------------------------------------------------------------------
# Lab assay outputs (instantiated by lab_sample_template)
# ---------------------------------------------------------------------------
_LAB_COLS: list[str] = [
    "lab_tm_overflow_tfe",
    "lab_mag_mixed_conc_tfe",
]

# ---------------------------------------------------------------------------
# Label / supervised target (label stage only — never before flotation)
# ---------------------------------------------------------------------------
_LABEL_COLS: list[str] = [
    "y_fx_xin_s",
    "y_fx_xin_s_true",
]

# ---------------------------------------------------------------------------
# Canonical V5 minimal output column list
# ---------------------------------------------------------------------------
V5_OUTPUT_COLUMNS: list[str] = _MAG_DCS + _TM_DCS + _LAB_COLS + _LABEL_COLS

# Convenience set for fast membership checks
V5_OUTPUT_COLUMNS_SET: frozenset[str] = frozenset(V5_OUTPUT_COLUMNS)
