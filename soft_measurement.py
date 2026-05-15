#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软测量/soft_measurement.py
===========================
基于多种机器学习方法的浮选精矿品位软测量
支持两个出矿口（新一线 xin1、新二线 xin2）的品位预测

方法：
  1. ElasticNet  — 结合 L1+L2 正则化的线性回归模型
  2. SVR         — 支持向量回归（RBF 核）
  3. GPR         — 高斯过程回归（为控制计算量对训练集子采样）
  4. XGBoost     — 极端梯度提升（引入二阶导数和正则化项）
  5. LightGBM    — 基于直方图和叶子生长策略的高效梯度提升树
  6. LSTM        — 单向长短期记忆网络（因果时序，适用于在线软测量）

时延对齐（可选，需先运行 lag_detector.py）：
  若 软测量/结果/lag_analysis_<outlet>.csv 存在，将自动读取每个特征的最优
  滞后（dominant_lag），并对每列独立做 np.roll + NaN 填充，使各特征提前
  对应步数。相比统一平移，该策略能更好地利用非同步的过程动态信息。

数据来源：
  data/modeling_dataset_xin1_final.parquet  — 新一线特征 + 品位目标
  data/modeling_dataset_xin2_final.parquet  — 新二线特征 + 品位目标

输出：
  软测量/结果/metrics_summary.csv          — 所有模型在两个出矿口的评估指标
  软测量/结果/prediction_<outlet>.png      — 预测值 vs 真实值折线图
  软测量/结果/scatter_<outlet>.png         — 散点图（每个模型）
  软测量/结果/lag_analysis_<outlet>.csv    — 由 lag_detector.py 生成的各特征滞后表

运行顺序（推荐）：
  1. python 软测量/lag_detector.py          # 生成各特征最优滞后 CSV
  2. python 软测量/soft_measurement.py      # 软测量建模（自动读取滞后 CSV）

或直接运行（跳过滞后对齐）：
  python 软测量/soft_measurement.py
