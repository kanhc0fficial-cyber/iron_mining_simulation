"""
第0层：外生扰动过程 d(t)。

驱动方式：相关 Ornstein-Uhlenbeck 过程（含物理范围硬约束）。
d1/d2 之间具有地质相关性（Cholesky 分解生成相关噪声）。
"""

from __future__ import annotations
import numpy as np

from sim.config import DisturbanceConfig


class DisturbanceLayer:
    """
    每步输出 4 个隐藏扰动量，写入 bus（_x_ 前缀，不落盘）：
      _x_d1 : 球磨溢流 TFe 品位
      _x_d2 : 碳酸铁含量
      _x_d3 : 矿石可磨性系数
      _x_d4 : 公共管网水压 (MPa)
    """

    def __init__(
        self,
        cfg: DisturbanceConfig,
        rng: np.random.Generator,
        open_loop: bool = False,
    ) -> None:
        self._cfg = cfg
        self._rng = rng
        self._open_loop = open_loop

        # OU 过程残差初始化为 0（预热阶段自然收敛到稳态分布）
        self._xi_d1: float = 0.0
        self._xi_d2: float = 0.0
        self._xi_d3: float = 0.0
        self._xi_d4: float = 0.0

        # 预计算 d1-d2 Cholesky 分解矩阵（正常模式和开环模式各一份）
        # L = [[s1, 0], [rho*s2, s2*sqrt(1-rho²)]]
        s2 = cfg.d2_sigma
        rho = cfg.cov_d1d2

        def _make_L(s1: float) -> np.ndarray:
            return np.array([
                [s1, 0.0],
                [rho * s2, s2 * np.sqrt(max(1.0 - rho ** 2, 0.0))],
            ])

        self._L_normal = _make_L(cfg.d1_sigma)
        self._L_open = _make_L(cfg.d1_sigma * cfg.d1_sigma_open_factor)

    def step(self, bus: dict) -> None:
        """推进一步，将 _x_d1~d4 写入 bus。"""
        cfg = self._cfg

        # d1/d2：相关 OU 噪声（开环模式下扩大 d1 扰动幅度）
        z = self._rng.standard_normal(2)
        L = self._L_open if self._open_loop else self._L_normal
        eta12 = L @ z                           # shape (2,)

        self._xi_d1 = cfg.d1_phi * self._xi_d1 + eta12[0]
        self._xi_d2 = cfg.d2_phi * self._xi_d2 + eta12[1]

        # d3/d4：独立 OU 噪声
        self._xi_d3 = cfg.d3_phi * self._xi_d3 + self._rng.normal(0.0, cfg.d3_sigma)
        self._xi_d4 = cfg.d4_phi * self._xi_d4 + self._rng.normal(0.0, cfg.d4_sigma)

        # 加均值并硬约束到物理范围
        d1 = float(np.clip(cfg.d1_mean + self._xi_d1, cfg.d1_min, cfg.d1_max))
        d2 = float(np.clip(cfg.d2_mean + self._xi_d2, cfg.d2_min, cfg.d2_max))
        d3 = float(np.clip(cfg.d3_mean + self._xi_d3, cfg.d3_min, cfg.d3_max))
        d4 = float(np.clip(cfg.d4_mean + self._xi_d4, cfg.d4_min, cfg.d4_max))

        bus["_x_d1"] = d1
        bus["_x_d2"] = d2
        bus["_x_d3"] = d3
        bus["_x_d4"] = d4
