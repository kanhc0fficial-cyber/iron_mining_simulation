"""
热力学一阶 ODE 辅助类（前向欧拉离散化）。

方程：τ * dT/dt = Q_heat - k_cool * (T - T_amb)
"""

from __future__ import annotations
import numpy as np


class FirstOrderThermal:
    """
    通用热力学一阶惰性模型。

    参数
    ----
    tau      : 热时间常数（s）
    k_cool   : 散热系数（W/°C），稳态时 T_ss = T_amb + Q_heat/k_cool
    T_init   : 初始温度（°C）
    """

    def __init__(self, tau: float, k_cool: float, T_init: float) -> None:
        if tau <= 0:
            raise ValueError("tau 必须为正数")
        if k_cool <= 0:
            raise ValueError("k_cool 必须为正数")
        self.tau = tau
        self.k_cool = k_cool
        self.T = T_init

    def step(
        self,
        Q_heat: float,
        T_amb: float,
        dt: float,
        noise: float = 0.0,
    ) -> float:
        """
        前向欧拉步进一步，返回更新后的温度。

        参数
        ----
        Q_heat : 输入热功率（W）
        T_amb  : 环境/冷却介质温度（°C）
        dt     : 时间步长（s）
        noise  : 附加高斯噪声（已采样，直接叠加）
        """
        dT = (Q_heat - self.k_cool * (self.T - T_amb)) / self.tau
        self.T += dT * dt + noise
        return self.T

    @property
    def steady_state_temp(self) -> float:
        """稳态温度（只读）。

        基于当前 self.T 和内部参数无法直接计算（需要外部提供 Q_heat）；
        请在调用处直接使用：
            T_ss = T_amb + Q_heat / k_cool
        """
        raise NotImplementedError(
            "请直接计算: T_ss = T_amb + Q_heat / k_cool"
        )
