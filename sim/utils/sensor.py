"""
传感器噪声、漂移与故障注入模型。
"""

from __future__ import annotations
import numpy as np


def add_noise(val: float, sigma: float, rng: np.random.Generator) -> float:
    """在测量值上叠加零均值高斯白噪声。"""
    return val + rng.normal(0.0, sigma)


def add_drift(
    val: float,
    b: float,
    sigma_b: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """
    随机游走漂移模型。

    参数
    ----
    val     : 真实物理量
    b       : 当前漂移偏置
    sigma_b : 漂移步噪声（每步标准差）
    rng     : 随机数生成器

    返回
    ----
    (observed, b_new)
        observed : 含漂移的观测值
        b_new    : 更新后的漂移偏置
    """
    b_new = b + rng.normal(0.0, sigma_b)
    return val + b_new, b_new


def inject_fault(
    val: float,
    p_fault: float,
    fault_val: float,
    rng: np.random.Generator,
) -> float:
    """以概率 p_fault 将测量值替换为异常值 fault_val。"""
    return fault_val if rng.random() < p_fault else val
