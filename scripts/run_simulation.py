#!/usr/bin/env python3
"""
仿真 CLI 入口。

用法示例：
  python scripts/run_simulation.py
  python scripts/run_simulation.py --steps 100 --format csv --output /tmp/out.csv
  python scripts/run_simulation.py --no-warmup --seed 123
"""

from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

# 将项目根目录加入 sys.path，使 `sim` 包可直接导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.config import SimConfig, DisturbanceConfig, BallMillConfig, MagSepConfig
from sim.simulator import Simulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="东鞍山选矿DCS仿真系统")
    parser.add_argument(
        "--steps", type=int, default=None,
        help="仿真步数（默认：SimConfig.n_steps = 43200）",
    )
    parser.add_argument(
        "--output", type=str, default="output/simulation.parquet",
        help="输出文件路径（默认：output/simulation.parquet）",
    )
    parser.add_argument(
        "--format", choices=["parquet", "csv"], default="parquet",
        help="输出格式（默认：parquet）",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="全局随机种子（默认：42）",
    )
    parser.add_argument(
        "--no-warmup", action="store_true",
        help="跳过预热阶段",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    sim_cfg = SimConfig(seed=args.seed)
    dist_cfg = DisturbanceConfig()
    ball_cfg = BallMillConfig()
    mag_cfg = MagSepConfig()

    sim = Simulator(
        sim_cfg=sim_cfg,
        dist_cfg=dist_cfg,
        ball_cfg=ball_cfg,
        mag_cfg=mag_cfg,
        output_path=args.output,
        fmt=args.format,
    )

    if not args.no_warmup:
        print(f"[仿真] 预热 {sim_cfg.warm_up_steps} 步 ...", flush=True)
        sim.warm_up()

    n_steps = args.steps if args.steps is not None else sim_cfg.n_steps
    print(f"[仿真] 开始仿真 {n_steps} 步 ...", flush=True)
    t0 = time.perf_counter()

    sim.run_steps(n_steps)

    elapsed = time.perf_counter() - t0
    print(f"[仿真] 完成！耗时 {elapsed:.2f}s，输出 → {args.output}")


if __name__ == "__main__":
    main()
