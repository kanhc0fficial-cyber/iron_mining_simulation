"""
入口边界发生器测试（设计 v2 阶段 1）。

验证：
  1. 新 BoundaryGenerator 写出旧 `_x_*` 兼容字段
  2. 三路线入口 TFe、浓度、F200 分布落在现场主场景范围
  3. 入口过程化验按采样时刻输出，非采样时刻允许 NaN
  4. 边界层不输出球磨 DCS 点位，只输出隐藏兼容量和 lab_*
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import BoundaryConfig, SimConfig
from sim.layers.boundary import BoundaryGenerator, BOUNDARY_LAB_COLUMNS


def _run_boundary(n: int = 300, seed: int = 42, cfg: BoundaryConfig | None = None) -> list[dict]:
    sim_cfg = SimConfig(seed=seed)
    rng = np.random.default_rng(seed)
    boundary = BoundaryGenerator(cfg or BoundaryConfig(), sim_cfg, rng)
    history: list[dict] = []
    for t in range(n):
        bus: dict = {"t": t}
        boundary.step(bus, t)
        history.append(dict(bus))
    return history


class TestBoundaryCompatibility:
    def test_legacy_hidden_fields_present(self) -> None:
        bus = _run_boundary(n=1)[-1]
        expected = {
            "_x_d1",
            "_x_d2",
            "_x_d3",
            "_x_d4",
            "_x_m_ball",
            "_x_rho_ball",
            "_x_d80_ball",
            "_x_f25_ball",
            "_x_f200_ball",
            "_x_f325_ball",
        }
        missing = expected - set(bus)
        assert not missing, f"缺少兼容隐藏字段：{missing}"

    def test_three_line_hidden_states_present(self) -> None:
        bus = _run_boundary(n=1)[-1]
        for line_id in (1, 2, 3):
            for suffix in ("on", "m_solid", "c", "tfe", "f200", "f325", "f25", "d80"):
                key = f"_x_eryi_line{line_id}_{suffix}"
                assert key in bus, f"{key} 不在 bus 中"

    def test_boundary_emits_no_ball_mill_dcs_columns(self) -> None:
        bus = _run_boundary(n=1)[-1]
        public_non_lab = [
            key for key in bus
            if not key.startswith("_x_") and not key.startswith("lab_") and key != "t"
        ]
        assert public_non_lab == [], f"边界层不应输出 DCS 列：{public_non_lab}"


class TestBoundaryRanges:
    def test_mixed_feed_ranges_match_phase1_targets(self) -> None:
        history = _run_boundary(n=1000)
        late = history[100:]
        tfe = np.array([row["_x_d1"] for row in late])
        concentration = np.array([row["_x_rho_ball"] for row in late])
        f200 = np.array([row["_x_f200_ball"] for row in late])

        assert 0.305 <= float(tfe.mean()) <= 0.325
        assert np.all((0.30 <= tfe) & (tfe <= 0.38))
        assert 0.36 <= float(concentration.mean()) <= 0.405
        assert np.all((0.34 <= concentration) & (concentration <= 0.42))
        assert 0.74 <= float(f200.mean()) <= 0.83
        assert np.all((0.74 <= f200) & (f200 <= 0.83))

    def test_line_schedule_is_discrete(self) -> None:
        cfg = BoundaryConfig(p_line_schedule_switch=1.0)
        history = _run_boundary(n=50, cfg=cfg)
        counts = {row["_x_boundary_lines_on"] for row in history}
        assert counts <= {1, 2, 3}
        assert counts, "未生成开台数"


class TestBoundaryLabs:
    def test_lab_columns_present_and_sampled(self) -> None:
        history = _run_boundary(n=180)
        for row in history:
            for col in BOUNDARY_LAB_COLUMNS:
                assert col in row, f"{col} 不在 bus 中"

        finite_counts = {
            col: sum(math.isfinite(row[col]) for row in history)
            for col in BOUNDARY_LAB_COLUMNS
        }
        assert all(count >= 2 for count in finite_counts.values()), finite_counts

    def test_lab_values_are_percent_units(self) -> None:
        history = _run_boundary(n=180)
        for row in history:
            for line_id in (1, 2, 3):
                tfe = row[f"lab_{line_id}_eryi_tfe"]
                f200 = row[f"lab_{line_id}_eryi_f200"]
                if math.isfinite(tfe):
                    assert 25.0 <= tfe <= 38.0
                if math.isfinite(f200):
                    assert 70.0 <= f200 <= 86.0
