"""
球磨溢流边界输入层。

3 条球磨线并联，各量用 AR(1) 过程模拟慢变波动。
f_{-25μm} 由 d80 经反 S 形函数计算，代表超细粒含量。
"""

from __future__ import annotations
import numpy as np
from scipy.special import expit  # sigmoid，避免溢出

from sim.config import BallMillConfig


class BallMillInput:
    """
    读取 bus 中 _x_d3（可磨性系数），
    写入以下隐藏物理量（_x_ 前缀，不落盘）：
      _x_m_ball   : 球磨溢流质量流量（t/h，三线合计）
      _x_rho_ball : 球磨溢流浓度（质量分数）
      _x_d80_ball : 球磨溢流 d80 粒度（mm）
      _x_f25_ball : 球磨溢流 -25μm 超细粒含量（质量分数）
    """

    def __init__(self, cfg: BallMillConfig, rng: np.random.Generator) -> None:
        self._cfg = cfg
        self._rng = rng

        # AR(1) 过程残差初始化
        self._xi_m: float = 0.0
        self._xi_rho: float = 0.0
        self._xi_d80: float = 0.0

    def step(self, bus: dict) -> None:
        cfg = self._cfg

        # d3 影响 d80（可磨性越好，d80 越小，粒度越细）
        # 此处用简单的乘性修正
        d3 = bus.get("_x_d3", cfg.d3_default if hasattr(cfg, "d3_default") else 1.0)

        # AR(1) 更新（三线共用同一残差，表示高相关）
        self._xi_m = (cfg.m_ball_phi * self._xi_m
                      + self._rng.normal(0.0, cfg.m_ball_sigma))
        self._xi_rho = (cfg.rho_ball_phi * self._xi_rho
                        + self._rng.normal(0.0, cfg.rho_ball_sigma))
        self._xi_d80 = (cfg.d80_ball_phi * self._xi_d80
                        + self._rng.normal(0.0, cfg.d80_ball_sigma))

        # 各线 m_ball（加行间独立小扰动以模拟 rho_lines < 1 相关性）
        m_shared = cfg.m_ball_mean + self._xi_m
        m_ball_total = 0.0
        for _ in range(cfg.n_lines):
            # 行间独立扰动（独立分量占 (1-rho_lines) 比例）
            ind_noise = self._rng.normal(
                0.0, cfg.m_ball_sigma * np.sqrt(1.0 - cfg.rho_lines)
            )
            m_line = m_shared + ind_noise
            m_ball_total += float(np.clip(m_line, cfg.m_ball_min, cfg.m_ball_max))

        # 浓度
        rho_ball = float(np.clip(
            cfg.rho_ball_mean + self._xi_rho,
            cfg.rho_ball_min, cfg.rho_ball_max,
        ))

        # d80（受可磨性修正）
        d80_raw = cfg.d80_ball_mean / d3 + self._xi_d80
        d80_ball = float(np.clip(d80_raw, cfg.d80_ball_min, cfg.d80_ball_max))

        # f_{-25μm}：反 S 形函数
        # f25 = f25_max * sigmoid(k_f25 * (d80_ref - d80)) + noise
        f25_noise = self._rng.normal(0.0, cfg.sigma_f25)
        f25 = float(np.clip(
            cfg.f25_max * float(expit(cfg.k_f25 * (cfg.d80_ref - d80_ball))) + f25_noise,
            0.0, 1.0,
        ))

        bus["_x_m_ball"] = m_ball_total
        bus["_x_rho_ball"] = rho_ball
        bus["_x_d80_ball"] = d80_ball
        bus["_x_f25_ball"] = f25
