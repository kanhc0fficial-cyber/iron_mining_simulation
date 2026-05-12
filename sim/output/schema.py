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

# ── 第二步：塔磨段 18 个 DCS 变量──────────────────────────────────────────
STEP2_COLUMNS: list[str] = [
    "agg_tm_cyclone_pool_level",          # 泵池液位 (m)
    "agg_tm_cyclone_pool_valve_setpoint", # 泵池水阀位给定 (0~1)
    "MC1_FET503_AI",                      # 泵池加水流量 (m³/s)
    "agg_tm_cyclone_feed_flow",           # 旋流器给矿管道流量 (m³/s)
    "agg_tm_cyclone_pump_freq",           # 三旋给矿泵频率 (Hz)
    "agg_tm_cyclone_pump_current",        # 三旋给矿泵电流 (A)
    "agg_tm_cyclone_sand_valve_setpoint", # 沉砂水阀位给定 (0~1)
    "agg_tm_cyclone_sand_valve_feedback", # 沉砂水阀位反馈 (0~1)
    "agg_tm_cyclone_sand_water_flow",     # 旋流器沉砂加水流量 (m³/s)
    "agg_tm_motor_current",               # 塔磨主电机电流 (A)
    "MC1_TM204_HDZC_1_WD_AI",            # 滑动轴承温度1 (°C)
    "MC1_TM206_HDZC_2_WD_AI",            # 滑动轴承温度2 (°C)
    "MC1_TM204_ZDJ_DZ_A_WD_AI",          # 主电机定子温度A (°C)
    "MC1_TM206_ZDJ_DZ_B_WD_AI",          # 主电机定子温度B (°C)
    "agg_tm_reducer_oil_temp",            # 减速机油池温度 (°C)
    "agg_tm_reducer_outlet_temp",         # 减速机出油口温度 (°C)
    "agg_tm_cyclone_overflow_pool_level", # 旋流器溢流泵池液位 (m)
    "agg_tm_overflow_pump_current",       # 旋流器溢流泵电流 (A)
]

# ── 第三步：浮选段 DCS 变量 + 目标变量（占位，第三步填充）───────────────────
STEP3_COLUMNS: list[str] = []

# ── 当前激活输出列（第一步仅含磁选段）──────────────────────────────────────
OUTPUT_COLUMNS: list[str] = STEP1_COLUMNS + STEP2_COLUMNS + STEP3_COLUMNS
