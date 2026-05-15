#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dml_causal_effect_value/run_dml_xin2.py
========================================
双重机器学习（Double Machine Learning, DML）求新二线浮选精矿品位因果效应系数 θ

模型形式（Partial Linear Model）：
    Y = θ · T + g(X) + ε
    T = f(X) + η

其中：
    Y = y_fx_xin2          （新二线精矿 TFe 品位，稀疏化验标签）
    T = 用户指定的处理变量    （默认：新二线一粗气流量设定 fx_s2_cx1_air_sp）
    X = 混杂变量集           （去除 Y、T 及同线化验泄漏列后的所有过程变量）

估计方法：Cross-fitting DML（Chernozhukov et al., 2018）
    1. 将有化验标签的行按时间顺序等分为 K 个折（K=5）
    2. 对每折 k：
        a. 在余下 K-1 折上用 HistGBDT-Temporal 拟合 Y~X 的扰动函数 ĝ
        b. 在余下 K-1 折上用 HistGBDT-Temporal 拟合 T~X 的扰动函数 f̂
        c. 在折 k 上计算残差：Ỹ = Y - ĝ(X)，T̃ = T - f̂(X)
    3. 汇集全部残差，用 OLS 回归 Ỹ ~ T̃ 求得 θ：
           θ = (Σ T̃²)⁻¹ · Σ T̃·Ỹ
    4. 采用 HC3 异方差稳健标准误，计算 95% 置信区间
    5. 不进行反驳性检验（Refutation Tests）

基学习器：HistGBDT-Temporal（引入滞后特征 + 滚动均值特征）
    滞后步数 lags    = [5, 30, 60, 120]（单位：分钟）
    滚动窗口 windows = [15, 60, 120]（单位：分钟）
    特征构造方式与 soft_measurement.py 中 run_histgb_temporal_sparse 一致

数据来源：
    与 soft_measurement.py 共用同一仿真 Parquet 数据集，默认路径由
    SIMULATION_DATASET 指定，可通过 --dataset 参数覆盖。

输出：
    dml_causal_effect_value/结果/<timestamp>/dml_theta_xin2.csv  — θ 点估计与置信区间
    dml_causal_effect_value/结果/<timestamp>/residuals_xin2.csv  — 残差序列（用于诊断）
    dml_causal_effect_value/结果/<timestamp>/residual_scatter_xin2.png — 残差散点图

运行示例：
    python dml_causal_effect_value/run_dml_xin2.py \\
        --dataset path/to/simulation.parquet \\
        --treatment fx_s2_cx1_air_sp \\
        --n-folds 5
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

from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import VarianceThreshold
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_squared_error

warnings.filterwarnings("ignore")
plt.rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════════════════════
#  路径配置
# ═══════════════════════════════════════════════════════════════════════════
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BASE_RESULT = os.path.join(_THIS_DIR, "结果")
_RUN_TAG     = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULT_DIR   = os.path.join(_BASE_RESULT, _RUN_TAG)

# 默认数据集路径（与 soft_measurement.py 保持一致）
SIMULATION_DATASET = r"C:\Users\goldenwhale\Downloads\my_mining_simulation\output\simulation_10months_rerun_20260514_openloop.parquet"

# ═══════════════════════════════════════════════════════════════════════════
#  全局超参数
# ═══════════════════════════════════════════════════════════════════════════
RANDOM_SEED     = 42
N_FOLDS         = 5        # cross-fitting 折数

# HistGBDT-Temporal 时序特征配置（与 soft_measurement.py 一致）
TEMPORAL_LAGS    = [5, 30, 60, 120]   # 滞后步数（分钟）
TEMPORAL_WINDOWS = [15, 60, 120]      # 滚动均值窗口（分钟）

# HistGradientBoostingRegressor 超参
HGBDT_MAX_ITER         = 500
HGBDT_LEARNING_RATE    = 0.03
HGBDT_MAX_LEAF_NODES   = 15
HGBDT_L2_REG           = 0.05
HGBDT_MAX_TRAIN        = 50000   # 每折最大训练样本数

# 目标变量与数据列
Y_COL            = "y_fx_xin2"
OTHER_Y_COL      = "y_fx_xin1"
DEFAULT_TREATMENT = "fx_s2_cx1_air_sp"
FORBIDDEN_LAB_PREFIXES = ("lab_flo_",)


