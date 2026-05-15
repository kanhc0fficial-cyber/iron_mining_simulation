"""
顶层仿真编排器。

按拓扑顺序调度各子系统，通过信号总线（bus）传递中间物理量，
并将非 _x_ 前缀的量增量写入输出文件。
"""

from __future__ import annotations
from pathlib import Path

from sim.config import (
    SimConfig, DisturbanceConfig, BallMillConfig, BoundaryConfig, MagSepConfig, TowerMillConfig,
    FlotationConfig, ProcessLabConfig,
)
from sim.rng import RNGFactory
from sim.layers.boundary import BoundaryGenerator
from sim.layers.mag_sep import MagSepSystem
from sim.layers.tower_mill import TowerMillSystem
from sim.layers.flotation import FlotationSystem
from sim.layers.process_lab import ProcessLabSampler
from sim.output.writer import Writer


class Simulator:
    """
    东鞍山选矿仿真顶层编排器（第三步：扰动 + 球磨 + 磁选段 + 塔磨段 + 浮选段）。

    参数
    ----
    sim_cfg      : 全局仿真控制参数
    dist_cfg     : 旧扰动层参数（用于构造第一阶段 BoundaryConfig）
    ball_cfg     : 旧球磨溢流参数（用于构造第一阶段 BoundaryConfig）
    mag_cfg      : 磁选段参数
    boundary_cfg : 入口边界参数（提供时优先使用）
    tm_cfg       : 塔磨段参数（None 时使用默认值）
    flo_cfg      : 浮选段参数（None 时使用默认值）
    output_path  : 输出文件路径
    fmt          : 输出格式（"parquet" 或 "csv"）
    """

    def __init__(
        self,
        sim_cfg: SimConfig,
        dist_cfg: DisturbanceConfig,
        ball_cfg: BallMillConfig,
        mag_cfg: MagSepConfig,
        boundary_cfg: BoundaryConfig | None = None,
        tm_cfg: TowerMillConfig | None = None,
        flo_cfg: FlotationConfig | None = None,
        lab_cfg: ProcessLabConfig | None = None,
        output_path: str | Path = "output/simulation.parquet",
        fmt: str = "parquet",
    ) -> None:
        self._sim_cfg = sim_cfg
        rng_factory = RNGFactory(sim_cfg.seed)

        boundary_cfg = boundary_cfg if boundary_cfg is not None else BoundaryConfig.from_legacy(
            dist_cfg, ball_cfg, dt=sim_cfg.dt
        )
        self._boundary = BoundaryGenerator(
            boundary_cfg, sim_cfg, rng_factory.get("boundary"), open_loop=sim_cfg.open_loop
        )
        self._mag_sep = MagSepSystem(mag_cfg, sim_cfg, rng_factory.get("mag"))
        self._tower_mill = TowerMillSystem(
            tm_cfg if tm_cfg is not None else TowerMillConfig(),
            sim_cfg,
            rng_factory.get("tm"),
        )
        self._flotation = FlotationSystem(
            flo_cfg if flo_cfg is not None else FlotationConfig(),
            sim_cfg,
            rng_factory.get("flo"),
        )
        self._process_lab = ProcessLabSampler(
            lab_cfg if lab_cfg is not None else ProcessLabConfig(),
            sim_cfg,
            rng_factory.get("process_lab"),
        )
        self._writer = Writer(output_path, fmt=fmt)

        self._bus: dict = {}

    def warm_up(self, n_steps: int | None = None) -> None:
        """预热仿真（不写输出），使动态状态达到稳态。"""
        steps = n_steps if n_steps is not None else self._sim_cfg.warm_up_steps
        for t in range(steps):
            self._step(t, write=False)

    def run(self) -> None:
        """运行完整仿真并写入输出。"""
        for t in range(self._sim_cfg.n_steps):
            self._step(t, write=True)
        self._writer.close()

    def run_steps(self, n_steps: int) -> None:
        """运行指定步数（用于快速验证），写入输出。"""
        if n_steps <= 0:
            raise ValueError(f"n_steps 必须是正整数，得到 {n_steps!r}")
        for t in range(n_steps):
            self._step(t, write=True)
        self._writer.close()

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _step(self, t: int, write: bool) -> None:
        bus = self._bus
        bus.clear()
        bus["t"] = t

        self._boundary.step(bus, t)        # 写入口边界、旧 _x_* 兼容字段和 lab_1/2/3_eryi_*
        self._mag_sep.step(bus, t)         # 写磁选 DCS 变量 + _x_g_mag, _x_m_mag
        self._tower_mill.step(bus, t)      # 写塔磨 DCS 变量 + _x_f325_ov …
        self._flotation.step(bus, t)       # 写浮选 DCS 变量 + y_fx_xin1/2
        self._process_lab.step(bus, t)     # 写确认点位过程化验 lab_*，不回流机理

        if write:
            self._writer.write_row(bus)
