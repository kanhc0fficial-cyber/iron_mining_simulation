# Process lab sampler completion log

Date: 2026-05-14

## 中文说明

“没有把未确认的 `lab_*` 点位硬凑进来”的意思是：

- 文档明确把 `粗细溢`、`29米*`、`38米` 标为待确认取样口。
- 这些点位没有可靠资料说明它们对应入口边界、塔磨某组旋流器溢流，还是其他现场管线。
- 如果直接拿相近隐藏变量去填这些列，会让数据看起来完整，但实际是在制造错误标签。
- 因此这类点位暂不绑定；后续拿到现场点位映射后再加。

本次已经把资料充分、来源明确的磁选、塔磨、浮选过程化验 sampler 补完。

## Implemented

- Added `ProcessLabConfig`.
- Added `sim/layers/process_lab.py`.
- Added confirmed internal process-lab columns:
  - Magnetic separation: weak mag concentrate/tail, high-intensity concentrate/tail, sweep concentrate/tail, mixed concentrate, tube-test proxy.
  - Tower mill / third classification: feed `-325`, discharge `-325`, overflow `-325`, overflow TFe, overflow concentration, sand `-325`.
  - Flotation: feed TFe/F325, final concentrate/tail TFe, rougher/cleaner/scavenger stage TFe, final concentrate yield and Fe recovery for s1/s2.
- Connected `ProcessLabSampler` after flotation and before writer in `Simulator`.
- Extended `PROCESS_LAB_COLUMNS` so exported parquet/csv contains the new process-lab columns.
- Added tower-mill hidden fields:
  - `_x_tm_discharge_f325`
  - `_x_tm_discharge_d80`
  - `_x_tm_overflow_conc`

## Sampling semantics

- Sampling interval defaults to 30-60 steps.
- At sample time, sampler writes percent-unit lab values with sampling/lab noise.
- Outside sample time, sampler writes `NaN`.
- Sampler only reads hidden `_x_*` states and does not feed back into DCS or mechanism formulas.

## Preview baseline

120-step preview with fixed 30-step process-lab interval:

- `lab_mag_mixed_conc_tfe`: mean about 42.68%.
- `lab_mag_tube_conc_tfe`: mean about 37.66%.
- `lab_tm_overflow_f325`: mean about 93.46%.
- `lab_tm_overflow_tfe`: mean about 42.78%.
- `lab_tm_overflow_conc`: mean about 17.19%.
- `lab_flo_feed_tfe_s1`: mean about 43.78%.
- `lab_flo_conc_tfe_s1`: mean about 67.19%.
- `lab_flo_tail_tfe_s1`: mean about 20.56%.
- `lab_flo_final_conc_yield_s1`: mean about 49.28%.
- `lab_flo_final_conc_recovery_s1`: mean about 76.25%.

## Verification

- `pytest tests/test_process_lab.py -q`: 3 passed.
- `pytest tests/test_integration.py::TestOutputSchema tests/test_integration.py::TestShortRun tests/test_validation.py -q`: 10 passed.
- `pytest -q`: 89 passed, 7 warnings.

