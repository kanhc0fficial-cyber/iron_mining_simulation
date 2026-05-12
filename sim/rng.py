"""
随机数管理：为每个子系统分配独立、可复现的 np.random.Generator。
"""

from __future__ import annotations
import numpy as np


class RNGFactory:
    """
    以主种子派生出各子系统专用的随机数生成器。

    相同 master_seed 下调用相同名称序列，保证整体可复现性。
    """

    def __init__(self, master_seed: int) -> None:
        self._master_rng = np.random.default_rng(master_seed)
        self._registry: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        """返回指定名称的专用 Generator；同名每次返回同一实例。"""
        if name not in self._registry:
            seed = int(self._master_rng.integers(0, 2**31))
            self._registry[name] = np.random.default_rng(seed)
        return self._registry[name]
