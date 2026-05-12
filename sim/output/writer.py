"""
增量写 Parquet / CSV 输出。

每 batch_size 行写入一次，降低内存开销。
Parquet 格式使用 pyarrow.ParquetWriter 实现真正的逐批写入，
不在内存中累积所有批次；CSV 格式用追加模式写入同一文件。
最终调用 close() 刷入剩余行并关闭文件句柄。
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from sim.output.schema import OUTPUT_COLUMNS

# Parquet 输出的 Arrow schema（全部 float64，t 列为 int64）
def _build_schema(columns: list[str]) -> pa.Schema:
    fields = [pa.field("t", pa.int64())]
    for col in columns:
        fields.append(pa.field(col, pa.float64()))
    return pa.schema(fields)


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
        self._csv_first_chunk = True

        # 确保父目录存在
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Parquet 增量写入器（首次 _flush 时惰性创建）
        self._pq_writer: pq.ParquetWriter | None = None
        self._pq_schema: pa.Schema = _build_schema(self._columns)

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
        """刷入剩余缓冲区并关闭文件句柄。"""
        if self._buffer:
            self._flush()
        if self._pq_writer is not None:
            self._pq_writer.close()
            self._pq_writer = None

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _flush(self) -> None:
        df = pd.DataFrame(self._buffer, columns=["t"] + self._columns)
        self._buffer.clear()
        if self._fmt == "parquet":
            if self._pq_writer is None:
                self._pq_writer = pq.ParquetWriter(self._path, self._pq_schema)
            table = pa.Table.from_pandas(df, schema=self._pq_schema, preserve_index=False)
            self._pq_writer.write_table(table)
        else:
            df.to_csv(
                self._path,
                mode="w" if self._csv_first_chunk else "a",
                header=self._csv_first_chunk,
                index=False,
            )
            self._csv_first_chunk = False