# ═══════════════════════════════════════════════════════════════════════════
#  辅助工具
# ═══════════════════════════════════════════════════════════════════════════

def subsample_indices(indices: np.ndarray, max_samples: int,
                      random_state: int = RANDOM_SEED) -> np.ndarray:
    """固定随机种子抽样，保持升序，避免过密训练集耗时过长。"""
    indices = np.asarray(indices, dtype=np.int64)
    if max_samples <= 0 or len(indices) <= max_samples:
        return indices
    rng = np.random.default_rng(random_state)
    return np.sort(rng.choice(indices, size=max_samples, replace=False))


# ═══════════════════════════════════════════════════════════════════════════
#  数据加载与预处理
# ═══════════════════════════════════════════════════════════════════════════

def load_data(dataset_path: str, treatment_col: str):
    """加载仿真数据集并返回：Y, T, X_raw, feat_cols, df_index。

    Y：目标变量（稀疏化验值，NaN 表示未采样）
    T：处理变量（全量时间步均有值）
    X：混杂变量特征矩阵（过滤泄漏列后）
    """
    print(f"[数据加载] 读取文件：{dataset_path}")
    df = pd.read_parquet(dataset_path)

    # 时间索引处理（与 soft_measurement.py 保持一致）
    if "t" in df.columns:
        df = df.sort_values("t")
        minute_offset = pd.to_timedelta(df["t"].to_numpy(), unit="min")
        df.index = pd.Timestamp("2026-01-01") + minute_offset
        df.index.name = "time"
        df = df.drop(columns=["t"])
    else:
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "time"
        df = df.sort_index()

    # 检查必要列是否存在
    if Y_COL not in df.columns:
        raise ValueError(f"目标列 '{Y_COL}' 不在数据集中，可用列：{list(df.columns)[:20]}")
    if treatment_col not in df.columns:
        raise ValueError(
            f"处理变量列 '{treatment_col}' 不在数据集中，请用 --treatment 指定正确列名。\n"
            f"示例列名（前30列）：{list(df.columns)[:30]}"
        )

    Y = df[Y_COL].values.astype(np.float32)
    t_mean = df[treatment_col].mean()
    T = df[treatment_col].ffill().fillna(t_mean).values.astype(np.float32)

    # 混杂变量：去除 Y 列、另一条线的 Y 列、处理变量 T、浮选化验泄漏列
    exclude_cols = {Y_COL, OTHER_Y_COL, treatment_col}
    feat_cols = []
    for col in df.columns:
        if col in exclude_cols:
            continue
        if col.startswith(FORBIDDEN_LAB_PREFIXES):
            continue
        feat_cols.append(col)

    X_raw = df[feat_cols].values.astype(np.float32)
    df_index = df.index

    n_labeled = int(np.sum(~np.isnan(Y)))
    print(f"[数据加载] 样本总数={len(df)}，有效化验标签数={n_labeled}（稀疏率={n_labeled/len(df):.2%}）")
    print(f"[数据加载] 处理变量={treatment_col}，混杂变量数={X_raw.shape[1]}")

    return Y, T, X_raw, feat_cols, df_index


def preprocess_features(X_raw: np.ndarray):
    """方差过滤 + NaN 填充，返回预处理后的特征矩阵及变换器。

    VarianceThreshold 仅过滤列（特征），不改变行顺序，因此 DataFrame 中
    行仍保持原始时间升序，前向填充（ffill）不会引入未来信息泄漏。
    """
    # 方差过滤
    vt = VarianceThreshold(threshold=1e-4)
    X_vt = vt.fit_transform(X_raw)
    print(f"[特征预处理] 方差过滤后：{X_vt.shape[1]}/{X_raw.shape[1]} 个特征")

    # NaN 填充：前向填充（历史值替代缺失）+ 列均值兜底（头部无历史可填时）
    X_df = pd.DataFrame(X_vt).ffill()
    col_means = X_df.mean()
    X_clean = X_df.fillna(col_means).values.astype(np.float32)

    return X_clean, vt, col_means


