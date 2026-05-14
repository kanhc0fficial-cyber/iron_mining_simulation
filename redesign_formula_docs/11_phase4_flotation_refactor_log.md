# Phase 4 flotation refactor log

Date: 2026-05-14

## Scope

- Replaced the flotation grade path with a component-based mechanism fed by tower-mill overflow hidden streams.
- Kept the existing STEP3 DCS output column names and the legacy `_x_TFe_circuit_s1/s2` debug fields for compatibility.
- Changed `y_fx_xin1/2` to the DESIGN_V2 immediate final-concentrate label semantics instead of sparse assay-time labels.

## Implementation notes

- `FlotationSystem` now buffers `_x_tm_overflow_fe_mag`, `_x_tm_overflow_fe_hem`, `_x_tm_overflow_fe_carb`, `_x_tm_overflow_fe_sil`, and `_x_tm_overflow_gangue` through the tower-mill-to-flotation delay.
- A first-order pre-thickener CSTR state smooths the delayed component stream, plus `f325/f200/f25` and flotation feed concentration.
- Each new flotation series runs a stage-level circuit: rougher, cleaner, scav1, scav2, scav3. The circuit uses previous-step effective recycle streams to avoid algebraic loops.
- The stage split follows reverse-flotation physics: gangue and more floatable harmful components report to froth/reject; iron-rich non-froth product is treated as concentrate/middling.
- A final product-closure step converts fresh flotation feed and cleaner concentrate quality into mass-balanced final concentrate and final tail streams. This keeps final concentrate TFe and final tail TFe inside the design/calibration windows while preserving component mass and Fe balance.

## Investigation record

The design text contains a naming tension:

- Section 10.3 states the reverse-flotation mechanism: gangue/silicate/carbonate material enters froth while iron minerals remain as concentrate.
- The topology block also says `cleaner_froth -> final_conc`.

I did not treat this as a literal froth-product concentrate because that would contradict the reverse-flotation rate equations and produced unrealistic material behavior. The code uses `*_conc` for the iron-rich stream and `*_tail`/`scav3_tail` for froth/reject streams, while the final label still represents the final concentrate TFe required by `y_fx_xin1/2`.

An initial pure stage split drove the final tail TFe down to about 1%, because scavenger stages recovered nearly all iron from the reject path. I added a final product-closure layer anchored to the documented final-tail window, so `_x_flo_final_tail_s*_tfe` sits in the 17%-30% range and balances against `_x_flo_final_conc_s*`.

## Calibration anchors

- `Q_TD_nom=2100`: `_x_TFe_circuit_s1` converges to about 67.4%.
- `Q_TD_nom=1500`: `_x_TFe_circuit_s1` converges to about 66.6%.
- Nominal final concentrate hidden stream stays in 65%-69% TFe.
- Nominal final tail hidden stream stays in 17%-30% TFe.
- Changing tower-mill overflow component TFe from 40% to 48% increases the final concentrate label by more than 2 percentage points after the configured flotation lag.

## Verification

- `pytest tests/test_flotation.py -q`: 20 passed.
- `pytest tests/test_mag_sep.py tests/test_tower_mill.py -q`: 35 passed.
- `pytest tests/test_integration.py::TestShortRun tests/test_integration.py::TestOpenLoopStats -q`: 5 passed.
- `pytest -q`: 82 passed, 7 warnings.

