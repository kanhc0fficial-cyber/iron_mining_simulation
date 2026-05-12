"""
扰动层单元测试。

验证：
  1. 相同 seed → 完全相同的输出序列
  2. 不同 seed → 不同输出
  3. 所有扰动变量始终在物理可行范围内
  4. d1/d2 之间存在负相关性（100步样本）
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import DisturbanceConfig
from sim.layers.disturbance import DisturbanceLayer


def run_n_steps(seed: int, n: int = 200) -> dict[str, list[float]]:
    """运行 n 步扰动层，返回各变量时序列表。"""
    cfg = DisturbanceConfig()
    rng = np.random.default_rng(seed)
    layer = DisturbanceLayer(cfg, rng)
    results: dict[str, list[float]] = {
        "_x_d1": [], "_x_d2": [], "_x_d3": [], "_x_d4": [],
    }
    for _ in range(n):
        bus: dict = {}
        layer.step(bus)
        for key in results:
            results[key].append(bus[key])
    return results


class TestDisturbanceReproducibility:
    def test_same_seed_same_output(self):
        r1 = run_n_steps(seed=42, n=100)
        r2 = run_n_steps(seed=42, n=100)
        for key in r1:
            assert r1[key] == r2[key], f"{key} 输出不可复现"

    def test_different_seed_different_output(self):
        r1 = run_n_steps(seed=42, n=50)
        r2 = run_n_steps(seed=99, n=50)
        # 至少 d1 的均值应不同
        diff = abs(np.mean(r1["_x_d1"]) - np.mean(r2["_x_d1"]))
        # 即使均值接近（两者都会趋于 d1_mean），序列本身应不相同
        assert r1["_x_d1"] != r2["_x_d1"], "不同种子产生了相同序列"


class TestDisturbancePhysicalRange:
    def test_d1_in_range(self):
        cfg = DisturbanceConfig()
        results = run_n_steps(seed=42, n=500)
        for v in results["_x_d1"]:
            assert cfg.d1_min <= v <= cfg.d1_max, f"d1={v:.4f} 超出 [{cfg.d1_min}, {cfg.d1_max}]"

    def test_d2_in_range(self):
        cfg = DisturbanceConfig()
        results = run_n_steps(seed=42, n=500)
        for v in results["_x_d2"]:
            assert cfg.d2_min <= v <= cfg.d2_max, f"d2={v:.4f} 超出范围"

    def test_d3_in_range(self):
        cfg = DisturbanceConfig()
        results = run_n_steps(seed=42, n=500)
        for v in results["_x_d3"]:
            assert cfg.d3_min <= v <= cfg.d3_max, f"d3={v:.4f} 超出范围"

    def test_d4_in_range(self):
        cfg = DisturbanceConfig()
        results = run_n_steps(seed=42, n=500)
        for v in results["_x_d4"]:
            assert cfg.d4_min <= v <= cfg.d4_max, f"d4={v:.4f} 超出范围"


class TestDisturbanceCorrelation:
    def test_d1_d2_negative_correlation(self):
        """d1-d2 应呈负相关（cov_d1d2=-0.6）。"""
        results = run_n_steps(seed=42, n=2000)
        d1 = np.array(results["_x_d1"])
        d2 = np.array(results["_x_d2"])
        corr = float(np.corrcoef(d1, d2)[0, 1])
        # OU 过程经过剪切后相关性会弱化，但应仍为负值
        assert corr < 0.0, f"d1-d2 相关系数 = {corr:.3f}，应为负值"

    def test_d1_mean_near_config(self):
        cfg = DisturbanceConfig()
        results = run_n_steps(seed=42, n=5000)
        mean_d1 = np.mean(results["_x_d1"])
        assert abs(mean_d1 - cfg.d1_mean) < 0.01, (
            f"d1 均值 {mean_d1:.4f} 偏离标定值 {cfg.d1_mean}"
        )