# ═══════════════════════════════════════════════════════════════════════════
#  HistGBDT-Temporal 特征构造与预测
# ═══════════════════════════════════════════════════════════════════════════

def build_temporal_rows(X_full: np.ndarray, indices: np.ndarray,
                        lags: list, windows: list,
                        csum: np.ndarray) -> np.ndarray:
    """为给定的全局时间索引 indices 构造时序特征矩阵。

    特征组成：
        [X[i] | X[i-lag1] | X[i-lag2] | ... | mean(X[i-w1+1:i+1]) | ...]

    与 soft_measurement.py 中 run_histgb_temporal_sparse._rows() 逻辑完全一致。

    参数
    ----
    X_full  : shape (N, d) — 全量时序特征矩阵
    indices : 全局行索引（0-based，相对于 X_full）
    lags    : 滞后步数列表
    windows : 滚动窗口长度列表
    csum    : shape (N+1, d) — X_full 的前缀和（含首行零向量），加速滚动均值
    """
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
        mean_feat = (csum[indices + 1] - csum[start]) / count
        blocks.append(mean_feat.astype(np.float32))
    return np.hstack(blocks)


def build_cumsum(X_full: np.ndarray) -> np.ndarray:
    """构建前缀累积和矩阵，用于 O(1) 滚动均值计算。"""
    return np.vstack([
        np.zeros((1, X_full.shape[1]), dtype=np.float64),
        np.cumsum(X_full, axis=0, dtype=np.float64),
    ])


def fit_histgbdt_temporal(X_full: np.ndarray, y: np.ndarray,
                          train_global_idx: np.ndarray,
                          csum: np.ndarray,
                          lags: list, windows: list,
                          random_state: int = RANDOM_SEED
                          ) -> tuple[HistGradientBoostingRegressor, np.ndarray]:
    """在 train_global_idx 指定的行上拟合 HistGBDT-Temporal 模型。

    注意：train_global_idx 为全局时间索引（相对于 X_full），
    y 为对应行的标签（无 NaN，调用前已过滤）。
    """
    train_idx_sub = subsample_indices(
        np.arange(len(train_global_idx)), HGBDT_MAX_TRAIN, random_state
    )
    X_tr = build_temporal_rows(X_full, train_global_idx[train_idx_sub],
                               lags, windows, csum)
    y_tr = y[train_idx_sub]

    # 处理 NaN（滞后特征在序列开头可能产生 NaN，用列均值填充）
    col_means = np.nanmean(X_tr, axis=0).astype(np.float32)
    nan_mask = np.isnan(X_tr)
    if nan_mask.any():
        X_tr = np.where(nan_mask, col_means, X_tr)

    model = HistGradientBoostingRegressor(
        max_iter=HGBDT_MAX_ITER,
        learning_rate=HGBDT_LEARNING_RATE,
        max_leaf_nodes=HGBDT_MAX_LEAF_NODES,
        l2_regularization=HGBDT_L2_REG,
        random_state=random_state,
    )
    model.fit(X_tr, y_tr)
    return model, col_means  # 返回 col_means 用于预测时的 NaN 填充


def predict_histgbdt_temporal(model: HistGradientBoostingRegressor,
                               X_full: np.ndarray,
                               pred_global_idx: np.ndarray,
                               csum: np.ndarray,
                               lags: list, windows: list,
                               train_col_means: np.ndarray) -> np.ndarray:
    """用已拟合的 HistGBDT-Temporal 对 pred_global_idx 指定的行做预测。"""
    X_pred = build_temporal_rows(X_full, pred_global_idx, lags, windows, csum)
    nan_mask = np.isnan(X_pred)
    if nan_mask.any():
        X_pred = np.where(nan_mask, train_col_means, X_pred)
    return model.predict(X_pred)


# ═══════════════════════════════════════════════════════════════════════════
#  DML 主流程：Cross-fitting + 因果效应估计
# ═══════════════════════════════════════════════════════════════════════════

