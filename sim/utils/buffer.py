"""
时滞循环缓冲区。

用于磁选→塔磨（15~30 min）、塔磨→浮选（30~60 min）、
化验时滞（120~240 min）等环节的延迟信号传递。
"""

from __future__ import annotations
import numpy as np


class RingBuffer:
    """固定容量的循环缓冲，支持按步数读取历史值。"""

    def __init__(self, capacity: int, default: float = 0.0) -> None:
        if capacity < 1:
            raise ValueError("capacity 必须 ≥ 1")
        self._buf = np.full(capacity, default, dtype=float)
        self._capacity = capacity
        self._head = 0            # 下一次写入位置

    def push(self, value: float) -> None:
        """写入最新值，覆盖最旧值。"""
        self._buf[self._head] = value
        self._head = (self._head + 1) % self._capacity

    def peek(self, delay_steps: int) -> float:
        """读取 delay_steps 步之前的值（delay_steps=0 为最新写入值）。"""
        if delay_steps < 0 or delay_steps >= self._capacity:
            raise ValueError(
                f"delay_steps={delay_steps} 超出 [0, {self._capacity - 1}]"
            )
        idx = (self._head - 1 - delay_steps) % self._capacity
        return float(self._buf[idx])

    @property
    def capacity(self) -> int:
        return self._capacity
