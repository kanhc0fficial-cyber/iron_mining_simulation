# Phase 5 calibration and leakage check log

Date: 2026-05-14

## Scope

Implemented reusable calibration/leakage diagnostics for exported simulation data.

This phase follows the `DESIGN_V2_COMPLETE.md` stage-5 requirement:

- `corr(DCS(t), y(t))`
- `corr(DCS(t-lag), y(t))`
- single-variable model R2
- multivariable time-window model R2
- `lab_*` to `y` relationship
- upstream response-lag checks

## Code added

- `sim/validation/leakage.py`
  - `default_dcs_columns`: excludes `y_*`, `lab_*`, and hidden `_x_*`.
  - `lagged_correlations`: computes `corr(feature(t-lag), target(t))`.
  - `time_split_linear_r2`: fits a time-split ridge/linear model and reports test R2.
  - `build_leakage_summary`: builds the standard Phase-5 report.
  - `estimate_response_lag`: estimates the best response lag between cause/effect signals.
- `scripts/leakage_check.py`
  - CLI for running the report against exported `.parquet` or `.csv` data.
- `tests/test_validation.py`
  - synthetic tests for DCS/lab exclusion, response-lag detection, window-model improvement, and direct-proxy detection.

## Current open-loop baseline

Command:

```text
python scripts/leakage_check.py --input /tmp/test_open_loop.parquet --target y_fx_xin1 --top 8
```

Result:

- Max single-feature R2: `0.0545`
- Instant multivariate R2: `0.1107`
- Window multivariate R2: `0.1276`
- Window gain: `0.0170`
- Strongest DCS correlations are reagent-frequency/current columns, all with absolute correlation near `0.23`.
- No single DCS column currently behaves like a direct final-grade proxy.

The time-window gain is positive but modest. That is acceptable for the current G1 baseline, but it also shows a future calibration target: upstream ore/mineralogy disturbances should produce a clearer delayed signature once the process-lab sampler and more deliberate excitation scenarios are added.

## Notes

- The checker is read-only and does not feed any result back into mechanism formulas.
- `lab_*` variables are intentionally reported separately from DCS columns. Current internal process-lab coverage is still incomplete beyond the entrance boundary samples; adding full magnetic/tower/flotation process-lab outputs should be a separate follow-up phase rather than hard-coding unconfirmed sample points.
- The CLI can be used with `--check --max-single-r2 0.95` to fail a run when a single DCS feature becomes suspiciously predictive.

## Verification

- `pytest tests/test_validation.py -q`: 4 passed.
- `pytest -q`: 86 passed, 7 warnings.

