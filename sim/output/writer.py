"""
增量写 Parquet / CSV 输出。

每 batch_size 行写入一次，降低内存开销。
最终调用 close() 刷入剩余行。
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from sim.output.schema import OUTPUT_COLUMNS


class Writer:
    """
    流式写入仿真输出。

    参数
    ----
    output_path : 输出文件路径（.parquet 或 .csv）
    fmt         : 输出格式，"parquet"（默认）或 "csv"
    batch_size  : 每次批写行数（默认 1000）
    columns     : 要输出的列名列表（默认 OUTPUT_COLUMNS）
    """

    def __init__(
        self,
        output_path: str | Path,
        fmt: Literal["parquet", "csv"] = "parquet",
        batch_size: int = 1000,
        columns: list[str] | None = None,
    ) -> None:
        self._path = Path(output_path)
        self._fmt = fmt
        self._batch_size = batch_size
        self._columns = columns if columns is not None else OUTPUT_COLUMNS
        self._buffer: list[dict] = []
        self._parquet_parts: list[pd.DataFrame] = []
        self._csv_first_chunk = True

        # 确保父目录存在
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write_row(self, bus: dict) -> None:
        """
        将 bus 中非 _x_ 前缀的键写入缓冲区，达到 batch_size 时落盘。
        """
        row: dict = {"t": bus.get("t", float("nan"))}
        for col in self._columns:
            val = bus.get(col, float("nan"))
            row[col] = float(val) if val is not None else float("nan")
        self._buffer.append(row)

        if len(self._buffer) >= self._batch_size:
            self._flush()

    def close(self) -> None:
        """刷入剩余缓冲区并合并写入最终文件。"""
        if self._buffer:
            self._flush()
        self._finalize()

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _flush(self) -> None:
        df = pd.DataFrame(self._buffer, columns=["t"] + self._columns)
        self._buffer.clear()
        if self._fmt == "parquet":
            self._parquet_parts.append(df)
        else:
            df.to_csv(
                self._path,
                mode="w" if self._csv_first_chunk else "a",
                header=self._csv_first_chunk,
                index=False,
            )
            self._csv_first_chunk = False

    def _finalize(self) -> None:
        if self._fmt == "parquet" and self._parquet_parts:
            combined = pd.concat(self._parquet_parts, ignore_index=True)
            combined.to_parquet(self._path, index=False)
            self._parquet_parts.clear()
