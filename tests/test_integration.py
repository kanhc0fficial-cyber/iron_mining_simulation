"""
全流程集成测试。

验收标准：
  - 30 天完整仿真（43 200 步）运行时间 < 5 min（单核）
  - 输出 DataFrame 列数 ≥ 200，无缺失列，无 NaN/Inf（除 y_fx_xin1/2 和采样型 lab_* 的 NaN）
  - 开环模式：TFe 方差 ≥ 4.0，均值 ∈ [66, 68] %
  - 传感器故障频率与文档一致（轴承 ≈ 0.2 %，泡沫层 ≈ 0.5 %）
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import (
    SimConfig, DisturbanceConfig, BallMillConfig, MagSepConfig,
    TowerMillConfig, FlotationConfig,
)
from sim.simulator import Simulator
from sim.output.schema import (
    STEP1_COLUMNS, STEP2_COLUMNS, STEP3_COLUMNS, OUTPUT_COLUMNS, PROCESS_LAB_COLUMNS,
)


# ── 辅助：快速运行仿真并返回 DataFrame ──────────────────────────────────

def _run_sim(
    n_steps: int = 43_200,
    open_loop: bool = False,
    seed: int = 42,
    warm_up: bool = True,
    output_path: str = "/tmp/test_integration_out.parquet",
) -> pd.DataFrame:
    sim_cfg = SimConfig(n_steps=n_steps, seed=seed, open_loop=open_loop)
    sim = Simulator(
        sim_cfg=sim_cfg,
        dist_cfg=DisturbanceConfig(),
        ball_cfg=BallMillConfig(),
        mag_cfg=MagSepConfig(),
        tm_cfg=TowerMillConfig(),
        flo_cfg=FlotationConfig(),
        output_path=output_path,
        fmt="parquet",
    )
    if warm_up:
        sim.warm_up()
    sim.run_steps(n_steps)
    return pd.read_parquet(output_path)


# ── 1. 输出 Schema 完整性 ────────────────────────────────────────────────

class TestOutputSchema:

    def test_column_count(self) -> None:
        """OUTPUT_COLUMNS 总列数（不含 t 列）≥ 200。"""
        assert len(OUTPUT_COLUMNS) >= 200, f"列数 = {len(OUTPUT_COLUMNS)}"

    def test_no_duplicate_columns(self) -> None:
        assert len(OUTPUT_COLUMNS) == len(set(OUTPUT_COLUMNS)), "存在重复列名"

    def test_step3_column_count(self) -> None:
        assert len(STEP3_COLUMNS) == 186


# ── 2. 短仿真健全检查（100 步，约 1s）────────────────────────────────────

class TestShortRun:

    def setup_method(self) -> None:
        self.df = _run_sim(n_steps=100, warm_up=False, output_path="/tmp/test_short.parquet")

    def test_row_count(self) -> None:
        assert len(self.df) == 100

    def test_all_output_columns_present(self) -> None:
        expected = set(OUTPUT_COLUMNS)
        actual = set(self.df.columns) - {"t"}
        missing = expected - actual
        assert not missing, f"缺失列（前5个）：{list(missing)[:5]}"

    def test_no_nan_inf_except_targets(self) -> None:
        target_cols = {"y_fx_xin1", "y_fx_xin2", *PROCESS_LAB_COLUMNS}
        non_target = [c for c in OUTPUT_COLUMNS if c not in target_cols]
        for col in non_target:
            col_data = self.df[col]
            assert col_data.notna().all(), f"列 {col} 含 NaN"
            assert np.isfinite(col_data).all(), f"列 {col} 含 Inf"


# ── 3. 30 天全仿真（性能 + 数据质量）────────────────────────────────────

class TestFullRun:
    """耗时测试，只在 CI 中按需运行。"""

    @pytest.mark.slow
    def test_30day_runtime_under_5min(self) -> None:
        t0 = time.perf_counter()
        df = _run_sim(n_steps=43_200, open_loop=False, output_path="/tmp/test_full_cl.parquet")
        elapsed = time.perf_counter() - t0
        assert elapsed < 300.0, f"仿真耗时 {elapsed:.1f}s > 300s"
        assert len(df) == 43_200

    @pytest.mark.slow
    def test_no_nan_inf_except_targets_full(self) -> None:
        df = _run_sim(n_steps=43_200, open_loop=False, output_path="/tmp/test_full_cl2.parquet")
        target_cols = {"y_fx_xin1", "y_fx_xin2", *PROCESS_LAB_COLUMNS}
        non_target = [c for c in OUTPUT_COLUMNS if c not in target_cols]
        for col in non_target:
            assert df[col].notna().all(), f"{col} 含 NaN"
            assert np.isfinite(df[col]).all(), f"{col} 含 Inf"


# ── 4. 开环激励模式：TFe 统计特性 ────────────────────────────────────────

class TestOpenLoopStats:

    @pytest.fixture(scope="class")
    def df_open(self) -> pd.DataFrame:
        return _run_sim(
            n_steps=43_200, open_loop=True, seed=42,
            output_path="/tmp/test_open_loop.parquet",
        )

    @pytest.mark.slow
    def test_tfe_variance_ge_4(self, df_open: pd.DataFrame) -> None:
        """开环模式下 y_fx_xin1 非 NaN 值方差 ≥ 4.0 (%²)。"""
        tfe_pct = df_open["y_fx_xin1"].dropna() * 100
        assert len(tfe_pct) >= 20, f"化验点数不足：{len(tfe_pct)}"
        var = float(tfe_pct.var())
        assert var >= 4.0, f"TFe 方差 = {var:.3f} < 4.0"

    @pytest.mark.slow
    def test_tfe_mean_in_range(self, df_open: pd.DataFrame) -> None:
        """开环模式 TFe 均值应在 [66, 68] %。"""
        tfe_pct = df_open["y_fx_xin1"].dropna() * 100
        mean = float(tfe_pct.mean())
        assert 66.0 <= mean <= 68.0, f"TFe 均值 = {mean:.3f}%"


# ── 5. 传感器故障频率 ────────────────────────────────────────────────────

class TestFaultFrequency:

    @pytest.fixture(scope="class")
    def df_cl(self) -> pd.DataFrame:
        return _run_sim(
            n_steps=43_200, open_loop=False, seed=42,
            output_path="/tmp/test_fault_freq.parquet",
        )

    @pytest.mark.slow
    def test_bearing_fault_frequency(self, df_cl: pd.DataFrame) -> None:
        """轴承温度故障频率约为 0.2 %（允许范围 0.05 %~1.0 %）。"""
        bearing_col = "MC1_TM204_HDZC_1_WD_AI"
        fault_rate = (df_cl[bearing_col] < -100).mean() * 100
        assert 0.05 <= fault_rate <= 1.0, f"轴承故障率 = {fault_rate:.4f}%"

    @pytest.mark.slow
    def test_froth_fault_frequency(self, df_cl: pd.DataFrame) -> None:
        """泡沫层故障频率约为 0.5 %（允许范围 0.1 %~2.0 %）。"""
        froth_col = "fx_s1_cx1_froth_h"
        fault_rate = (df_cl[froth_col] == -21.0).mean() * 100
        assert 0.1 <= fault_rate <= 2.0, f"泡沫层故障率 = {fault_rate:.4f}%"
