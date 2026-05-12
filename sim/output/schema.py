"""
输出列名与单位注册表。

本文件按仿真阶段分区管理列名：
  STEP1_COLUMNS : 磁选段 DCS 变量（第一步交付）
  STEP2_COLUMNS : 塔磨段 DCS 变量（第二步追加）
  STEP3_COLUMNS : 浮选段 DCS 变量 + 目标变量（第三步追加）

OUTPUT_COLUMNS  : 当前激活的输出列（由 Simulator 根据构建阶段选取）。
以 '_x_' 开头的 bus 键不写入输出文件。
"""

from __future__ import annotations

# ── 第一步：磁选段 12 个 DCS 变量 ───────────────────────────────────────────
STEP1_COLUMNS: list[str] = [
    "agg_mag_excit_voltage",          # 励磁电压 (V)
    "agg_mag_excit_current",          # 励磁电流 (A)
    "agg_mag_coil_temp",              # 线圈温度 (°C)
    "agg_mag_tailings_valve1",        # 尾矿阀1开度 (0~1)
    "agg_mag_tailings_valve2",        # 尾矿阀2开度 (0~1)
    "agg_mag_blowdown_valve",         # 排污阀开度 (0~1)
    "agg_mag_pulsation_freq",         # 脉动频率 (/min)
    "agg_mag_ring_freq",              # 转环频率 (Hz)
    "agg_mag_level",                  # 选矿液位 (m)
    "agg_mag_flush_water_pressure",   # 冲矿水压力 (MPa)
    "agg_mag_motor_current_rc",       # 主电机A相电流 (A)
    "agg_mag_motor_voltage_rc",       # 主电机BC线电压 (V)
]

# ── 第二步：塔磨段 18 个 DCS 变量（占位，第二步填充）────────────────────────
STEP2_COLUMNS: list[str] = []

# ── 第三步：浮选段 DCS 变量 + 目标变量（占位，第三步填充）───────────────────
STEP3_COLUMNS: list[str] = []

# ── 当前激活输出列（第一步仅含磁选段）──────────────────────────────────────
OUTPUT_COLUMNS: list[str] = STEP1_COLUMNS + STEP2_COLUMNS + STEP3_COLUMNS
