#!/usr/bin/env python3
"""
磁选段标定点断言脚本（第一步）。

验收标准（来自考查报告）：
  弱磁选（d1=31.49%）：
    - 弱磁精矿品位 g_wmag ≈ 51.29 % ± 0.5 %
    - 铁作业回收率 beta_wm ≈ 45.23 % ± 1.0 %
    - 弱磁尾矿品位（= 强磁给矿） ≈ 23.91 % ± 0.5 %

  强磁选（g_feed=23.91%，名义励磁、名义流速）：
    - 强磁精矿品位 g_strong ≈ 40.73 % ± 1.0 %
    - 强磁铁回收率 beta_strong ≈ 67.99 % ± 1.0 %

  混磁精矿（d1=31.49%，全段稳态）：
    - 混磁精矿品位 g_mag ≈ 43.84 % ± 1.0 %

不依赖运行仿真：直接调用代数公式，断言参数一致性。
"""

from __future__ import annotations
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import MagSepConfig


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def assert_close(
    name: str,
    actual: float,
    expected: float,
    tol: float,
    unit: str = "%",
) -> None:
    scale = 100.0 if unit == "%" else 1.0
    err = abs(actual * scale - expected)
    status = "✓" if err <= tol else "✗"
    print(f"  [{status}] {name}: {actual*scale:.4f}%  (期望 {expected:.2f}±{tol:.2f})")
    if err > tol:
        raise AssertionError(
            f"{name} 标定失败：actual={actual*scale:.4f}%, "
            f"expected={expected:.2f}%, tol=±{tol:.2f}%"
        )


def main() -> None:
    cfg = MagSepConfig()

    print("=" * 60)
    print("磁选段标定点验证")
    print("=" * 60)

    # ── 弱磁选标定（d1 = 31.49%）────────────────────────────────────────
    print("\n【弱磁选标定】d1 = 31.49%")
    d1_cal = 0.3149
    f25_ref = cfg.f25_nom  # 名义超细粒含量

    g_wmag = d1_cal * cfg.k_wm_Fe / (1.0 + cfg.k_wm_Si * (1.0 - d1_cal))
    g_wmag = min(max(g_wmag, 0.0), 1.0)
    assert_close("弱磁精矿品位 g_wmag", g_wmag, 51.29, 0.50)

    beta_wm = cfg.beta_wm0 * (1.0 - cfg.k_wm_f25 * f25_ref)
    beta_wm = min(max(beta_wm, 0.01), 0.99)
    assert_close("弱磁铁回收率 beta_wm", beta_wm, 45.23, 1.00)

    # 弱磁尾矿品位（= 强磁给矿品位）
    m_Fe = d1_cal
    m_conc_frac = beta_wm * m_Fe / g_wmag      # 精矿质量分数（对给矿归一化）
    m_tail_frac = 1.0 - m_conc_frac
    if m_tail_frac > 0.01:
        g_wm_tail = (m_Fe - beta_wm * m_Fe) / m_tail_frac
    else:
        g_wm_tail = 0.0
    assert_close("弱磁尾矿品位（强磁给矿）g_wm_tail", g_wm_tail, 23.91, 0.50)

    # ── 强磁选标定（g_feed = 23.91%，名义励磁/流速）────────────────────
    print("\n【强磁选标定】g_feed = 23.91%（名义励磁，名义流速）")
    g_feed = g_wm_tail   # 由弱磁标定结果传递，应接近 23.91%

    g_strong = g_feed * cfg.k_s_Fe / (1.0 + cfg.k_s_Si * (1.0 - g_feed))
    g_strong = min(max(g_strong, g_feed), 1.0)
    assert_close("强磁精矿品位 g_strong", g_strong, 40.73, 1.00)

    # 名义 beta_strong（force_balance = 1.0 → log(1) = 0 → sigmoid(bias_s)）
    beta_strong_nom = sigmoid(cfg.bias_s)
    assert_close("强磁铁回收率 beta_strong（名义点）", beta_strong_nom, 67.99, 1.00)

    # ── 混磁精矿标定（全段稳态，d1=31.49%）─────────────────────────────
    print("\n【混磁精矿标定】d1=31.49%，全段稳态")
    m_ball_nom = 265.0 * 3    # t/h，三线合计

    # 弱磁精矿与尾矿质量流
    m_wm_conc = beta_wm * d1_cal * m_ball_nom / g_wmag
    m_wm_tail_flow = m_ball_nom - m_wm_conc

    m_wm_tail_flow = m_ball_nom - m_wm_conc     # alias used below

    # 强磁精矿质量流
    g_feed_strong = g_wm_tail
    if g_strong > 0.01 and m_wm_tail_flow > 0.01:
        m_strong_conc = beta_strong_nom * g_feed_strong * m_wm_tail_flow / g_strong
    else:
        m_strong_conc = 0.0
    m_strong_conc = min(m_strong_conc, m_wm_tail_flow)
    m_strong_tail = m_wm_tail_flow - m_strong_conc

    # 强磁尾矿品位（= 扫强磁给矿品位）
    if m_strong_tail > 0.01:
        m_Fe_tail = g_feed_strong * m_wm_tail_flow
        m_Fe_strong_conc = g_strong * m_strong_conc
        g_strong_tail = (m_Fe_tail - m_Fe_strong_conc) / m_strong_tail
    else:
        g_strong_tail = 0.0
    g_strong_tail = max(g_strong_tail, 0.0)

    # 扫强磁精矿
    g_sweep = g_strong_tail * cfg.k_sw_Fe / (1.0 + cfg.k_sw_Si * (1.0 - g_strong_tail))
    g_sweep = min(max(g_sweep, g_strong_tail), 1.0)
    if g_sweep > 0.01 and m_strong_tail > 0.01:
        m_sweep_conc = cfg.beta_sweep_Fe * g_strong_tail * m_strong_tail / g_sweep
    else:
        m_sweep_conc = 0.0
    m_sweep_conc = min(m_sweep_conc, m_strong_tail)

    # 混磁精矿
    m_mag = m_wm_conc + m_strong_conc + m_sweep_conc
    if m_mag > 0.01:
        g_mag = (g_wmag * m_wm_conc + g_strong * m_strong_conc + g_sweep * m_sweep_conc) / m_mag
    else:
        g_mag = 0.0
    assert_close("混磁精矿品位 g_mag", g_mag, 43.84, 1.00)

    print("\n" + "=" * 60)
    print("全部标定断言通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