def run_dml(Y: np.ndarray, T: np.ndarray, X_full: np.ndarray,
            n_folds: int = N_FOLDS) -> dict:
    """执行 Cross-fitting DML，返回包含 θ、置信区间及诊断信息的字典。

    算法步骤
    --------
    1. 取有化验标签的行（labeled rows），按时间顺序切分为 n_folds 折
    2. 对每折 k：
        - 用余下 K-1 折拟合 Y-nuisance 模型（HistGBDT-Temporal）
        - 用余下 K-1 折拟合 T-nuisance 模型（HistGBDT-Temporal）
        - 在折 k 上预测：Ŷ, T̂
        - 计算残差：Ỹ = Y - Ŷ，T̃ = T - T̂
    3. 汇集所有折的残差
    4. OLS：θ = (T̃'T̃)⁻¹ T̃'Ỹ
    5. HC3 异方差稳健标准误 + 95% CI
    """
    t_total = time.time()

    # 仅使用有化验标签的行
    labeled_mask = ~np.isnan(Y)
    labeled_global_idx = np.flatnonzero(labeled_mask)
    n_labeled = len(labeled_global_idx)
    Y_labeled = Y[labeled_global_idx]
    T_labeled = T[labeled_global_idx]

    print(f"\n[DML] 有效化验样本数 n={n_labeled}，折数 K={n_folds}")

    if n_labeled < n_folds * 10:
        raise ValueError(
            f"有效化验样本数 {n_labeled} 过少，无法进行 {n_folds} 折 DML，"
            f"请减少折数（--n-folds）或增加数据量。"
        )

    # 构建全量前缀和（用于 O(1) 滚动均值）
    csum = build_cumsum(X_full)

    # 按时间顺序等分折（不打乱，保证时序因果性）
    fold_boundaries = np.array_split(np.arange(n_labeled), n_folds)

    Y_res = np.full(n_labeled, np.nan, dtype=np.float64)
    T_res = np.full(n_labeled, np.nan, dtype=np.float64)
    Y_hat_all = np.full(n_labeled, np.nan, dtype=np.float64)
    T_hat_all = np.full(n_labeled, np.nan, dtype=np.float64)

    for fold_k, fold_test_local in enumerate(fold_boundaries):
        t_fold = time.time()
        # 训练集：其余折的局部索引
        fold_train_local = np.concatenate(
            [fold_boundaries[j] for j in range(n_folds) if j != fold_k]
        )
        # 转为全局时间索引
        train_global = labeled_global_idx[fold_train_local]
        test_global  = labeled_global_idx[fold_test_local]

        y_train = Y_labeled[fold_train_local]
        t_train = T_labeled[fold_train_local]

        n_tr, n_te = len(train_global), len(test_global)

        # ── Y-nuisance：用 X 预测 Y ──────────────────────────────────────
        y_model, y_col_means = fit_histgbdt_temporal(
            X_full, y_train, train_global, csum,
            TEMPORAL_LAGS, TEMPORAL_WINDOWS, random_state=RANDOM_SEED + fold_k
        )
        Y_hat = predict_histgbdt_temporal(
            y_model, X_full, test_global, csum,
            TEMPORAL_LAGS, TEMPORAL_WINDOWS, y_col_means
        )

        # ── T-nuisance：用 X 预测 T ──────────────────────────────────────
        t_model, t_col_means = fit_histgbdt_temporal(
            X_full, t_train, train_global, csum,
            TEMPORAL_LAGS, TEMPORAL_WINDOWS, random_state=RANDOM_SEED + fold_k + N_FOLDS
        )
        T_hat = predict_histgbdt_temporal(
            t_model, X_full, test_global, csum,
            TEMPORAL_LAGS, TEMPORAL_WINDOWS, t_col_means
        )

        # ── 残差 ─────────────────────────────────────────────────────────
        Y_res[fold_test_local] = Y_labeled[fold_test_local] - Y_hat
        T_res[fold_test_local] = T_labeled[fold_test_local] - T_hat
        Y_hat_all[fold_test_local] = Y_hat
        T_hat_all[fold_test_local] = T_hat

        # 折内 nuisance 模型性能
        y_r2 = r2_score(Y_labeled[fold_test_local], Y_hat)
        t_r2 = r2_score(T_labeled[fold_test_local], T_hat)
        print(
            f"  折 {fold_k+1}/{n_folds}：train={n_tr} test={n_te} "
            f"Y-nuisance R²={y_r2:.4f}  T-nuisance R²={t_r2:.4f}  "
            f"耗时={time.time()-t_fold:.1f}s"
        )

    # ── θ 点估计（OLS on residuals）─────────────────────────────────────
    valid = ~(np.isnan(Y_res) | np.isnan(T_res))
    Yr = Y_res[valid]
    Tr = T_res[valid]
    n_eff = valid.sum()

    # θ = (Tr'Tr)^{-1} Tr'Yr
    TrTr = float(np.dot(Tr, Tr))
    TrYr = float(np.dot(Tr, Yr))
    theta = TrYr / TrTr

    # ── HC3 异方差稳健标准误 ─────────────────────────────────────────────
    # leverage: h_i = Tr_i² / Σ Tr²
    # HC3 残差缩放: ε_i / (1 - h_i)
    residuals_dml = Yr - theta * Tr
    leverage = Tr ** 2 / TrTr
    scale = 1.0 - leverage
    scale = np.maximum(scale, 1e-8)   # 防止除零
    score = Tr * (residuals_dml / scale)    # influence function (HC3)
    var_theta = np.sum(score ** 2) / (TrTr ** 2)
    se_theta  = float(np.sqrt(var_theta))
    ci_lo = theta - 1.96 * se_theta
    ci_hi = theta + 1.96 * se_theta

    print(f"\n[DML 结果] θ = {theta:.6f}  SE = {se_theta:.6f}  "
          f"95% CI = [{ci_lo:.6f}, {ci_hi:.6f}]  n_eff={n_eff}")
    print(f"[DML 结果] 总耗时 {time.time()-t_total:.1f}s")

    return {
        "theta": theta,
        "se": se_theta,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "n_effective": n_eff,
        "Y_residuals": Y_res,
        "T_residuals": T_res,
        "Y_hat": Y_hat_all,
        "T_hat": T_hat_all,
        "labeled_global_idx": labeled_global_idx,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  结果保存与可视化
# ═══════════════════════════════════════════════════════════════════════════

def save_results(result: dict, treatment_col: str, df_index: pd.DatetimeIndex,
                 n_folds: int):
    """将 θ 估计结果和残差序列保存为 CSV，并绘制诊断散点图。"""
    os.makedirs(RESULT_DIR, exist_ok=True)

    # ── θ 汇总表 ─────────────────────────────────────────────────────────
    summary = pd.DataFrame([{
        "治疗变量 (T)":     treatment_col,
        "结果变量 (Y)":     Y_COL,
        "θ 点估计":         round(result["theta"], 6),
        "HC3 标准误":       round(result["se"], 6),
        "95% CI 下界":      round(result["ci_lo"], 6),
        "95% CI 上界":      round(result["ci_hi"], 6),
        "有效样本数":        result["n_effective"],
        "折数 K":           n_folds,
        "基学习器":         "HistGBDT-Temporal",
    }])
    theta_csv = os.path.join(RESULT_DIR, "dml_theta_xin2.csv")
    summary.to_csv(theta_csv, index=False, encoding="utf-8-sig")
    print(f"[保存] θ 汇总：{theta_csv}")

    # ── 残差序列 CSV ──────────────────────────────────────────────────────
    labeled_idx = result["labeled_global_idx"]
    res_df = pd.DataFrame({
        "time":       df_index[labeled_idx],
        "Y_true":     result["Y_residuals"] + result["Y_hat"],  # 恢复原始 Y
        "Y_hat":      result["Y_hat"],
        "Y_residual": result["Y_residuals"],
        "T_true":     result["T_residuals"] + result["T_hat"],  # 恢复原始 T
        "T_hat":      result["T_hat"],
        "T_residual": result["T_residuals"],
    })
    res_csv = os.path.join(RESULT_DIR, "residuals_xin2.csv")
    res_df.to_csv(res_csv, index=False, encoding="utf-8-sig")
    print(f"[保存] 残差序列：{res_csv}")

    # ── 残差散点图（T̃ vs Ỹ，用于诊断线性假设）─────────────────────────
    Tr = result["T_residuals"]
    Yr = result["Y_residuals"]
    valid = ~(np.isnan(Tr) | np.isnan(Yr))
    Tr_v, Yr_v = Tr[valid], Yr[valid]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(
        f"DML 残差诊断 — 新二线 ({Y_COL})\n"
        f"θ = {result['theta']:.4f}  "
        f"95% CI = [{result['ci_lo']:.4f}, {result['ci_hi']:.4f}]",
        fontsize=12,
    )

    # 左图：T̃ vs Ỹ 散点 + 拟合线
    ax = axes[0]
    ax.scatter(Tr_v, Yr_v, s=8, alpha=0.4, color="steelblue", edgecolors="none")
    xlim = np.array([Tr_v.min(), Tr_v.max()])
    ax.plot(xlim, result["theta"] * xlim, "r-", linewidth=1.5,
            label=f"θ = {result['theta']:.4f}")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.axvline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("T 残差（T̃ = T - f̂(X)）", fontsize=10)
    ax.set_ylabel("Y 残差（Ỹ = Y - ĝ(X)）", fontsize=10)
    ax.set_title("残差散点图（线性因果假设验证）", fontsize=10)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # 右图：DML 残差（Ỹ - θ·T̃）的时序图
    ax2 = axes[1]
    dml_resid = Yr_v - result["theta"] * Tr_v
    time_pts = np.arange(len(dml_resid))
    ax2.plot(time_pts, dml_resid, linewidth=0.5, color="darkorange", alpha=0.7)
    ax2.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax2.set_xlabel("有效化验样本序号", fontsize=10)
    ax2.set_ylabel("DML 残差（Ỹ - θ·T̃）", fontsize=10)
    ax2.set_title("DML 残差时序（用于检验同方差性与自相关假设）", fontsize=10)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = os.path.join(RESULT_DIR, "residual_scatter_xin2.png")
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"[保存] 残差散点图：{fig_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  命令行入口
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="HistGBDT-Temporal DML 因果效应估计（新二线浮选精矿品位）"
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="仿真 Parquet 数据集路径，覆盖脚本内默认路径",
    )
    parser.add_argument(
        "--treatment",
        default=DEFAULT_TREATMENT,
        help=(
            f"处理变量列名（默认：{DEFAULT_TREATMENT}）。"
            " 常用选项：fx_s2_cx1_air_sp, fx_s2_td_rough_freq, "
            "fx_s2_naoh_freq, fx_s2_cao_freq 等"
        ),
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=N_FOLDS,
        help=f"Cross-fitting 折数（默认：{N_FOLDS}）",
    )
    return parser.parse_args()


