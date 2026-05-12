"""
通用离散 PID 控制器（含反积分饱和）。
"""

from __future__ import annotations


class PIDController:
    """
    增量式离散 PID，输出限幅，支持反积分饱和（anti-windup）。

    更新方程::

        e   = sp - measurement
        P   = Kp * e
        I  += Ki * e * dt          （饱和时停止积累）
        D   = Kd * (e - e_prev) / dt
        u   = clip(P + I + D, u_min, u_max)
    """

    def __init__(
        self,
        Kp: float,
        Ki: float,
        Kd: float,
        dt: float,
        u_min: float = 0.0,
        u_max: float = 1.0,
        anti_windup: bool = True,
    ) -> None:
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max
        self.anti_windup = anti_windup

        self._integral: float = 0.0
        self._e_prev: float = 0.0

    def reset(self, integral: float = 0.0) -> None:
        self._integral = integral
        self._e_prev = 0.0

    def step(self, setpoint: float, measurement: float) -> float:
        """计算并返回控制输出 u。"""
        e = setpoint - measurement
        derivative = (e - self._e_prev) / self.dt

        # 反积分饱和：仅当输出未饱和时才累积积分
        raw_u = self.Kp * e + self._integral + self.Kd * derivative
        saturated = raw_u < self.u_min or raw_u > self.u_max
        if not (self.anti_windup and saturated):
            self._integral += self.Ki * e * self.dt

        u = max(self.u_min, min(self.u_max, self.Kp * e + self._integral + self.Kd * derivative))
        self._e_prev = e
        return u
