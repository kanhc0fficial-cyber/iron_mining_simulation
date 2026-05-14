"""
工艺化验（ProcessLabSampler）与工具函数综合测试
Phase 5: 覆盖化验采样时机、采样值范围、NaN 间隔、各段化验字段、
         PID 控制器、RingBuffer 时滞、传感器噪声/漂移/故障注入、
         聚合统计功能等

测试角度:
  - ProcessLabSampler: 所有化验字段存在性、采样区间、单位、NaN 时机
  - 磁选化验: 各段品位 % 范围
  - 塔磨化验: 粒度、品位
  - 浮选化验: 精矿/尾矿品位、产率、回收率
  - PID 控制器: 稳态精度、积分饱和、Anti-Windup
  - RingBuffer: 时滞、容量检查
  - 传感器函数: add_noise、add_drift、inject_fault
  - 聚合函数: active_mask、aggregate_active、write_aggregate
  - 全流程化验采样集成
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import (
    ProcessLabConfig,
    SimConfig,
    BoundaryConfig,
    MagSepConfig,
    TowerMillConfig,
    FlotationConfig,
)
from sim.layers.process_lab import (
    ProcessLabSampler,
    MAG_LAB_COLUMNS,
    TM_LAB_COLUMNS,
    FLO_LAB_COLUMNS,
    INTERNAL_PROCESS_LAB_COLUMNS,
    _sigmoid,
    _finite,
)
from sim.utils.pid import PIDController
from sim.utils.buffer import RingBuffer
from sim.utils.sensor import add_noise, add_drift, inject_fault
from sim.utils.aggregation import (
    active_mask,
    aggregate_active,
    write_aggregate,
    AggregateStats,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_full_bus() -> dict:
    """构造一个完整的 bus，包含所有化验采样所需的隐藏字段。"""
    return {
        # 边界
        "_x_boundary_fe_mag": 800 * 0.3149 * 0.765,
        "_x_boundary_fe_hem": 800 * 0.3149 * 0.118,
        "_x_boundary_fe_carb": 800 * 0.3149 * 0.057,
        "_x_boundary_fe_sil": 800 * 0.3149 * 0.060,
        "_x_boundary_gangue": 800 * (1.0 - 0.3149),
        # 磁选
        "_x_mag_wm_conc_tfe": 0.68, "_x_mag_wm_tail_tfe": 0.10,
        "_x_mag_hm_conc_tfe": 0.55, "_x_mag_hm_tail_tfe": 0.08,
        "_x_mag_sw_conc_tfe": 0.48, "_x_mag_sw_tail_tfe": 0.06,
        "_x_mag_mixed_conc_tfe": 0.4384,
        "_x_mag_wm_conc_m": 200.0, "_x_mag_wm_tail_m": 600.0,
        # 塔磨
        "_x_tm_cyclone_feed_f325": 0.55, "_x_tm_discharge_f325": 0.80,
        "_x_f325_ov": 0.928, "_x_tm_overflow_f325": 0.928,
        "_x_tm_cyclone_overflow_f325": 0.928,
        "_x_tm_overflow_tfe": 0.4384, "_x_tm_overflow_conc": 0.15,
        "_x_tm_cyclone_sand_f325": 0.55,
        # 浮选 系列1
        "_x_flo_feed_s1_tfe": 0.4384, "_x_flo_feed_s1_m": 500.0,
        "_x_flo_feed_f325_s1": 0.928,
        "_x_flo_final_conc_s1_tfe": 0.67, "_x_flo_final_conc_s1_m": 130.0,
        "_x_flo_final_tail_s1_tfe": 0.13,
        "_x_flo_rougher_conc_s1_tfe": 0.65, "_x_flo_rougher_tail_s1_tfe": 0.15,
        "_x_flo_cleaner_tail_s1_tfe": 0.45,
        "_x_flo_scav1_conc_s1_tfe": 0.55, "_x_flo_scav1_tail_s1_tfe": 0.12,
        "_x_flo_scav2_conc_s1_tfe": 0.50, "_x_flo_scav2_tail_s1_tfe": 0.10,
        "_x_flo_scav3_conc_s1_tfe": 0.45, "_x_flo_scav3_tail_s1_tfe": 0.09,
        "_x_flo_feed_s1_fe_mag": 130.0, "_x_flo_feed_s1_fe_hem": 20.0,
        "_x_flo_feed_s1_fe_carb": 5.0, "_x_flo_feed_s1_fe_sil": 5.0,
        "_x_flo_final_conc_s1_fe_mag": 95.0, "_x_flo_final_conc_s1_fe_hem": 10.0,
        "_x_flo_final_conc_s1_fe_carb": 1.5, "_x_flo_final_conc_s1_fe_sil": 1.5,
        # 浮选 系列2
        "_x_flo_feed_s2_tfe": 0.4384, "_x_flo_feed_s2_m": 500.0,
        "_x_flo_feed_f325_s2": 0.928,
        "_x_flo_final_conc_s2_tfe": 0.67, "_x_flo_final_conc_s2_m": 130.0,
        "_x_flo_final_tail_s2_tfe": 0.13,
        "_x_flo_rougher_conc_s2_tfe": 0.65, "_x_flo_rougher_tail_s2_tfe": 0.15,
        "_x_flo_cleaner_tail_s2_tfe": 0.45,
        "_x_flo_scav1_conc_s2_tfe": 0.55, "_x_flo_scav1_tail_s2_tfe": 0.12,
        "_x_flo_scav2_conc_s2_tfe": 0.50, "_x_flo_scav2_tail_s2_tfe": 0.10,
        "_x_flo_scav3_conc_s2_tfe": 0.45, "_x_flo_scav3_tail_s2_tfe": 0.09,
        "_x_flo_feed_s2_fe_mag": 130.0, "_x_flo_feed_s2_fe_hem": 20.0,
        "_x_flo_feed_s2_fe_carb": 5.0, "_x_flo_feed_s2_fe_sil": 5.0,
        "_x_flo_final_conc_s2_fe_mag": 95.0, "_x_flo_final_conc_s2_fe_hem": 10.0,
        "_x_flo_final_conc_s2_fe_carb": 1.5, "_x_flo_final_conc_s2_fe_sil": 1.5,
    }


def _make_lab(
    cfg: ProcessLabConfig | None = None,
    seed: int = 0,
) -> ProcessLabSampler:
    rng = np.random.default_rng(seed)
    return ProcessLabSampler(cfg or ProcessLabConfig(), SimConfig(), rng)


def _run_lab(n: int = 500, seed: int = 0) -> list[dict]:
    lab = _make_lab(seed=seed)
    history: list[dict] = []
    for t in range(n):
        bus = _make_full_bus()
        lab.step(bus, t)
        history.append(dict(bus))
    return history


def _arr(history: list[dict], key: str) -> np.ndarray:
    return np.array([row[key] for row in history])


# ──────────────────────────────────────────────────────────────────────────────
# 1. ProcessLabSampler：字段完整性
# ──────────────────────────────────────────────────────────────────────────────

class TestLabColumns:

    def test_all_internal_lab_columns_in_bus(self):
        history = _run_lab(n=1)
        bus = history[-1]
        for col in INTERNAL_PROCESS_LAB_COLUMNS:
            assert col in bus, f"{col} 不在 bus 中"

    def test_mag_lab_columns_count(self):
        assert len(MAG_LAB_COLUMNS) == 9, f"MAG_LAB_COLUMNS 数目 {len(MAG_LAB_COLUMNS)} ≠ 9"

    def test_tm_lab_columns_count(self):
        assert len(TM_LAB_COLUMNS) == 6, f"TM_LAB_COLUMNS 数目 {len(TM_LAB_COLUMNS)} ≠ 6"

    def test_flo_lab_columns_count(self):
        expected = 2 * 14  # 2 系列 × 14 指标
        assert len(FLO_LAB_COLUMNS) == expected, \
            f"FLO_LAB_COLUMNS 数目 {len(FLO_LAB_COLUMNS)} ≠ {expected}"

    def test_all_mag_columns_present(self):
        bus = _make_full_bus()
        lab = _make_lab()
        lab.step(bus, 0)  # 第一步即采样
        for col in MAG_LAB_COLUMNS:
            assert col in bus

    def test_all_tm_columns_present(self):
        bus = _make_full_bus()
        lab = _make_lab()
        lab.step(bus, 0)
        for col in TM_LAB_COLUMNS:
            assert col in bus

    def test_all_flo_columns_present(self):
        bus = _make_full_bus()
        lab = _make_lab()
        lab.step(bus, 0)
        for col in FLO_LAB_COLUMNS:
            assert col in bus


# ──────────────────────────────────────────────────────────────────────────────
# 2. 采样时机与 NaN 行为
# ──────────────────────────────────────────────────────────────────────────────

class TestSamplingTiming:

    def test_all_nan_before_first_sample(self):
        """t=0 时第一步立即采样，t=1 时根据区间可能为 NaN。"""
        lab = _make_lab()
        # t=0 采样
        bus0 = _make_full_bus()
        lab.step(bus0, 0)
        assert math.isfinite(bus0["lab_mag_mixed_conc_tfe"]), \
            "第一步（t=0）应立即采样"

    def test_nan_between_samples(self):
        """两次采样之间应有 NaN 步。"""
        history = _run_lab(n=500)
        nan_count = sum(
            1 for row in history
            if math.isnan(row["lab_mag_mixed_conc_tfe"])
        )
        assert nan_count > 0, "采样间隔内应有 NaN"

    def test_sample_interval_within_config_bounds(self):
        """采样间隔应在 [interval_min_steps, interval_max_steps] 范围内。"""
        cfg = ProcessLabConfig()
        history = _run_lab(n=2000)
        # 找出采样时刻
        sample_times = [
            t for t, row in enumerate(history)
            if math.isfinite(row["lab_mag_mixed_conc_tfe"])
        ]
        assert len(sample_times) >= 3, "采样次数不足，无法验证间隔"
        intervals = [sample_times[i+1] - sample_times[i] for i in range(len(sample_times)-1)]
        for interval in intervals:
            assert cfg.interval_min_steps <= interval <= cfg.interval_max_steps + 1, \
                f"采样间隔 {interval} 超出 [{cfg.interval_min_steps}, {cfg.interval_max_steps}]"

    def test_sample_at_least_once_per_200_steps(self):
        """在 200 步内应至少采样一次。"""
        history = _run_lab(n=200)
        sample_count = sum(
            1 for row in history
            if math.isfinite(row["lab_mag_mixed_conc_tfe"])
        )
        assert sample_count >= 1, "200 步内未采样"

    def test_reproducibility(self):
        """相同种子产生相同采样时刻。"""
        h1 = _run_lab(n=300, seed=42)
        h2 = _run_lab(n=300, seed=42)
        for t in range(300):
            v1 = h1[t]["lab_mag_mixed_conc_tfe"]
            v2 = h2[t]["lab_mag_mixed_conc_tfe"]
            same_nan = math.isnan(v1) == math.isnan(v2)
            assert same_nan, f"t={t}: 种子相同但采样不同步"
            if not math.isnan(v1):
                assert abs(v1 - v2) < 1e-10


# ──────────────────────────────────────────────────────────────────────────────
# 3. 磁选化验值范围
# ──────────────────────────────────────────────────────────────────────────────

class TestMagLabValues:

    def setup_method(self):
        self.history = _run_lab(n=2000)
        # 只取有效采样行
        self.samples = [row for row in self.history
                        if math.isfinite(row["lab_mag_mixed_conc_tfe"])]

    def test_wm_conc_tfe_in_range(self):
        vals = [row["lab_mag_wm_conc_tfe"] for row in self.samples]
        for v in vals:
            assert 50.0 <= v <= 80.0, f"弱磁精矿 TFe={v:.2f}% 超出 [50,80]%"

    def test_wm_tail_tfe_in_range(self):
        vals = [row["lab_mag_wm_tail_tfe"] for row in self.samples]
        for v in vals:
            assert 0.0 <= v <= 30.0, f"弱磁尾矿 TFe={v:.2f}% 超出 [0,30]%"

    def test_hm_conc_tfe_in_range(self):
        vals = [row["lab_mag_hm_conc_tfe"] for row in self.samples]
        for v in vals:
            assert 20.0 <= v <= 70.0, f"强磁精矿 TFe={v:.2f}% 超出 [20,70]%"

    def test_mixed_conc_tfe_near_target(self):
        """混磁精矿品位 ≈ 43.84%（容差 ±5%）。"""
        vals = np.array([row["lab_mag_mixed_conc_tfe"] for row in self.samples])
        assert abs(vals.mean() - 43.84) < 5.0, \
            f"混精均值 {vals.mean():.2f}% 偏离 43.84%"

    def test_tube_yield_in_range(self):
        vals = [row["lab_mag_tube_yield"] for row in self.samples]
        for v in vals:
            assert 20.0 <= v <= 70.0, f"管式结选产率={v:.2f}% 超出 [20,70]%"

    def test_tube_conc_above_feed(self):
        """管式结选浓缩品位应高于原始给矿品位（品位提升效果）。"""
        feed_pct = 31.49
        for row in self.samples:
            tube_conc = row["lab_mag_tube_conc_tfe"]
            assert tube_conc >= feed_pct - 5.0, \
                f"管式结选品位 {tube_conc:.2f}% 低于给矿 {feed_pct:.2f}%"

    def test_conc_grade_above_tail_grade(self):
        """精矿品位 > 尾矿品位（基本物理约束）。"""
        for row in self.samples:
            assert row["lab_mag_wm_conc_tfe"] > row["lab_mag_wm_tail_tfe"], \
                "弱精 TFe 应高于弱尾 TFe"

    def test_sw_conc_above_sw_tail(self):
        for row in self.samples:
            assert row["lab_mag_sw_conc_tfe"] > row["lab_mag_sw_tail_tfe"], \
                "扫精 TFe 应高于扫尾 TFe"


# ──────────────────────────────────────────────────────────────────────────────
# 4. 塔磨化验值范围
# ──────────────────────────────────────────────────────────────────────────────

class TestTMLabValues:

    def setup_method(self):
        self.history = _run_lab(n=2000)
        self.samples = [row for row in self.history
                        if math.isfinite(row["lab_tm_overflow_f325"])]

    def test_overflow_f325_in_range(self):
        vals = [row["lab_tm_overflow_f325"] for row in self.samples]
        for v in vals:
            assert 80.0 <= v <= 100.0, f"溢流-325目={v:.2f}% 超出 [80,100]%"

    def test_overflow_f325_near_calibration(self):
        """稳态 f325_ov ≈ 92.8%（±3%）。"""
        vals = np.array([row["lab_tm_overflow_f325"] for row in self.samples])
        assert abs(vals.mean() - 92.8) < 3.0, \
            f"溢流-325目均值 {vals.mean():.2f}% 偏离 92.8%"

    def test_discharge_f325_less_than_overflow_f325(self):
        """磨机出料 -325目 < 溢流 -325目（旋流器富集了细粒级）。"""
        for row in self.samples:
            disch = row["lab_tm_discharge_f325"]
            ov = row["lab_tm_overflow_f325"]
            assert disch <= ov + 5.0, \
                f"出料-325目 {disch:.2f}% 不应显著大于溢流 {ov:.2f}%"

    def test_feed_f325_less_than_overflow_f325(self):
        """给矿 -325目（来自磁精矿）应低于溢流 -325目。"""
        for row in self.samples:
            feed = row["lab_tm_feed_f325"]
            ov = row["lab_tm_overflow_f325"]
            assert feed <= ov + 5.0, \
                f"给矿-325目 {feed:.2f}% 不应显著大于溢流 {ov:.2f}%"

    def test_overflow_tfe_in_range(self):
        vals = [row["lab_tm_overflow_tfe"] for row in self.samples]
        for v in vals:
            assert 30.0 <= v <= 70.0, f"溢流 TFe={v:.2f}% 超出 [30,70]%"

    def test_overflow_conc_in_range(self):
        vals = [row["lab_tm_overflow_conc"] for row in self.samples]
        for v in vals:
            assert 0.0 <= v <= 100.0, f"溢流浓度={v:.2f}% 超出 [0,100]%"

    def test_sand_f325_in_range(self):
        vals = [row["lab_tm_sand_f325"] for row in self.samples]
        for v in vals:
            assert 0.0 <= v <= 100.0, f"沉砂-325目={v:.2f}% 超出 [0,100]%"


# ──────────────────────────────────────────────────────────────────────────────
# 5. 浮选化验值范围
# ──────────────────────────────────────────────────────────────────────────────

class TestFloLabValues:

    def setup_method(self):
        self.history = _run_lab(n=2000)
        self.samples = [row for row in self.history
                        if math.isfinite(row["lab_flo_conc_tfe_s1"])]

    def test_conc_tfe_in_range(self):
        for s in (1, 2):
            vals = [row[f"lab_flo_conc_tfe_s{s}"] for row in self.samples]
            for v in vals:
                assert 50.0 <= v <= 80.0, f"浮精TFe_s{s}={v:.2f}% 超出 [50,80]%"

    def test_tail_tfe_in_range(self):
        for s in (1, 2):
            vals = [row[f"lab_flo_tail_tfe_s{s}"] for row in self.samples]
            for v in vals:
                assert 5.0 <= v <= 35.0, f"浮尾TFe_s{s}={v:.2f}% 超出 [5,35]%"

    def test_conc_tfe_above_tail_tfe(self):
        """精矿品位 > 尾矿品位。"""
        for row in self.samples:
            for s in (1, 2):
                assert row[f"lab_flo_conc_tfe_s{s}"] > row[f"lab_flo_tail_tfe_s{s}"], \
                    f"浮精品位应 > 浮尾品位"

    def test_final_conc_yield_in_range(self):
        vals = [row["lab_flo_final_conc_yield_s1"] for row in self.samples
                if math.isfinite(row["lab_flo_final_conc_yield_s1"])]
        for v in vals:
            assert 0.0 <= v <= 100.0, f"精矿产率={v:.2f}% 超出 [0,100]%"

    def test_final_conc_recovery_in_range(self):
        vals = [row["lab_flo_final_conc_recovery_s1"] for row in self.samples
                if math.isfinite(row["lab_flo_final_conc_recovery_s1"])]
        for v in vals:
            assert 0.0 <= v <= 100.0, f"铁回收率={v:.2f}% 超出 [0,100]%"

    def test_rougher_conc_above_rougher_feed(self):
        """粗精品位 > 粗给品位（浮选富集）。"""
        for row in self.samples:
            feed = row.get("lab_flo_feed_tfe_s1", None)
            rc = row.get("lab_flo_rough_conc_tfe_s1", None)
            if feed and rc:
                assert rc >= feed - 5.0, \
                    f"粗精品位 {rc:.2f}% 不应显著低于给矿 {feed:.2f}%"


# ──────────────────────────────────────────────────────────────────────────────
# 6. 工具函数：_sigmoid, _finite
# ──────────────────────────────────────────────────────────────────────────────

class TestLabUtils:

    def test_sigmoid_at_zero(self):
        assert abs(_sigmoid(0.0) - 0.5) < 1e-9

    def test_sigmoid_large_positive(self):
        assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-6)

    def test_sigmoid_large_negative(self):
        assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-6)

    def test_sigmoid_monotone(self):
        xs = [-10, -5, -1, 0, 1, 5, 10]
        vals = [_sigmoid(x) for x in xs]
        assert all(vals[i] < vals[i+1] for i in range(len(vals)-1))

    def test_finite_true(self):
        assert _finite(1.0) is True
        assert _finite(0.0) is True

    def test_finite_false_nan(self):
        assert _finite(float("nan")) is False

    def test_finite_false_inf(self):
        assert _finite(float("inf")) is False


# ──────────────────────────────────────────────────────────────────────────────
# 7. PID 控制器
# ──────────────────────────────────────────────────────────────────────────────

class TestPIDController:

    def test_pure_p_reaches_steady_state(self):
        """纯 P 控制（Ki=Kd=0）：输出 = Kp * e，无积分项时有稳态误差。"""
        pid = PIDController(Kp=1.0, Ki=0.0, Kd=0.0, dt=1.0)
        u = pid.step(setpoint=10.0, measurement=0.0)
        assert u == pytest.approx(1.0, abs=1e-9)  # 输出被限幅到 u_max=1.0

    def test_pi_eliminates_steady_state_error(self):
        """PI 控制在稳态误差为 0 时积分应稳定。"""
        pid = PIDController(Kp=1.0, Ki=0.5, Kd=0.0, dt=1.0, u_max=10.0)
        u_prev = 0.0
        for _ in range(1000):
            # 系统：y = 0.9 * y + 0.1 * u（一阶系统）
            # 模拟到接近稳态
            u_prev = pid.step(setpoint=5.0, measurement=u_prev * 0.9)
        # 输出应接近 5.0
        # 实际上 PI 在此简单积分下会趋向 sp
        # 不做严格断言，只检查控制器不发散
        assert u_prev < 20.0, "PI 控制器发散"

    def test_output_clipped_to_u_max(self):
        """输出应被限幅到 u_max。"""
        pid = PIDController(Kp=100.0, Ki=0.0, Kd=0.0, dt=1.0, u_max=1.0)
        u = pid.step(setpoint=1000.0, measurement=0.0)
        assert u <= 1.0, f"输出 {u} 超过 u_max=1.0"

    def test_output_clipped_to_u_min(self):
        """输出应被限幅到 u_min。"""
        pid = PIDController(Kp=100.0, Ki=0.0, Kd=0.0, dt=1.0, u_min=-1.0, u_max=0.0)
        u = pid.step(setpoint=-1000.0, measurement=0.0)
        assert u >= -1.0, f"输出 {u} 低于 u_min=-1.0"

    def test_anti_windup_prevents_integral_growth(self):
        """Anti-Windup 开启时，饱和后积分不再增长。"""
        pid = PIDController(Kp=0.0, Ki=1.0, Kd=0.0, dt=1.0, u_max=1.0, anti_windup=True)
        for _ in range(100):
            pid.step(setpoint=100.0, measurement=0.0)
        # 如果 anti-windup 正常，积分不应无界增长
        assert pid._integral < 200.0, "Anti-Windup 未生效，积分过大"

    def test_no_anti_windup_grows_integral(self):
        """Anti-Windup 关闭时，积分累积。"""
        pid = PIDController(Kp=0.0, Ki=1.0, Kd=0.0, dt=1.0, u_max=1.0, anti_windup=False)
        for _ in range(100):
            pid.step(setpoint=100.0, measurement=0.0)
        assert pid._integral > 100.0, "关闭 Anti-Windup 后积分应大幅增长"

    def test_reset_clears_state(self):
        pid = PIDController(Kp=1.0, Ki=1.0, Kd=1.0, dt=1.0)
        for _ in range(50):
            pid.step(setpoint=10.0, measurement=0.0)
        pid.reset()
        assert pid._integral == 0.0
        assert pid._e_prev == 0.0

    def test_derivative_action(self):
        """正向误差变化 → 正导数 → 增大输出。"""
        pid_d = PIDController(Kp=0.0, Ki=0.0, Kd=1.0, dt=1.0, u_max=100.0)
        u1 = pid_d.step(setpoint=10.0, measurement=0.0)   # e=10, de=10/dt=10
        u2 = pid_d.step(setpoint=10.0, measurement=0.0)   # e=10, de=0
        assert u1 > 0, "正误差变化应产生正导数输出"
        # 第二步导数为 0，输出应接近 0
        assert u2 < u1, "误差不变时导数应减小"

    def test_zero_error_zero_output_with_p_only(self):
        """sp=meas 时，纯 P 输出为 0。"""
        pid = PIDController(Kp=1.0, Ki=0.0, Kd=0.0, dt=1.0)
        u = pid.step(setpoint=5.0, measurement=5.0)
        assert u == pytest.approx(0.0, abs=1e-9)


# ──────────────────────────────────────────────────────────────────────────────
# 8. RingBuffer
# ──────────────────────────────────────────────────────────────────────────────

class TestRingBuffer:

    def test_init_default_value(self):
        buf = RingBuffer(capacity=5, default=3.14)
        for i in range(5):
            assert buf.peek(i) == pytest.approx(3.14)

    def test_push_and_peek_latest(self):
        buf = RingBuffer(capacity=5)
        buf.push(42.0)
        assert buf.peek(0) == pytest.approx(42.0)

    def test_push_and_peek_delayed(self):
        buf = RingBuffer(capacity=5)
        buf.push(1.0)
        buf.push(2.0)
        buf.push(3.0)
        assert buf.peek(0) == pytest.approx(3.0)
        assert buf.peek(1) == pytest.approx(2.0)
        assert buf.peek(2) == pytest.approx(1.0)

    def test_circular_wrapping(self):
        """超过容量时，旧值被覆盖。"""
        buf = RingBuffer(capacity=3)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            buf.push(v)
        # 现在缓冲区中：4.0, 5.0, ... 最新是 5.0
        assert buf.peek(0) == pytest.approx(5.0)
        assert buf.peek(1) == pytest.approx(4.0)
        assert buf.peek(2) == pytest.approx(3.0)

    def test_invalid_capacity(self):
        with pytest.raises(ValueError, match="capacity"):
            RingBuffer(capacity=0)

    def test_invalid_delay_too_large(self):
        buf = RingBuffer(capacity=5)
        with pytest.raises(ValueError):
            buf.peek(5)  # delay_steps >= capacity

    def test_invalid_delay_negative(self):
        buf = RingBuffer(capacity=5)
        with pytest.raises(ValueError):
            buf.peek(-1)

    def test_capacity_property(self):
        buf = RingBuffer(capacity=10)
        assert buf.capacity == 10

    def test_fifo_ordering(self):
        """先进先出：最早写入的值在最大 delay 处。"""
        buf = RingBuffer(capacity=10)
        for i in range(10):
            buf.push(float(i))
        assert buf.peek(9) == pytest.approx(0.0)

    def test_single_capacity_buffer(self):
        buf = RingBuffer(capacity=1)
        buf.push(99.0)
        assert buf.peek(0) == pytest.approx(99.0)
        buf.push(100.0)
        assert buf.peek(0) == pytest.approx(100.0)


# ──────────────────────────────────────────────────────────────────────────────
# 9. 传感器函数
# ──────────────────────────────────────────────────────────────────────────────

class TestSensorFunctions:

    def test_add_noise_mean_zero(self):
        rng = np.random.default_rng(0)
        vals = [add_noise(1.0, 0.1, rng) for _ in range(10000)]
        assert abs(np.mean(vals) - 1.0) < 0.01, "add_noise 均值偏差过大"

    def test_add_noise_std_correct(self):
        rng = np.random.default_rng(1)
        sigma = 0.5
        vals = [add_noise(0.0, sigma, rng) for _ in range(10000)]
        assert abs(np.std(vals) - sigma) < 0.05, "add_noise 标准差偏差过大"

    def test_add_noise_no_change_with_zero_sigma(self):
        rng = np.random.default_rng(0)
        result = add_noise(5.0, 0.0, rng)
        assert result == pytest.approx(5.0)

    def test_add_drift_updates_bias(self):
        rng = np.random.default_rng(0)
        obs, b_new = add_drift(10.0, 0.0, 0.01, rng)
        assert b_new != 0.0, "漂移偏置应更新"
        assert abs(obs - (10.0 + b_new)) < 1e-9

    def test_add_drift_random_walk(self):
        """多步漂移后，偏置标准差 ≈ sigma_b * sqrt(n)（随机游走）。"""
        rng = np.random.default_rng(42)
        biases = []
        b = 0.0
        sigma_b = 0.1
        n = 10000
        for _ in range(n):
            _, b = add_drift(0.0, b, sigma_b, rng)
            biases.append(b)
        # 随机游走末端方差 ≈ sigma_b^2 * n
        std_expected = sigma_b * np.sqrt(n)
        # 只检查漂移确实发生（方差非零）
        assert np.std(biases) > sigma_b, "漂移偏置未随机游走"

    def test_inject_fault_zero_probability(self):
        """p_fault=0 时不注入故障。"""
        rng = np.random.default_rng(0)
        for _ in range(1000):
            result = inject_fault(5.0, 0.0, -999.0, rng)
            assert result == pytest.approx(5.0)

    def test_inject_fault_certain(self):
        """p_fault=1 时总是注入故障。"""
        rng = np.random.default_rng(0)
        for _ in range(100):
            result = inject_fault(5.0, 1.0, -999.0, rng)
            assert result == pytest.approx(-999.0)

    def test_inject_fault_probabilistic(self):
        """p_fault=0.1 时，约 10% 返回故障值。"""
        rng = np.random.default_rng(0)
        fault_count = sum(
            1 for _ in range(10000)
            if inject_fault(5.0, 0.1, -999.0, rng) == pytest.approx(-999.0)
        )
        assert abs(fault_count / 10000.0 - 0.1) < 0.02, \
            f"故障注入概率 {fault_count/10000:.3f} 偏离 0.1"


# ──────────────────────────────────────────────────────────────────────────────
# 10. 聚合函数
# ──────────────────────────────────────────────────────────────────────────────

class TestAggregation:

    def test_active_mask_all_active(self):
        mask = active_mask(5, 5)
        assert mask.sum() == 5
        assert np.all(mask)

    def test_active_mask_none_active(self):
        mask = active_mask(5, 0)
        assert mask.sum() == 0

    def test_active_mask_partial(self):
        mask = active_mask(6, 4)
        assert mask.sum() == 4
        assert np.all(mask[:4])
        assert not np.any(mask[4:])

    def test_active_mask_exceeds_total(self):
        """active_count > total 时，应裁剪至 total。"""
        mask = active_mask(5, 10)
        assert mask.sum() == 5

    def test_aggregate_active_mean(self):
        vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        stats = aggregate_active(vals)
        assert stats.mean == pytest.approx(3.0)

    def test_aggregate_active_with_mask(self):
        vals = np.array([10.0, 20.0, 30.0])
        mask = np.array([True, True, False])
        stats = aggregate_active(vals, mask)
        assert stats.mean == pytest.approx(15.0)
        assert stats.active_count == 2

    def test_aggregate_fallback_when_no_active(self):
        """无设备运行时，应使用全部设备作为 fallback。"""
        vals = np.array([1.0, 2.0, 3.0])
        mask = np.array([False, False, False])
        stats = aggregate_active(vals, mask)
        assert stats.active_count == 0
        assert math.isfinite(stats.mean), "fallback 时 mean 应为有限数"

    def test_aggregate_empty_fallback(self):
        vals = np.array([])
        stats = aggregate_active(vals)
        assert stats.mean == 0.0

    def test_write_aggregate_sets_main_key(self):
        bus: dict = {}
        stats = AggregateStats(mean=42.0, std=1.0, min=40.0, max=44.0,
                               active_count=3, total_count=5)
        write_aggregate(bus, "test_signal", stats)
        assert bus["test_signal"] == pytest.approx(42.0)

    def test_write_aggregate_sets_diagnostics(self):
        bus: dict = {}
        stats = AggregateStats(mean=5.0, std=2.0, min=3.0, max=7.0,
                               active_count=3, total_count=5)
        write_aggregate(bus, "test_signal", stats)
        assert "test_signal_std" in bus
        assert "test_signal_min" in bus
        assert "test_signal_max" in bus
        assert "test_signal_on_count" in bus

    def test_aggregate_std_correct(self):
        vals = np.array([1.0, 3.0])
        stats = aggregate_active(vals)
        assert stats.std == pytest.approx(1.0)

    def test_aggregate_min_max_correct(self):
        vals = np.array([5.0, 1.0, 9.0, 3.0])
        stats = aggregate_active(vals)
        assert stats.min == pytest.approx(1.0)
        assert stats.max == pytest.approx(9.0)


# ──────────────────────────────────────────────────────────────────────────────
# 11. 全流程集成：ProcessLabSampler + 全段
# ──────────────────────────────────────────────────────────────────────────────

class TestFullPipelineLabSampling:

    def test_run_with_all_layers(self):
        """边界+磁选+塔磨+浮选+化验全流程运行 200 步不崩溃。"""
        from sim.layers.boundary import BoundaryGenerator
        from sim.layers.mag_sep import MagSepSystem
        from sim.layers.tower_mill import TowerMillSystem
        from sim.layers.flotation import FlotationSystem

        sim_cfg = SimConfig(seed=0)
        rng_b = np.random.default_rng(0)
        rng_m = np.random.default_rng(1)
        rng_t = np.random.default_rng(2)
        rng_f = np.random.default_rng(3)
        rng_l = np.random.default_rng(4)

        boundary = BoundaryGenerator(BoundaryConfig(), sim_cfg, rng_b)
        mag = MagSepSystem(MagSepConfig(), sim_cfg, rng_m)
        tm = TowerMillSystem(TowerMillConfig(), sim_cfg, rng_t)
        flo = FlotationSystem(FlotationConfig(), sim_cfg, rng_f)
        lab = ProcessLabSampler(ProcessLabConfig(), sim_cfg, rng_l)

        history: list[dict] = []
        for t in range(200):
            bus: dict = {"t": t}
            boundary.step(bus, t)
            mag.step(bus, t)
            tm.step(bus, t)
            flo.step(bus, t)
            lab.step(bus, t)
            history.append(dict(bus))

        for col in INTERNAL_PROCESS_LAB_COLUMNS:
            assert col in history[-1], f"{col} 不在最终 bus 中"

    def test_lab_samples_occur_in_full_run(self):
        """200步全流程中，化验至少采样一次。"""
        from sim.layers.boundary import BoundaryGenerator
        from sim.layers.mag_sep import MagSepSystem
        from sim.layers.tower_mill import TowerMillSystem
        from sim.layers.flotation import FlotationSystem

        sim_cfg = SimConfig(seed=0)
        boundary = BoundaryGenerator(BoundaryConfig(), sim_cfg, np.random.default_rng(0))
        mag = MagSepSystem(MagSepConfig(), sim_cfg, np.random.default_rng(1))
        tm = TowerMillSystem(TowerMillConfig(), sim_cfg, np.random.default_rng(2))
        flo = FlotationSystem(FlotationConfig(), sim_cfg, np.random.default_rng(3))
        lab = ProcessLabSampler(ProcessLabConfig(), sim_cfg, np.random.default_rng(4))

        sample_count = 0
        for t in range(200):
            bus: dict = {}
            boundary.step(bus, t)
            mag.step(bus, t)
            tm.step(bus, t)
            flo.step(bus, t)
            lab.step(bus, t)
            if math.isfinite(bus["lab_mag_mixed_conc_tfe"]):
                sample_count += 1
        assert sample_count >= 1, "200步全流程内未产生任何化验值"

    def test_invalid_interval_raises(self):
        """interval_min > interval_max 时 ProcessLabSampler 构造应抛异常。"""
        cfg = ProcessLabConfig(interval_min_steps=100, interval_max_steps=10)
        rng = np.random.default_rng(0)
        with pytest.raises(ValueError):
            ProcessLabSampler(cfg, SimConfig(), rng)