def main():
    global N_FOLDS
    args = parse_args()
    N_FOLDS = args.n_folds

    dataset_path = args.dataset or SIMULATION_DATASET
    treatment_col = args.treatment

    print("=" * 65)
    print("  HistGBDT-Temporal DML — 新二线浮选精矿品位因果效应估计")
    print(f"  结果变量 Y : {Y_COL}")
    print(f"  处理变量 T : {treatment_col}")
    print(f"  Cross-fitting K : {N_FOLDS}")
    print(f"  基学习器       : HistGBDT-Temporal "
          f"(lags={TEMPORAL_LAGS}, windows={TEMPORAL_WINDOWS})")
    print("=" * 65)

    # 1. 加载数据
    Y, T, X_raw, feat_cols, df_index = load_data(dataset_path, treatment_col)

    # 2. 特征预处理（方差过滤 + NaN 填充）
    X_full, vt, col_means = preprocess_features(X_raw)
    X_full = X_full.astype(np.float32)

    # 3. DML cross-fitting
    result = run_dml(Y, T, X_full, n_folds=N_FOLDS)

    # 4. 保存结果
    save_results(result, treatment_col, df_index, n_folds=N_FOLDS)

    # 5. 终端汇总输出
    print("\n" + "=" * 65)
    print("  DML 因果效应估计完毕")
    print(f"  θ (处理变量对精矿品位的因果效应) = {result['theta']:.6f}")
    print(f"  HC3 标准误 SE                     = {result['se']:.6f}")
    print(f"  95% 置信区间                      = [{result['ci_lo']:.6f}, {result['ci_hi']:.6f}]")
    print(f"  有效化验样本数                    = {result['n_effective']}")
    print(f"  结果已保存至：{RESULT_DIR}")
    print("=" * 65)


if __name__ == "__main__":
    main()