"""

import os
import sys
import time
import argparse
from datetime import datetime
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import VarianceThreshold, SelectKBest, mutual_info_regression
from sklearn.linear_model import ElasticNetCV
from sklearn.svm import SVR
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel, ConstantKernel as C
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

import xgboost as xgb
import lightgbm as lgb
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# 设置标准输出编码为 UTF-8，避免 Windows 控制台打印特殊字符（如 R²）报错
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

warnings.filterwarnings("ignore")
plt.rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ═══════════════════════════════════════════════════════════════════════════
#  路径配置
# ═══════════════════════════════════════════════════════════════════════════
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(ROOT, "data")
SIMULATION_DATASET = r"C:\Users\goldenwhale\Downloads\my_mining_simulation\output\simulation_10months_rerun_20260514_openloop.parquet"
_BASE_RESULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "结果")
_RUN_TAG     = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULT_DIR   = os.path.join(_BASE_RESULT, _RUN_TAG)
os.makedirs(RESULT_DIR, exist_ok=True)
# lag_detector 产出的 CSV 固定放在 结果/ 根目录，软测量只读不写
LAG_RESULT_DIR = _BASE_RESULT

# X_anchored：221过程变量 + 20化验指标(已ffill) + 2个Y列（稀疏化验值，未填充）
# 全时间轴，200468行，1min频率；Y列为 NaN=未化验，非NaN=当班实测值
DS_XIN1 = SIMULATION_DATASET
DS_XIN2 = SIMULATION_DATASET

# ═══════════════════════════════════════════════════════════════════════════
#  全局超参数
# ═══════════════════════════════════════════════════════════════════════════
MAX_LAG_MI       = 10    # max-lag MI 扫描的最大滞后步数（快速批跑默认值）
VAL_RATIO        = 0.10  # 验证集比例（从训练集末尾切出，用于 early stopping）
TEST_RATIO       = 0.20  # 测试集比例（时序分割，不打乱顺序，最终评估专用）
RANDOM_SEED      = 42
SPARSIFY_TARGET_BY_LAB = True
LAB_FEATURE_MODE = "upstream"
FORBIDDEN_LAB_PREFIXES = ("lab_flo_",)

# ── 时延对齐配置 ────────────────────────────────────────────────────────────
USE_LAG_ALIGN    = True
LAG_MODE         = "dominant"
LAG_CAP          = 30

# ── 特征选择（仅 SVR / GPR 使用 MI 预筛，其他模型直接用全量特征）────────────
# K_FEATURES_SEL：SVR/GPR 专用，Top-40 降维减少核矩阵代价
K_FEATURES_SEL   = 30
# MI 预对齐随机锚点采样：从全量时序的合法锚点 t∈[0, n-max_lag) 中随机抽取此数量
# MI 只依赖散点分布而不依赖样本顺序，随机采样不破坏 lag 语义，且无分段拼接边界污染
MI_SUBSAMPLE     = 5000

# GPR
GPR_MAX_SAMPLES  = 200
# SVR 训练样本上限（rbf-SVR 复杂度 O(n²~n³)，超过 10k 极慢）
SVR_MAX_SAMPLES  = 2000

# 常规模型 Optuna 小预算：覆盖方法为主，避免耗时过长
LINEAR_OPTUNA_TRIALS   = 8
SVR_OPTUNA_TRIALS      = 8
BOOSTING_OPTUNA_TRIALS = 10
LINEAR_MAX_TRAIN_SAMPLES = 50000
BOOSTING_MAX_TRAIN_SAMPLES = 50000

# LSTM 固定超参
# 时间分辨率 1 min/步，150 min ≈ 150 步
LSTM_SEQ_LEN        = 150
LSTM_EPOCHS         = 25
LSTM_PATIENCE       = 4

# LSTM Optuna 搜索配置
LSTM_USE_OPTUNA     = False  # LSTM 较慢，默认不用 Optuna；可用 --lstm-optuna 开启
LSTM_OPTUNA_TRIALS  = 3      # 搜索轮次
LSTM_OPTUNA_EPOCHS  = 8      # 每轮最大 epoch（快速评估）
LSTM_OPTUNA_PAT     = 2      # 每轮早停 patience

# 以下仅作默认值，实际由 Optuna 覆盖
LSTM_HIDDEN      = 32
LSTM_LAYERS      = 1
LSTM_DROPOUT     = 0.1
LSTM_LR          = 1e-3
LSTM_BATCH       = 64
DEEP_EPOCHS      = 25
DEEP_PATIENCE    = 4
DEEP_MAX_TRAIN_WINDOWS = 12000
DEEP_MAX_VAL_WINDOWS   = 3000
MLP_MAX_TRAIN_SAMPLES  = 50000
MLP_MAX_VAL_SAMPLES    = 10000

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

OUTLET_CFG = {
    "xin1": {
        "dataset": DS_XIN1,
        "y_col": "y_fx_xin1",
        "target_sample_col": "lab_flo_conc_tfe_s1",
        "label": "仿真新一线精矿品位",
        "use_lag_align": False,
    },
    "xin2": {
        "dataset": DS_XIN2,
        "y_col": "y_fx_xin2",
        "target_sample_col": "lab_flo_conc_tfe_s2",
        "label": "仿真新二线精矿品位",
        "use_lag_align": False,
    },
}

# 执行顺序：快模型先出结果，慢模型（SVR、LSTM）置后
# 暂时仅启用 LSTM（稀疏化验标签训练模式）
def set_simulation_dataset(dataset_path: str):
    for cfg in OUTLET_CFG.values():
        cfg["dataset"] = dataset_path


def select_feature_columns(df: pd.DataFrame, y_col: str) -> list[str]:
    """Select model inputs while preventing final/flotation assay leakage."""
    feat_cols: list[str] = []
    removed_forbidden_lab = 0
    removed_other_lab = 0
    for col in df.columns:
        if col == y_col:
            continue
        if col.startswith(FORBIDDEN_LAB_PREFIXES):
            removed_forbidden_lab += 1
            continue
        if col.startswith("lab_") and LAB_FEATURE_MODE == "none":
            removed_other_lab += 1
            continue
        feat_cols.append(col)
    print(
        f"  [特征选择] lab_features={LAB_FEATURE_MODE}; "
        f"禁用浮选 lab={removed_forbidden_lab} 列；"
        f"额外禁用其他 lab={removed_other_lab} 列"
    )
    return feat_cols


MODEL_NAMES = [
    "ElasticNet",
    "HistGBDT",
    "HistGBDT-Temporal",
    "LightGBM",
    "XGBoost",
    "GPR",
    "SVR",
    "MLP",
    "GRU",
    "TCN",
    "LSTM",
]


# ═══════════════════════════════════════════════════════════════════════════
#  LSTM 模型定义（单向，适用于因果时序软测量）
# ═══════════════════════════════════════════════════════════════════════════
class LSTMRegressor(nn.Module):
    """单向 LSTM 回归网络：seq_len × n_features → 1 标量

    单向设计确保 t 时刻预测仅依赖 t 及之前的信息，符合在线软测量的因果性要求。
    """

    def __init__(self, n_features: int, hidden: int = 64, n_layers: int = 2,
                 dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden,
            num_layers=n_layers,
            batch_first=True,
            bidirectional=False,
            dropout=dropout if n_layers > 1 else 0.0,
        )
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, seq_len, n_features)
        out, _ = self.lstm(x)          # out: (B, seq_len, hidden)
        last    = out[:, -1, :]        # 取最后一个时间步
        return self.head(self.drop(last)).squeeze(-1)


class GRURegressor(nn.Module):
    """单向 GRU 时序回归网络，作为 LSTM 的轻量对照。"""

    def __init__(self, n_features: int, hidden: int = 32, n_layers: int = 1,
                 dropout: float = 0.1):
        super().__init__()
        self.gru = nn.GRU(
            input_size=n_features,
            hidden_size=hidden,
            num_layers=n_layers,
            batch_first=True,
            bidirectional=False,
            dropout=dropout if n_layers > 1 else 0.0,
        )
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.gru(x)
        return self.head(self.drop(out[:, -1, :])).squeeze(-1)


class TCNRegressor(nn.Module):
    """小型因果卷积网络，覆盖 CNN/TCN 类软测量基线。"""

    def __init__(self, n_features: int, hidden: int = 32, dropout: float = 0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(n_features, hidden, kernel_size=5, padding=4, dilation=1),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Conv1d(hidden, hidden, kernel_size=5, padding=8, dilation=2),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = x.transpose(1, 2)
        z = self.net(z)
        z = z[:, :, :x.shape[1]]
        return self.head(z[:, :, -1]).squeeze(-1)


class MLPRegressor(nn.Module):
    """当前时刻特征的前馈神经网络基线。"""

    def __init__(self, n_features: int, hidden: int = 128, dropout: float = 0.15):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features, hidden),
            nn.ReLU(),
            nn.BatchNorm1d(hidden),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


# ═══════════════════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════════════════
def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """计算 R², RMSE, MAE（自动跳过 NaN，适应稀疏化验标签）"""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if mask.sum() < 2:
        return {"R2": float("nan"), "RMSE": float("nan"), "MAE": float("nan")}
    yt, yp = y_true[mask], y_pred[mask]
    r2   = r2_score(yt, yp)
    rmse = np.sqrt(mean_squared_error(yt, yp))
    mae  = mean_absolute_error(yt, yp)
    return {"R2": round(r2, 4), "RMSE": round(rmse, 4), "MAE": round(mae, 4)}


def subsample_indices(indices: np.ndarray, max_samples: int,
                      random_state: int = RANDOM_SEED) -> np.ndarray:
    """固定随机种子抽样，保持索引升序，避免长周期密集标签训练过慢。"""
    indices = np.asarray(indices, dtype=np.int64)
    if max_samples <= 0 or len(indices) <= max_samples:
        return indices
    rng = np.random.default_rng(random_state)
    return np.sort(rng.choice(indices, size=max_samples, replace=False))


def compute_max_lag_mi_scores(X: np.ndarray, y: np.ndarray,
                              max_lag: int = MAX_LAG_MI,
                              random_state: int = RANDOM_SEED) -> np.ndarray:
    """对每个特征列，在 lag ∈ [0, max_lag] 上分别计算互信息，取最大值作为得分。

    采用预对齐随机锚点采样：先确定所有物理合法的锚点集合 t ∈ [0, n-max_lag)，
    使得对任意 lag，x[t] 与 y[t+lag] 均在边界内且配对正确，再从中随机采样
    MI_SUBSAMPLE 个锚点。MI 只依赖散点分布而不依赖样本顺序，因此随机采样
    不破坏 lag 语义，且完全消除了分段拼接引入的跨段边界污染问题。

    [报告] MI 预筛仅服务于 SVR 和 GPR：这两个核方法对维度敏感，降到 Top-40
    后核矩阵代价显著下降。ElasticNet / XGBoost / LightGBM 直接用全量特征。
    """
    n, d = X.shape
    n_valid = n - max_lag  # 合法锚点 t 满足 t + max_lag < n
    if n_valid > MI_SUBSAMPLE:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(n_valid, size=MI_SUBSAMPLE, replace=False)
        print(f"  [MI 采样] {MI_SUBSAMPLE}/{n_valid} 预对齐随机锚点（无边界污染）")
    else:
        idx = np.arange(n_valid)
    scores = np.zeros(d, dtype=np.float64)
    for col_idx in range(d):
        x_col = X[:, col_idx]
        best_mi = 0.0
        for lag in range(0, max_lag + 1):
            x_lag = x_col[idx]
            y_lag = y[idx + lag]
            mi = mutual_info_regression(
                x_lag.reshape(-1, 1), y_lag,
                random_state=random_state
            )[0]
            if mi > best_mi:
                best_mi = mi
        scores[col_idx] = best_mi
    return scores


def load_lag_table(outlet_key: str) -> dict[str, int] | None:
    """读取 lag_detector.py 产出的滞后 CSV，返回 {feature_name: lag} 字典。

    优先从 LAG_RESULT_DIR（结果/根目录）读取，lag_detector.py 产出固定写在那里。
    """
    csv_path = os.path.join(LAG_RESULT_DIR, f"lag_analysis_{outlet_key}.csv")
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    if LAG_MODE == "ccf":
        lag_col = "ccf_lag"
    elif LAG_MODE == "mi":
        lag_col = "mi_lag"
    else:
        lag_col = "dominant_lag" if "dominant_lag" in df.columns else "mi_lag"
    lag_map = {}
    for _, row in df.iterrows():
        lag = int(row[lag_col])
        lag = min(lag, LAG_CAP)
        lag_map[str(row["feature"])] = lag
    return lag_map


def apply_per_feature_lags(X: np.ndarray, feat_names: list[str],
                           lag_map: dict[str, int]) -> np.ndarray:
    """对特征矩阵逐列应用各自最优滞后（历史对齐，消除前瞻偏差）。

    语义：lag_detector 定义 lag=k 表示 x_i[t] 与 y[t+k] 关联最强，
    即 x_i 超前 y 发生 k 步。预测 y[t] 时应使用 x_i[t-k]（历史值）。

    实现：np.roll(+k) 将位置 t 的值替换为 arr[t-k]，即用历史 k 步的 x。
    头部 k 个位置因卷绕无效，置 NaN 后由后续 ffill 补全。

    ⚠️  注意方向：roll(+k) 向后移，roll(-k) 向前移（读取未来，产生泄漏）。

    Args:
        X:          原始特征矩阵，形状 (n, d)，dtype float32/float64
        feat_names: 与列对应的特征名列表，长度 = d
        lag_map:    {feature_name: lag_steps} 字典（来自 load_lag_table）

    Returns:
        X_aligned:  对齐后的特征矩阵，形状 (n, d)
    """
    X_out     = X.copy().astype(np.float64)
    n         = X_out.shape[0]
    lag_applied = 0
    lag_zero    = 0

    for col_idx, feat in enumerate(feat_names):
        lag = lag_map.get(feat, 0)
        if lag <= 0 or lag >= n:
            lag_zero += 1
            continue
        # 向后滚动 lag 步：位置 t 得到 arr[t-k]（历史值），无前瞻
        X_out[:, col_idx] = np.roll(X_out[:, col_idx], lag)
        # 头部 lag 个位置因卷绕无效，置 NaN 供后续 ffill
        X_out[:lag, col_idx] = np.nan
        lag_applied += 1

    print(f"    滞后对齐：{lag_applied} 列已移位（向后），{lag_zero} 列滞后=0（跳过）")
    return X_out


def make_sequences(X: np.ndarray, y: np.ndarray,
                   seq_len: int) -> tuple[np.ndarray, np.ndarray]:
    """将 2D 时序数组切分为滑动窗口序列。

    Args:
        X:       (n_samples, n_features)
        y:       (n_samples,)
        seq_len: 窗口长度

    Returns:
        X_seq:   (n_samples - seq_len + 1, seq_len, n_features)
        y_seq:   (n_samples - seq_len + 1,)  — 对应每个窗口末尾的目标值
    """
    n = len(X)
    xs, ys = [], []
    for i in range(seq_len - 1, n):
        xs.append(X[i - seq_len + 1: i + 1])
        ys.append(y[i])
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)



def load_and_prepare(outlet_key: str):
    """加载数据、时延对齐、特征预处理、三段分割、标准化。

    返回两套特征集（特征选择策略按模型差异化）：
      full: 全量特征（方差过滤后，约 221 列）→ ElasticNet / XGBoost / LightGBM / LSTM
      sel:  MI 预筛 Top-K_FEATURES_SEL（约 40 列）→ SVR / GPR（核方法需降维）

    数据切分（按时间，不打乱）：
      train 70% | val 10% | test 20%
    """
    cfg   = OUTLET_CFG[outlet_key]
    y_col = cfg["y_col"]

    print(f"\n{'='*60}")
    print(f"  出矿口：{cfg['label']} ({outlet_key})")
    print(f"{'='*60}")

    # ── 1. 读取数据 ──────────────────────────────────────────────
    df = pd.read_parquet(cfg["dataset"])
    if "t" in df.columns:
        df = df.sort_values("t")
        # Simulation data uses integer minutes from start instead of a real timestamp.
        # Convert it to a minute-spaced DatetimeIndex so lab-age features keep the
        # same meaning as the real-data pipeline, then remove t from model inputs.
        minute_offset = pd.to_timedelta(df["t"].to_numpy(), unit="min")
        df.index = pd.Timestamp("2026-01-01") + minute_offset
        df.index.name = "time"
        df = df.drop(columns=["t"])
    else:
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "time"
        df = df.sort_index()

    other_y = "y_fx_xin2" if outlet_key == "xin1" else "y_fx_xin1"
    if other_y in df.columns:
        df = df.drop(columns=[other_y])

    # 保留原始稀疏化验值（NaN 表示该时刻无化验记录），不做任何填充
    target    = df[y_col].values.astype(np.float32)
    if SPARSIFY_TARGET_BY_LAB:
        sample_col = cfg.get("target_sample_col")
        if sample_col and sample_col in df.columns:
            sample_mask = df[sample_col].notna().to_numpy()
            dense_count = int(np.sum(~np.isnan(target)))
            target = target.copy()
            target[~sample_mask] = np.nan
            print(
                f"  [目标稀疏化] {y_col} 原有效值={dense_count}；"
                f"按 {sample_col} 采样保留={int(sample_mask.sum())}"
            )
        else:
            print(f"  [目标稀疏化] 未找到采样列 {sample_col}，保留原始 {y_col}")
    feat_cols = select_feature_columns(df, y_col)
    X_raw     = df[feat_cols].values.astype(np.float32)

    n_valid_y = int(np.sum(~np.isnan(target)))
    print(f"  原始特征维度：{X_raw.shape[1]}，样本数：{len(X_raw)}")
    print(f"  化验有效值数：{n_valid_y}（稀疏率={n_valid_y/len(target):.2%}）")

    # ── 1b. 按特征独立滞后对齐（若 lag_analysis CSV 存在） ───────
    if cfg.get("use_lag_align", USE_LAG_ALIGN):
        lag_map = load_lag_table(outlet_key)
        if lag_map is not None:
            print(f"  [滞后对齐] 读取到 {len(lag_map)} 个特征的最优滞后（模式={LAG_MODE}）")
            X_raw = apply_per_feature_lags(
                X_raw.astype(np.float64), feat_cols, lag_map
            ).astype(np.float32)
        else:
            print(f"  [滞后对齐] 未找到 lag_analysis_{outlet_key}.csv，跳过")

    # Step 2. Chronological train/val/test split.
    n_total   = len(X_raw)
    n_test    = int(n_total * TEST_RATIO)
    n_val     = int(n_total * VAL_RATIO)
    n_train   = n_total - n_val - n_test
    n_val_end = n_train + n_val

    X_train_raw = X_raw[:n_train]
    X_val_raw   = X_raw[n_train:n_val_end]
    X_test_raw  = X_raw[n_val_end:]
    y_train = target[:n_train]
    y_val   = target[n_train:n_val_end]
    y_test  = target[n_val_end:]
    val_index  = df.index[n_train:n_val_end]
    test_index = df.index[n_val_end:]

    print(f"  训练集：{n_train} 条  |  验证集：{n_val} 条  |  测试集：{n_test} 条")

    # ── 3. 方差过滤 + NaN 处理（所有模型共用） ───────────────────
    vt = VarianceThreshold(threshold=1e-4)
    X_tr_vt = vt.fit_transform(X_train_raw)
    X_va_vt = vt.transform(X_val_raw)
    X_te_vt = vt.transform(X_test_raw)
    print(f"  方差阈值后：{X_tr_vt.shape[1]} 个特征")

    X_tr_df   = pd.DataFrame(X_tr_vt).ffill()
    col_means = X_tr_df.mean()
    X_tr_vt   = X_tr_df.fillna(col_means).values
    X_va_vt   = pd.DataFrame(X_va_vt).ffill().fillna(col_means).values
    X_te_vt   = pd.DataFrame(X_te_vt).ffill().fillna(col_means).values


    # ── 4a. 全量特征标准化（ElasticNet / XGBoost / LightGBM / LSTM） ─
    scaler_full  = StandardScaler()
    X_train_full = scaler_full.fit_transform(X_tr_vt)
    X_val_full   = scaler_full.transform(X_va_vt)
    X_test_full  = scaler_full.transform(X_te_vt)

    return (
        X_train_full, X_val_full, X_test_full,    # standardized full features
        X_tr_vt, X_va_vt, X_te_vt,               # unstandardized features for LSTM
        y_train, y_val, y_test,
        val_index, test_index,
    )


def compute_sel_features(X_tr_vt: np.ndarray, X_va_vt: np.ndarray,
                         X_te_vt: np.ndarray, y_train: np.ndarray):
    """MI 预筛 Top-K 特征并标准化，仅供 SVR / GPR 使用（慢步骤，延迟调用）。"""
    k_sel = min(K_FEATURES_SEL, X_tr_vt.shape[1])
    label_mask = ~np.isnan(y_train)
    if label_mask.sum() < 10:
        print("  [MI 预筛 SVR/GPR] 有效标签太少，跳过 MI，使用前若干特征")
        top_idx = np.arange(k_sel)
    else:
        X_mi = X_tr_vt[label_mask]
        y_mi = y_train[label_mask]
        if len(X_mi) > MI_SUBSAMPLE:
            rng = np.random.default_rng(RANDOM_SEED)
            idx = np.sort(rng.choice(len(X_mi), size=MI_SUBSAMPLE, replace=False))
            X_mi, y_mi = X_mi[idx], y_mi[idx]
        print(f"  [MI 预筛 SVR/GPR] {label_mask.sum()} labeled rows，筛选 Top-{k_sel}/{X_tr_vt.shape[1]} 特征")
        mi_scores = mutual_info_regression(X_mi, y_mi, random_state=RANDOM_SEED)
        top_idx   = np.sort(np.argsort(mi_scores)[::-1][:k_sel])
        print(f"  MI 预筛后：{k_sel} 个特征"
              f"（最高分={mi_scores[top_idx[0]]:.4f}  最低分={mi_scores[top_idx[-1]]:.4f}）")
    X_tr_sel  = X_tr_vt[:, top_idx]
    X_va_sel  = X_va_vt[:, top_idx]
    X_te_sel  = X_te_vt[:, top_idx]
    scaler_sel  = StandardScaler()
    X_train_sel = scaler_sel.fit_transform(X_tr_sel)
    X_val_sel   = scaler_sel.transform(X_va_sel)
    X_test_sel  = scaler_sel.transform(X_te_sel)
    return X_train_sel, X_val_sel, X_test_sel


# ═══════════════════════════════════════════════════════════════════════════
#  模型训练与预测
# ═══════════════════════════════════════════════════════════════════════════

def run_elasticnet(X_train, X_val, X_test, y_train, y_val, y_test):
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 10 or val_mask.sum() < 2:
        print("  [ElasticNet] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )
    X_tr, y_tr = X_train[train_mask], y_train[train_mask]
    X_va, y_va = X_val[val_mask], y_val[val_mask]
    tr_idx = subsample_indices(np.arange(len(X_tr)), LINEAR_MAX_TRAIN_SAMPLES)
    X_tr_fit, y_tr_fit = X_tr[tr_idx], y_tr[tr_idx]

    def objective(trial):
        alpha    = trial.suggest_float("alpha",    1e-4, 10.0,  log=True)
        l1_ratio = trial.suggest_float("l1_ratio", 0.0,  1.0)
        from sklearn.linear_model import ElasticNet
        m = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=5000)
        m.fit(X_tr_fit, y_tr_fit)
        return np.sqrt(mean_squared_error(y_va, m.predict(X_va)))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED))
    study.optimize(objective, n_trials=LINEAR_OPTUNA_TRIALS, timeout=120, show_progress_bar=False)

    from sklearn.linear_model import ElasticNet
    bp = study.best_params
    model = ElasticNet(**bp, max_iter=5000)
    model.fit(X_tr_fit, y_tr_fit)
    elapsed = time.time() - t0
    print(f"  [ElasticNet] 最优验证RMSE={study.best_value:.4f}  "
          f"labeled train={train_mask.sum()} fit={len(X_tr_fit)} val={val_mask.sum()}  "
          f"α={bp['alpha']:.4f} l1={bp['l1_ratio']:.2f}  耗时={elapsed:.1f}s")
    return model.predict(X_train), model.predict(X_test)



def run_svr(X_train, X_val, X_test, y_train, y_val, y_test):
    """SVR 随机欠采样控制 O(n²) 复杂度，Optuna 调 C/epsilon/gamma。"""
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 10 or val_mask.sum() < 2:
        print("  [SVR] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )
    X_train_l, y_train_l = X_train[train_mask], y_train[train_mask]
    X_val_l, y_val_l = X_val[val_mask], y_val[val_mask]

    # 先确定训练子集（给 Optuna 和最终训练用同一组索引，保证公平性）
    if len(X_train_l) > SVR_MAX_SAMPLES:
        rng = np.random.default_rng(RANDOM_SEED)
        idx = np.sort(rng.choice(len(X_train_l), size=SVR_MAX_SAMPLES, replace=False))
        X_tr_svr, y_tr_svr = X_train_l[idx], y_train_l[idx]
        print(f"  [SVR 降采样] {SVR_MAX_SAMPLES}/{len(X_train_l)} labeled samples")
    else:
        X_tr_svr, y_tr_svr = X_train_l, y_train_l

    # 验证集同样降采样（与训练集比例相同）
    n_val_sub = min(len(X_val_l), max(2, SVR_MAX_SAMPLES // 4))
    rng2 = np.random.default_rng(RANDOM_SEED + 1)
    val_idx = np.sort(rng2.choice(len(X_val_l), size=n_val_sub, replace=False))
    X_va_svr, y_va_svr = X_val_l[val_idx], y_val_l[val_idx]

    def objective(trial):
        C       = trial.suggest_float("C",       0.1,  500.0, log=True)
        epsilon = trial.suggest_float("epsilon", 1e-3, 1.0,   log=True)
        gamma   = trial.suggest_categorical("gamma", ["scale", "auto"])
        m = SVR(kernel="rbf", C=C, epsilon=epsilon, gamma=gamma)
        m.fit(X_tr_svr, y_tr_svr)
        return np.sqrt(mean_squared_error(y_va_svr, m.predict(X_va_svr)))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED))
    study.optimize(objective, n_trials=SVR_OPTUNA_TRIALS, timeout=180, show_progress_bar=False)

    bp = study.best_params
    model = SVR(kernel="rbf", **bp)
    model.fit(X_tr_svr, y_tr_svr)
    elapsed = time.time() - t0
    print(f"  [SVR]        最优验证RMSE={study.best_value:.4f}  "
          f"C={bp['C']:.2f} ε={bp['epsilon']:.4f}  耗时={elapsed:.1f}s")
    return model.predict(X_train), model.predict(X_test)



def run_gpr(X_train, X_test, y_train, y_test):
    """GPR 随机无放回采样控制 O(n³) 复杂度。

    使用随机采样（固定种子）代替末尾截断，使归纳点覆盖全局分布，
    避免末尾工况偏移导致 GPR 在历史时段完全失效。
    """
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    if train_mask.sum() < 10:
        print("  [GPR] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )
    X_train_l, y_train_l = X_train[train_mask], y_train[train_mask]
    if len(X_train_l) > GPR_MAX_SAMPLES:
        rng  = np.random.default_rng(RANDOM_SEED)
        idx  = rng.choice(len(X_train_l), size=GPR_MAX_SAMPLES, replace=False)
        idx  = np.sort(idx)          # 保持时序顺序（可选，利于 GPR 核函数估计）
        X_tr_gpr = X_train_l[idx]
        y_tr_gpr = y_train_l[idx]
    else:
        X_tr_gpr, y_tr_gpr = X_train_l, y_train_l

    kernel = C(1.0, (1e-2, 1e2)) * RBF(1.0, (1e-2, 1e2)) + WhiteKernel(0.1, (1e-5, 1e1))
    model  = GaussianProcessRegressor(
        kernel=kernel, n_restarts_optimizer=1, random_state=RANDOM_SEED,
        normalize_y=True
    )
    model.fit(X_tr_gpr, y_tr_gpr)
    pred_train = model.predict(X_train)
    pred_test  = model.predict(X_test)
    elapsed = time.time() - t0
    n_sub = len(X_tr_gpr)
    print(f"  [GPR]        子采样={n_sub}/{len(X_train_l)} labeled samples  耗时={elapsed:.1f}s")
    return pred_train, pred_test


def run_xgboost(X_train, X_val, X_test, y_train, y_val, y_test):
    """XGBoost：Optuna 调参 + 验证集 early stopping。"""
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 20 or val_mask.sum() < 2:
        print("  [XGBoost] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )
    X_tr, y_tr = X_train[train_mask], y_train[train_mask]
    X_va, y_va = X_val[val_mask], y_val[val_mask]
    tr_idx = subsample_indices(np.arange(len(X_tr)), BOOSTING_MAX_TRAIN_SAMPLES)
    X_tr_fit, y_tr_fit = X_tr[tr_idx], y_tr[tr_idx]

    def objective(trial):
        params = dict(
            n_estimators        = trial.suggest_int(  "n_estimators",   100, 500),
            learning_rate       = trial.suggest_float("learning_rate",   0.01, 0.3, log=True),
            max_depth           = trial.suggest_int(  "max_depth",       2, 7),
            subsample           = trial.suggest_float("subsample",       0.5, 1.0),
            colsample_bytree    = trial.suggest_float("colsample_bytree",0.4, 1.0),
            reg_alpha           = trial.suggest_float("reg_alpha",       1e-4, 10.0, log=True),
            reg_lambda          = trial.suggest_float("reg_lambda",      1e-4, 10.0, log=True),
            min_child_weight    = trial.suggest_int(  "min_child_weight",1, 10),
            early_stopping_rounds=20, eval_metric="rmse",
            random_state=RANDOM_SEED, verbosity=0, n_jobs=-1, device="cpu",
        )
        m = xgb.XGBRegressor(**params)
        m.fit(X_tr_fit, y_tr_fit, eval_set=[(X_va, y_va)], verbose=False)
        return np.sqrt(mean_squared_error(y_va, m.predict(X_va)))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED))
    study.optimize(objective, n_trials=BOOSTING_OPTUNA_TRIALS, timeout=240, show_progress_bar=False)

    bp = study.best_params
    model = xgb.XGBRegressor(
        **bp, early_stopping_rounds=20, eval_metric="rmse",
        random_state=RANDOM_SEED, verbosity=0, n_jobs=-1, device="cpu",
    )
    model.fit(X_tr_fit, y_tr_fit, eval_set=[(X_va, y_va)], verbose=False)
    elapsed = time.time() - t0
    print(f"  [XGBoost]    最优验证RMSE={study.best_value:.4f}  "
          f"labeled train={train_mask.sum()} fit={len(X_tr_fit)} val={val_mask.sum()}  "
          f"最佳轮次={model.best_iteration}  耗时={elapsed:.1f}s")
    return model.predict(X_train), model.predict(X_test)



def run_lightgbm(X_train, X_val, X_test, y_train, y_val, y_test):
    """LightGBM：Optuna 调参 + 验证集 early stopping。"""
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 20 or val_mask.sum() < 2:
        print("  [LightGBM] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )
    X_tr, y_tr = X_train[train_mask], y_train[train_mask]
    X_va, y_va = X_val[val_mask], y_val[val_mask]
    tr_idx = subsample_indices(np.arange(len(X_tr)), BOOSTING_MAX_TRAIN_SAMPLES)
    X_tr_fit, y_tr_fit = X_tr[tr_idx], y_tr[tr_idx]

    def objective(trial):
        params = dict(
            n_estimators     = trial.suggest_int(  "n_estimators",    100, 500),
            learning_rate    = trial.suggest_float("learning_rate",    0.01, 0.3, log=True),
            max_depth        = trial.suggest_int(  "max_depth",        2, 8),
            num_leaves       = trial.suggest_int(  "num_leaves",       7, 127),
            subsample        = trial.suggest_float("subsample",        0.5, 1.0),
            colsample_bytree = trial.suggest_float("colsample_bytree", 0.4, 1.0),
            reg_alpha        = trial.suggest_float("reg_alpha",        1e-4, 10.0, log=True),
            reg_lambda       = trial.suggest_float("reg_lambda",       1e-4, 10.0, log=True),
            random_state=RANDOM_SEED, verbose=-1, n_jobs=-1,
        )
        m = lgb.LGBMRegressor(**params)
        m.fit(X_tr_fit, y_tr_fit,
              eval_set=[(X_va, y_va)],
              callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(-1)])
        return np.sqrt(mean_squared_error(y_va, m.predict(X_va)))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED))
    study.optimize(objective, n_trials=BOOSTING_OPTUNA_TRIALS, timeout=240, show_progress_bar=False)

    bp = study.best_params
    model = lgb.LGBMRegressor(**bp, random_state=RANDOM_SEED, verbose=-1, n_jobs=-1)
    model.fit(X_tr_fit, y_tr_fit,
              eval_set=[(X_va, y_va)],
              callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(-1)])
    elapsed = time.time() - t0
    print(f"  [LightGBM]   最优验证RMSE={study.best_value:.4f}  "
          f"labeled train={train_mask.sum()} fit={len(X_tr_fit)} val={val_mask.sum()}  "
          f"最佳轮次={model.best_iteration_}  耗时={elapsed:.1f}s")
    return model.predict(X_train), model.predict(X_test)



# ── 辅助：构建稀疏化验窗口数据集 ──────────────────────────────────────────────
def run_histgb_sparse(X_train, X_val, X_test, y_train, y_val, y_test):
    """Histogram GBDT trained only on rows that have assay labels."""
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 20:
        print("  [HistGBDT] too few labeled training rows; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )

    train_idx = subsample_indices(np.flatnonzero(train_mask), BOOSTING_MAX_TRAIN_SAMPLES)
    val_idx = np.flatnonzero(val_mask)
    model = HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.03,
        max_leaf_nodes=15,
        l2_regularization=0.05,
        random_state=RANDOM_SEED,
    )
    model.fit(X_train[train_idx], y_train[train_idx])

    if len(val_idx) >= 2:
        pred_val = model.predict(X_val[val_idx])
        val_rmse = np.sqrt(mean_squared_error(y_val[val_idx], pred_val))
        print(
            f"  [HistGBDT] labeled rows train={train_mask.sum()} "
            f"fit={len(train_idx)} val={val_mask.sum()} val_RMSE={val_rmse:.4f} "
            f"elapsed={time.time() - t0:.1f}s"
        )
    else:
        print(
            f"  [HistGBDT] labeled rows train={train_mask.sum()} "
            f"elapsed={time.time() - t0:.1f}s"
        )

    return model.predict(X_train), model.predict(X_test)


def run_histgb_temporal_sparse(X_train, X_val, X_test, y_train, y_val, y_test):
    """Histogram GBDT with compact lag and rolling features at labeled rows."""
    t0 = time.time()
    X_full = np.concatenate([X_train, X_val, X_test], axis=0).astype(np.float32)
    y_full = np.concatenate([y_train, y_val, y_test]).astype(np.float32)
    n_train = len(X_train)
    n_val = len(X_val)
    train_idx_all = np.flatnonzero(~np.isnan(y_train))
    val_idx_all = n_train + np.flatnonzero(~np.isnan(y_val))
    test_idx = n_train + n_val + np.flatnonzero(~np.isnan(y_test))

    if len(train_idx_all) < 20:
        print("  [HistGBDT-Temporal] too few labeled training rows; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )

    lags = [5, 30, 60, 120]
    windows = [15, 60, 120]
    csum = np.vstack([
        np.zeros((1, X_full.shape[1]), dtype=np.float64),
        np.cumsum(X_full, axis=0, dtype=np.float64),
    ])

    def _rows(indices: np.ndarray) -> np.ndarray:
        blocks = [X_full[indices]]
        for lag in lags:
            block = np.full((len(indices), X_full.shape[1]), np.nan, dtype=np.float32)
            src = indices - lag
            valid = src >= 0
            if valid.any():
                block[valid] = X_full[src[valid]]
            blocks.append(block)
        for window in windows:
            start = np.maximum(0, indices - window + 1)
            count = (indices - start + 1).astype(np.float64)[:, None]
            mean = (csum[indices + 1] - csum[start]) / count
            blocks.append(mean.astype(np.float32))
        return np.hstack(blocks)

    train_idx = subsample_indices(train_idx_all, BOOSTING_MAX_TRAIN_SAMPLES)
    val_idx = subsample_indices(
        val_idx_all, min(len(val_idx_all), 10000), random_state=RANDOM_SEED + 1
    )
    X_tr = _rows(train_idx)
    y_tr = y_full[train_idx]
    model = HistGradientBoostingRegressor(
        max_iter=500,
        learning_rate=0.03,
        max_leaf_nodes=15,
        l2_regularization=0.05,
        random_state=RANDOM_SEED,
    )
    model.fit(X_tr, y_tr)

    if len(val_idx) >= 2:
        pred_val = model.predict(_rows(val_idx))
        val_rmse = np.sqrt(mean_squared_error(y_full[val_idx], pred_val))
        print(
            f"  [HistGBDT-Temporal] labeled rows train={len(train_idx)} "
            f"val={len(val_idx)} features={X_tr.shape[1]} "
            f"val_RMSE={val_rmse:.4f} elapsed={time.time() - t0:.1f}s"
        )
    else:
        print(
            f"  [HistGBDT-Temporal] labeled rows train={len(train_idx)} "
            f"features={X_tr.shape[1]} elapsed={time.time() - t0:.1f}s"
        )

    pred_train = np.full(len(y_train), np.nan, dtype=np.float32)
    pred_test = np.full(len(y_test), np.nan, dtype=np.float32)
    pred_train[train_idx] = model.predict(X_tr)
    if len(test_idx):
        for start in range(0, len(test_idx), 10000):
            idx_batch = test_idx[start:start + 10000]
            pred_test[idx_batch - n_train - n_val] = model.predict(_rows(idx_batch))
    return pred_train, pred_test


def build_sparse_windows(
        X_full_s: np.ndarray,
        y_full: np.ndarray,
        seq_len: int,
        seg_start: int,
        seg_end: int,
        max_windows: int | None = None,
        random_state: int = RANDOM_SEED,
) -> tuple[np.ndarray, np.ndarray]:
    """从全量时序 X_full_s / y_full 中，提取 [seg_start, seg_end) 范围内有化验值的窗口。

    窗口定义（与用户伪代码一致）：对目标索引 i ∈ [seg_start, seg_end)，
      - 特征窗口 = X_full_s[i - seq_len : i]，即 X[i-seq_len] 到 X[i-1]，长度恰好为 seq_len
      - 目标标签 = y_full[i]
    仅当 y_full[i] 不为 NaN 且 i >= seq_len 时，该窗口才纳入数据集。

    Returns:
        X_win: (n_valid, seq_len, n_features)  float32
        y_win: (n_valid,)                       float32
    """
    valid_idx = np.flatnonzero(~np.isnan(y_full[seg_start:seg_end])) + seg_start
    valid_idx = valid_idx[valid_idx >= seq_len]
    if max_windows is not None and len(valid_idx) > max_windows:
        valid_idx = subsample_indices(valid_idx, max_windows, random_state=random_state)

    windows_X, windows_y = [], []
    for i in valid_idx:
        windows_X.append(X_full_s[i - seq_len: i])
        windows_y.append(y_full[i])
    if not windows_X:
        n_feat = X_full_s.shape[1]
        return (np.empty((0, seq_len, n_feat), dtype=np.float32),
                np.empty(0, dtype=np.float32))
    return (np.array(windows_X, dtype=np.float32),
            np.array(windows_y, dtype=np.float32))


def predict_all_sliding(
        model: nn.Module,
        X_s: np.ndarray,
        seq_len: int,
        device: str,
        y_mean: float,
        y_std: float,
        batch_size: int,
) -> np.ndarray:
    """在给定时序上滑动预测，与训练窗口的切片约定保持一致。

    对位置 i，窗口为 X_s[i-seq_len:i]（不含 X[i]），预测对应 y[i]。
    前 seq_len 个位置（无足够历史）返回 NaN。

    Args:
        X_s:   (n, n_features) 已标准化的特征序列
    Returns:
        preds: (n,) float32，索引 0..seq_len-1 为 NaN，其余为反标准化后预测值
    """
    n = len(X_s)
    preds = np.full(n, np.nan, dtype=np.float32)
    if n <= seq_len:
        return preds
    # 对 i in [seq_len, n)，窗口为 X_s[i-seq_len:i]
    all_out = []
    model.eval()
    with torch.no_grad():
        for start in range(seq_len, n, batch_size):
            end = min(start + batch_size, n)
            batch_windows = np.stack(
                [X_s[i - seq_len: i] for i in range(start, end)]
            ).astype(np.float32, copy=False)
            xb = torch.from_numpy(batch_windows).to(device)
            all_out.append(model(xb).cpu().numpy())
    raw = np.concatenate(all_out)       # 长度 n - seq_len
    restored = raw * y_std + y_mean
    preds[seq_len:] = restored
    return preds


def predict_sparse_sliding(
        model: nn.Module,
        X_s: np.ndarray,
        target_indices: np.ndarray,
        seq_len: int,
        device: str,
        y_mean: float,
        y_std: float,
        batch_size: int,
) -> np.ndarray:
    """仅在指定目标索引上做 LSTM 滑窗预测，其他位置保持 NaN。"""
    preds = np.full(len(X_s), np.nan, dtype=np.float32)
    target_indices = np.asarray(target_indices, dtype=np.int64)
    target_indices = target_indices[
        (target_indices >= seq_len) & (target_indices < len(X_s))
    ]
    if len(target_indices) == 0:
        return preds

    model.eval()
    out = []
    with torch.no_grad():
        for start in range(0, len(target_indices), batch_size):
            batch_idx = target_indices[start:start + batch_size]
            batch_windows = np.stack(
                [X_s[i - seq_len: i] for i in batch_idx]
            ).astype(np.float32, copy=False)
            xb = torch.from_numpy(batch_windows).to(device)
            out.append(model(xb).cpu().numpy())
    restored = np.concatenate(out) * y_std + y_mean
    preds[target_indices] = restored
    return preds


def _train_torch_regressor(
        model: nn.Module,
        X_tr: np.ndarray,
        y_tr: np.ndarray,
        X_va: np.ndarray,
        y_va: np.ndarray,
        epochs: int,
        patience: int,
        batch_size: int,
        lr: float,
        name: str,
) -> tuple[nn.Module, float, float]:
    y_mean = float(y_tr.mean())
    y_std = float(y_tr.std() + 1e-8)
    y_tr_n = ((y_tr - y_mean) / y_std).astype(np.float32)
    y_va_n = ((y_va - y_mean) / y_std).astype(np.float32)

    X_tr_t = torch.from_numpy(X_tr.astype(np.float32, copy=False))
    y_tr_t = torch.from_numpy(y_tr_n)
    X_va_t = torch.from_numpy(X_va.astype(np.float32, copy=False)).to(DEVICE)
    y_va_t = torch.from_numpy(y_va_n).to(DEVICE)

    dl_train = DataLoader(
        TensorDataset(X_tr_t, y_tr_t),
        batch_size=batch_size,
        shuffle=True,
        drop_last=False,
    )
    model = model.to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.HuberLoss(delta=1.0)

    best_val = float("inf")
    best_state = None
    patience_cnt = 0
    for epoch in range(1, epochs + 1):
        model.train()
        for xb, yb in dl_train:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(X_va_t), y_va_t).item()
        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_cnt = 0
        else:
            patience_cnt += 1
            if patience_cnt >= patience:
                print(f"    [{name}] early stopped at epoch {epoch} (patience={patience})")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, y_mean, y_std


def run_mlp(X_train_raw, X_val_raw, X_test_raw, y_train, y_val, y_test):
    """MLP 深度学习基线：只在有化验标签的行训练，输出完整测试轴预测。"""
    t0 = time.time()
    train_mask = ~np.isnan(y_train)
    val_mask = ~np.isnan(y_val)
    if train_mask.sum() < 20 or val_mask.sum() < 2:
        print("  [MLP] labeled rows too few; skipped")
        return (
            np.full(len(y_train), np.nan, dtype=np.float32),
            np.full(len(y_test), np.nan, dtype=np.float32),
        )

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_train_raw)
    X_va_s = scaler.transform(X_val_raw)
    X_te_s = scaler.transform(X_test_raw)
    train_idx = subsample_indices(np.flatnonzero(train_mask), MLP_MAX_TRAIN_SAMPLES)
    val_idx = subsample_indices(np.flatnonzero(val_mask), MLP_MAX_VAL_SAMPLES, random_state=RANDOM_SEED + 1)

    model = MLPRegressor(n_features=X_tr_s.shape[1], hidden=128, dropout=0.15)
    model, y_mean, y_std = _train_torch_regressor(
        model,
        X_tr_s[train_idx], y_train[train_idx],
        X_va_s[val_idx], y_val[val_idx],
        epochs=DEEP_EPOCHS,
        patience=DEEP_PATIENCE,
        batch_size=LSTM_BATCH,
        lr=1e-3,
        name="MLP",
    )

    model.eval()
    with torch.no_grad():
        pred_train = model(torch.from_numpy(X_tr_s.astype(np.float32)).to(DEVICE)).cpu().numpy()
        pred_test = model(torch.from_numpy(X_te_s.astype(np.float32)).to(DEVICE)).cpu().numpy()
    pred_train = pred_train * y_std + y_mean
    pred_test = pred_test * y_std + y_mean
    print(
        f"  [MLP] labeled rows train={train_mask.sum()} fit={len(train_idx)} "
        f"val={val_mask.sum()} val_fit={len(val_idx)} elapsed={time.time() - t0:.1f}s"
    )
    return pred_train, pred_test


def run_sequence_deep(X_train_raw, X_val_raw, X_test_raw,
                      y_train, y_val, y_test,
                      model_name: str,
                      seq_len: int = LSTM_SEQ_LEN):
    """GRU/TCN 稀疏标签时序深度学习基线。"""
    t0 = time.time()
    n_train = len(X_train_raw)
    n_val = len(X_val_raw)
    n_test = len(X_test_raw)

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_train_raw)
    X_va_s = scaler.transform(X_val_raw)
    X_te_s = scaler.transform(X_test_raw)
    X_full_s = np.concatenate([X_tr_s, X_va_s, X_te_s], axis=0)
    y_full = np.concatenate([y_train, y_val, y_test]).astype(np.float32)

    tr_start, tr_end = 0, n_train
    va_start, va_end = n_train, n_train + n_val
    te_start, te_end = n_train + n_val, n_train + n_val + n_test
    X_tr_win, y_tr_win = build_sparse_windows(
        X_full_s, y_full, seq_len, tr_start, tr_end,
        max_windows=DEEP_MAX_TRAIN_WINDOWS, random_state=RANDOM_SEED,
    )
    X_va_win, y_va_win = build_sparse_windows(
        X_full_s, y_full, seq_len, va_start, va_end,
        max_windows=DEEP_MAX_VAL_WINDOWS, random_state=RANDOM_SEED + 1,
    )
    X_te_win, y_te_win = build_sparse_windows(
        X_full_s, y_full, seq_len, te_start, te_end,
        max_windows=DEEP_MAX_VAL_WINDOWS, random_state=RANDOM_SEED + 2,
    )
    print(f"  [{model_name}] sparse windows: train={len(X_tr_win)}, val={len(X_va_win)}, test={len(X_te_win)}")
    if len(X_tr_win) < 20 or len(X_va_win) < 2:
        print(f"  [{model_name}] labeled windows too few; skipped")
        return (
            np.full(n_train, np.nan, dtype=np.float32),
            np.full(n_test, np.nan, dtype=np.float32),
        )

    n_features = X_tr_win.shape[2]
    if model_name == "GRU":
        model = GRURegressor(n_features=n_features, hidden=LSTM_HIDDEN,
                             n_layers=LSTM_LAYERS, dropout=LSTM_DROPOUT)
    elif model_name == "TCN":
        model = TCNRegressor(n_features=n_features, hidden=LSTM_HIDDEN,
                             dropout=LSTM_DROPOUT)
    else:
        raise ValueError(f"unsupported deep sequence model: {model_name}")

    model, y_mean, y_std = _train_torch_regressor(
        model,
        X_tr_win, y_tr_win,
        X_va_win, y_va_win,
        epochs=DEEP_EPOCHS,
        patience=DEEP_PATIENCE,
        batch_size=LSTM_BATCH,
        lr=LSTM_LR,
        name=model_name,
    )

    train_label_idx = np.flatnonzero(~np.isnan(y_train))
    test_label_idx = np.flatnonzero(~np.isnan(y_test))
    pred_train = predict_sparse_sliding(
        model, X_full_s[:n_train], train_label_idx, seq_len, DEVICE, y_mean, y_std, LSTM_BATCH
    )
    X_te_ctx = X_full_s[va_end - seq_len: te_end]
    pred_te_ctx = predict_sparse_sliding(
        model, X_te_ctx, test_label_idx + seq_len, seq_len, DEVICE, y_mean, y_std, LSTM_BATCH
    )
    pred_test = pred_te_ctx[seq_len:]
    print(f"  [{model_name}] elapsed={time.time() - t0:.1f}s")
    return pred_train, pred_test


def run_lstm(X_train_raw, X_val_raw, X_test_raw,
             y_train, y_val, y_test,
             seq_len: int = LSTM_SEQ_LEN):
    """Sparse-label LSTM that directly learns the assay y value."""
    t0 = time.time()

    n_train = len(X_train_raw)
    n_val   = len(X_val_raw)
    n_test  = len(X_test_raw)

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_train_raw)
    X_va_s = scaler.transform(X_val_raw)
    X_te_s = scaler.transform(X_test_raw)

    X_full_s = np.concatenate([X_tr_s, X_va_s, X_te_s], axis=0)
    y_full   = np.concatenate([y_train, y_val, y_test]).astype(np.float32)

    tr_start, tr_end = 0,                  n_train
    va_start, va_end = n_train,            n_train + n_val
    te_start, te_end = n_train + n_val,    n_train + n_val + n_test

    X_tr_win, y_tr_win = build_sparse_windows(
        X_full_s, y_full, seq_len, tr_start, tr_end,
        max_windows=DEEP_MAX_TRAIN_WINDOWS, random_state=RANDOM_SEED,
    )
    X_va_win, y_va_win = build_sparse_windows(
        X_full_s, y_full, seq_len, va_start, va_end,
        max_windows=DEEP_MAX_VAL_WINDOWS, random_state=RANDOM_SEED + 1,
    )
    X_te_win, y_te_win = build_sparse_windows(
        X_full_s, y_full, seq_len, te_start, te_end,
        max_windows=DEEP_MAX_VAL_WINDOWS, random_state=RANDOM_SEED + 2,
    )

    print(f"  [LSTM] sparse windows: train={len(X_tr_win)}, val={len(X_va_win)}, test={len(X_te_win)}")
    if len(X_tr_win) == 0:
        print("  [LSTM] no valid training labels; skipped")
        return np.full(n_train, np.nan, dtype=np.float32), np.full(n_test, np.nan, dtype=np.float32)

    n_features = X_tr_win.shape[2]
    y_mean = float(y_tr_win.mean())
    y_std  = float(y_tr_win.std() + 1e-8)
    y_tr_norm = ((y_tr_win - y_mean) / y_std).astype(np.float32)
    y_va_norm = ((y_va_win - y_mean) / y_std).astype(np.float32)
    has_val = len(X_va_win) > 0

    X_tr_t = torch.from_numpy(X_tr_win)
    y_tr_t = torch.from_numpy(y_tr_norm)
    X_va_t = torch.from_numpy(X_va_win).to(DEVICE) if has_val else None
    y_va_np = y_va_norm

    def _objective(trial):
        h  = trial.suggest_categorical("hidden",     [32, 64, 128, 256])
        nl = trial.suggest_int(        "n_layers",   1, 3)
        dr = trial.suggest_float(      "dropout",    0.0, 0.5)
        lr = trial.suggest_float(      "lr",         1e-4, 5e-3, log=True)
        bs = trial.suggest_categorical("batch_size", [16, 32, 64, 128])

        m = LSTMRegressor(n_features=n_features, hidden=h,
                          n_layers=nl, dropout=dr).to(DEVICE)
        opt  = torch.optim.Adam(m.parameters(), lr=lr, weight_decay=1e-4)
        crit = nn.HuberLoss(delta=1.0)
        dl   = DataLoader(TensorDataset(X_tr_t, y_tr_t),
                          batch_size=bs, shuffle=True, drop_last=False)

        best_vl, pat = float("inf"), 0
        for epoch in range(LSTM_OPTUNA_EPOCHS):
            m.train()
            for xb, yb in dl:
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                opt.zero_grad()
                crit(m(xb), yb).backward()
                nn.utils.clip_grad_norm_(m.parameters(), 1.0)
                opt.step()

            if has_val:
                m.eval()
                with torch.no_grad():
                    vp = m(X_va_t).cpu().numpy()
                vl = float(np.sqrt(np.mean((vp - y_va_np) ** 2)))
                trial.report(vl, epoch)
                if trial.should_prune():
                    raise optuna.TrialPruned()
                if vl < best_vl - 1e-4:
                    best_vl, pat = vl, 0
                else:
                    pat += 1
                    if pat >= LSTM_OPTUNA_PAT:
                        break
        return best_vl

    if LSTM_USE_OPTUNA:
        print(f"  [LSTM+Optuna] searching n_trials={LSTM_OPTUNA_TRIALS}...")
        _pruner = optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=10)
        _study  = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED),
            pruner=_pruner,
        )
        _study.optimize(_objective, n_trials=LSTM_OPTUNA_TRIALS,
                        timeout=600, show_progress_bar=False)

        bp = _study.best_params
        print(f"  [LSTM+Optuna] best val RMSE={_study.best_value:.4f}  params={bp}")
        best_hidden  = bp["hidden"]
        best_layers  = bp["n_layers"]
        best_dropout = bp["dropout"]
        best_lr      = bp["lr"]
        best_batch   = bp["batch_size"]
    else:
        best_hidden  = LSTM_HIDDEN
        best_layers  = LSTM_LAYERS
        best_dropout = LSTM_DROPOUT
        best_lr      = LSTM_LR
        best_batch   = LSTM_BATCH
        print("  [LSTM] Optuna disabled; using fixed params: "
              f"hidden={best_hidden}, n_layers={best_layers}, "
              f"dropout={best_dropout}, lr={best_lr}, batch_size={best_batch}")

    dl_train = DataLoader(
        TensorDataset(X_tr_t, y_tr_t),
        batch_size=best_batch, shuffle=True, drop_last=False,
    )
    dl_val = DataLoader(
        TensorDataset(X_va_t.cpu() if X_va_t is not None else torch.empty(0),
                      torch.from_numpy(y_va_norm)),
        batch_size=best_batch, shuffle=False, drop_last=False,
    ) if has_val else None

    model = LSTMRegressor(
        n_features=n_features,
        hidden=best_hidden,
        n_layers=best_layers,
        dropout=best_dropout,
    ).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=best_lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=10, min_lr=1e-5
    )
    criterion = nn.HuberLoss(delta=1.0)

    best_val_loss = float("inf")
    patience_cnt  = 0
    best_state    = None

    for epoch in range(1, LSTM_EPOCHS + 1):
        model.train()
        for xb, yb in dl_train:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        if has_val:
            val_losses = []
            with torch.no_grad():
                for xb, yb in dl_val:
                    xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                    val_losses.append(criterion(model(xb), yb).item())
            val_loss = float(np.mean(val_losses))
        else:
            val_loss = float("inf")

        scheduler.step(val_loss)
        if val_loss < best_val_loss - 1e-5:
            best_val_loss = val_loss
            patience_cnt  = 0
            best_state    = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_cnt += 1
            if patience_cnt >= LSTM_PATIENCE:
                print(f"    early stopped at epoch {epoch} (patience={LSTM_PATIENCE})")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    elapsed = time.time() - t0
    print(f"  [LSTM] final val loss={best_val_loss:.5f}  elapsed={elapsed:.1f}s")

    train_label_idx = np.flatnonzero(~np.isnan(y_train))
    test_label_idx = np.flatnonzero(~np.isnan(y_test))
    pred_train = predict_sparse_sliding(
        model, X_full_s[:n_train], train_label_idx, seq_len, DEVICE, y_mean, y_std, best_batch
    )
    X_te_ctx = X_full_s[va_end - seq_len: te_end]
    pred_te_ctx = predict_sparse_sliding(
        model, X_te_ctx, test_label_idx + seq_len, seq_len, DEVICE, y_mean, y_std, best_batch
    )
    pred_test = pred_te_ctx[seq_len:]

    return pred_train, pred_test


def plot_predictions(outlet_key: str, test_index: pd.DatetimeIndex,
                     y_test: np.ndarray, preds: dict, label: str):
    """测试集上各模型的预测值 vs 真实值折线图（时间轴）。"""
    n_models = len(preds)
    fig, axes = plt.subplots(n_models, 1, figsize=(14, 3 * n_models), sharex=True)
    if n_models == 1:
        axes = [axes]
    fig.suptitle(f"{label} — 测试集预测值 vs 真实值", fontsize=13, y=1.01)

    for ax, (name, pred) in zip(axes, preds.items()):
        valid_mask = ~np.isnan(pred) & ~np.isnan(y_test)
        if valid_mask.sum() < 2:
            r2 = float('nan')
        else:
            r2 = r2_score(y_test[valid_mask], pred[valid_mask])

        ax.plot(test_index[valid_mask], y_test[valid_mask],
                label="真实值", color="steelblue", linewidth=0.8, alpha=0.9)
        ax.plot(test_index[valid_mask], pred[valid_mask],
                label=f"{name} 预测", color="orangered", linewidth=0.8, alpha=0.85,
                linestyle="--")
        
        ax.set_title(f"{name}  R²={r2:.3f}", fontsize=10)
        ax.legend(fontsize=8, loc="upper right")
        ax.set_ylabel("品位 (%)", fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("时间")
    plt.tight_layout()
    save_path = os.path.join(RESULT_DIR, f"prediction_{outlet_key}.png")
    plt.savefig(save_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  折线图已保存：{save_path}")


def plot_scatter(outlet_key: str, y_test: np.ndarray, preds: dict, label: str):
    """散点图：每个模型一个子图（预测值 vs 真实值）。"""
    n_models = len(preds)
    ncols = 3
    nrows = (n_models + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.5 * nrows))
    if isinstance(axes, np.ndarray):
        axes_flat = axes.flatten()
    else:
        axes_flat = [axes]
    fig.suptitle(f"{label} — 散点图（预测 vs 真实）", fontsize=13)

    for ax, (name, pred) in zip(axes_flat, preds.items()):
        valid_mask = ~np.isnan(pred) & ~np.isnan(y_test)
        if valid_mask.sum() < 2:
            r2, rmse = float('nan'), float('nan')
        else:
            yt = y_test[valid_mask]
            yp = pred[valid_mask]
            r2   = r2_score(yt, yp)
            rmse = np.sqrt(mean_squared_error(yt, yp))
            
            ax.scatter(yt, yp, s=10, alpha=0.5, color="royalblue", edgecolors="none")
            lo, hi = min(yt.min(), yp.min()), max(yt.max(), yp.max())
            ax.plot([lo, hi], [lo, hi], "r--", linewidth=1)
            
        ax.set_title(f"{name}  R²={r2:.3f}  RMSE={rmse:.3f}", fontsize=9)
        ax.set_xlabel("真实值 (%)", fontsize=8)
        ax.set_ylabel("预测值 (%)", fontsize=8)
        ax.grid(True, alpha=0.3)

    for ax in axes_flat[n_models:]:
        ax.set_visible(False)

    plt.tight_layout()
    save_path = os.path.join(RESULT_DIR, f"scatter_{outlet_key}.png")
    plt.savefig(save_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  散点图已保存：{save_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════════════════════

def run_outlet(outlet_key: str, model_names: list[str] | None = None) -> pd.DataFrame:
    """对出矿口运行常规软测量模型（稀疏化验标签模式），返回评估指标 DataFrame。"""
    cfg = OUTLET_CFG[outlet_key]
    enabled = set(model_names or MODEL_NAMES)

    (X_train_full, X_val_full, X_test_full,
     X_tr_vt, X_va_vt, X_te_vt,
     y_train, y_val, y_test,
     val_index, test_index) = load_and_prepare(outlet_key)

    records    = []
    test_preds = {}

    def _save_and_plot():
        # ── 每次跑完一个模型，增量保存预测序列和指标 ──
        pred_df = pd.DataFrame({"y_true": y_test}, index=test_index)
        for k, v in test_preds.items():
            pred_df[f"pred_{k}"] = v
        pred_csv = os.path.join(RESULT_DIR, f"predictions_{outlet_key}.csv")
        pred_df.to_csv(pred_csv, encoding="utf-8")
        
        metrics_df_temp = pd.DataFrame(records)
        metrics_df_temp.insert(0, "出矿口", cfg["label"])
        temp_csv = os.path.join(RESULT_DIR, f"metrics_temp_{outlet_key}.csv")
        metrics_df_temp.to_csv(temp_csv, index=False, encoding="utf-8")
        
        # ── 同步更新图片 ──
        plot_predictions(outlet_key, test_index, y_test, test_preds, cfg["label"])
        plot_scatter(outlet_key, y_test, test_preds, cfg["label"])

    def _log(name, ptr, pte):
        m_tr = compute_metrics(y_train, ptr)
        m_te = compute_metrics(y_test,  pte)
        records.append({"模型": name,
                        "训练R2": m_tr["R2"], "训练RMSE": m_tr["RMSE"], "训练MAE": m_tr["MAE"],
                        "测试R2":  m_te["R2"], "测试RMSE":  m_te["RMSE"], "测试MAE":  m_te["MAE"]})
        test_preds[name] = pte
        print(f"    测试 R²={m_te['R2']:.4f}  RMSE={m_te['RMSE']:.4f}  MAE={m_te['MAE']:.4f}")
        _save_and_plot()

    if "ElasticNet" in enabled:
        ptr, pte = run_elasticnet(X_train_full, X_val_full, X_test_full, y_train, y_val, y_test)
        _log("ElasticNet", ptr, pte)

    if "HistGBDT" in enabled:
        ptr, pte = run_histgb_sparse(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test)
        _log("HistGBDT", ptr, pte)

    if "HistGBDT-Temporal" in enabled:
        ptr, pte = run_histgb_temporal_sparse(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test)
        _log("HistGBDT-Temporal", ptr, pte)

    if "LightGBM" in enabled:
        ptr, pte = run_lightgbm(X_train_full, X_val_full, X_test_full, y_train, y_val, y_test)
        _log("LightGBM", ptr, pte)

    if "XGBoost" in enabled:
        ptr, pte = run_xgboost(X_train_full, X_val_full, X_test_full, y_train, y_val, y_test)
        _log("XGBoost", ptr, pte)

    if {"GPR", "SVR"} & enabled:
        X_train_sel, X_val_sel, X_test_sel = compute_sel_features(X_tr_vt, X_va_vt, X_te_vt, y_train)
        if "GPR" in enabled:
            ptr, pte = run_gpr(X_train_sel, X_test_sel, y_train, y_test)
            _log("GPR", ptr, pte)
        if "SVR" in enabled:
            ptr, pte = run_svr(X_train_sel, X_val_sel, X_test_sel, y_train, y_val, y_test)
            _log("SVR", ptr, pte)

    if "MLP" in enabled:
        ptr, pte = run_mlp(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test)
        _log("MLP", ptr, pte)

    if "GRU" in enabled:
        ptr, pte = run_sequence_deep(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test,
                                     model_name="GRU", seq_len=LSTM_SEQ_LEN)
        _log("GRU", ptr, pte)

    if "TCN" in enabled:
        ptr, pte = run_sequence_deep(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test,
                                     model_name="TCN", seq_len=LSTM_SEQ_LEN)
        _log("TCN", ptr, pte)

    # ══ LSTM（稀疏化验标签，内部标准化）═══════════════════════════
    # compute_metrics 已内置 NaN 掩码，直接传入稀疏 y 即可
    if "LSTM" in enabled:
        ptr, pte = run_lstm(X_tr_vt, X_va_vt, X_te_vt, y_train, y_val, y_test,
                            seq_len=LSTM_SEQ_LEN)
        _log("LSTM", ptr, pte)

    # ── 增量保存 ──
    _save_and_plot()

    metrics_df = pd.DataFrame(records)
    metrics_df.insert(0, "出矿口", cfg["label"])
    return metrics_df





def parse_args():
    parser = argparse.ArgumentParser(description="运行浮选精矿品位软测量模型")
    parser.add_argument(
        "--no-optuna",
        action="store_true",
        help="禁用 LSTM Optuna 超参搜索（兼容旧参数；当前默认已禁用）",
    )
    parser.add_argument(
        "--lstm-optuna",
        action="store_true",
        help="启用轻量 LSTM Optuna 超参搜索（会明显增加耗时）",
    )
    parser.add_argument(
        "--skip-lstm",
        action="store_true",
        help="skip LSTM and run only the faster tabular models",
    )
    parser.add_argument(
        "--models",
        default=",".join(MODEL_NAMES),
        help=("comma-separated model names. Available: "
              + ",".join(MODEL_NAMES)),
    )
    parser.add_argument(
        "--outlets",
        default="xin1",
        help="comma-separated outlets to run. Default: xin1. Use xin1,xin2 only when comparing both symmetric lines.",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="override the parquet dataset path for both outlets",
    )
    parser.add_argument(
        "--dense-target",
        action="store_true",
        help="use dense y_fx_xin1/y_fx_xin2 targets instead of masking them by lab sample timestamps",
    )
    parser.add_argument(
        "--lab-features",
        choices=["upstream", "none"],
        default="upstream",
        help=(
            "which lab features to use. 'upstream' keeps non-flotation lab columns; "
            "'none' disables all lab columns. All lab_flo_* columns are always excluded."
        ),
    )
    return parser.parse_args()


def main():
    global LSTM_USE_OPTUNA, SPARSIFY_TARGET_BY_LAB, LAB_FEATURE_MODE
    args = parse_args()
    if args.lstm_optuna:
        LSTM_USE_OPTUNA = True
        print("[启动模式] 已启用 LSTM Optuna 轻量搜索")
    if args.no_optuna:
        LSTM_USE_OPTUNA = False
        print("[启动模式] 已禁用 LSTM Optuna 超参搜索")

    if args.dataset:
        set_simulation_dataset(args.dataset)
        print(f"[dataset] {args.dataset}")
    if args.dense_target:
        SPARSIFY_TARGET_BY_LAB = False
        print("[target] using dense y_fx targets")
    else:
        print("[target] sparsifying y_fx targets by lab_flo_conc_tfe sample timestamps")
    LAB_FEATURE_MODE = args.lab_features
    print(f"[lab_features] {LAB_FEATURE_MODE}; lab_flo_* columns are always excluded")

    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)

    requested_models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown_models = sorted(set(requested_models) - set(MODEL_NAMES))
    if unknown_models:
        raise ValueError(f"unknown model(s): {unknown_models}; available={MODEL_NAMES}")
    if args.skip_lstm:
        requested_models = [m for m in requested_models if m != "LSTM"]
        print("[启动模式] 已跳过 LSTM")

    requested_outlets = [o.strip() for o in args.outlets.split(",") if o.strip()]
    unknown_outlets = sorted(set(requested_outlets) - set(OUTLET_CFG))
    if unknown_outlets:
        raise ValueError(f"unknown outlet(s): {unknown_outlets}; available={list(OUTLET_CFG)}")

    print(f"[models] {', '.join(requested_models)}")
    print(f"[outlets] {', '.join(requested_outlets)}")

    all_results = []
    for outlet in requested_outlets:
        df_metrics = run_outlet(outlet, model_names=requested_models)
        all_results.append(df_metrics)

    summary = pd.concat(all_results, ignore_index=True)

    # 打印汇总表
    print("\n" + "=" * 80)
    print("  软测量结果汇总（测试集）")
    print("=" * 80)
    disp_cols = ["出矿口", "模型", "测试R2", "测试RMSE", "测试MAE"]
    print(summary[disp_cols].to_string(index=False))

    # 保存完整结果（含训练集）
    csv_path = os.path.join(RESULT_DIR, "metrics_summary.csv")
    summary.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"\n  完整指标已保存：{csv_path}")


if __name__ == "__main__":
    main()
