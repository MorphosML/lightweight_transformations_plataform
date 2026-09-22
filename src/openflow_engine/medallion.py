from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
import time
from typing import Any

import pandas as pd


class MedallionStage(str, Enum):
    BRONZE = "BRONZE"  # Raw, immutable ingest from SQL/S3
    SILVER = "SILVER"  # Cleansed, normalized, and PII-masked
    GOLD = "GOLD"      # Business aggregates, KPIs, and dimensional facts


@dataclass
class LakehouseTableMeta:
    name: str
    stage: MedallionStage
    row_count: int
    column_count: int
    columns: list[str]
    created_at: float
    format_type: str = "columnar/parquet"
    size_kb: float = 0.0


class MedallionCatalog:
    """Manages lakehouse tables organized into Bronze, Silver, and Gold tiers."""

    def __init__(self, base_storage_dir: str | None = None) -> None:
        self.base_dir = base_storage_dir
        self._tables: dict[str, tuple[LakehouseTableMeta, pd.DataFrame]] = {}

    def register_table(
        self,
        name: str,
        stage: MedallionStage,
        df: pd.DataFrame,
    ) -> LakehouseTableMeta:
        """Stores a table into the designated medallion tier."""
        mem_bytes = df.memory_usage(deep=True).sum() if not df.empty else 0
        size_kb = round(mem_bytes / 1024.0, 2)

        meta = LakehouseTableMeta(
            name=name,
            stage=stage,
            row_count=len(df),
            column_count=len(df.columns),
            columns=list(df.columns),
            created_at=time.time(),
            size_kb=size_kb,
        )

        key = f"{stage.value.lower()}:{name}"
        self._tables[key] = (meta, df.copy())

        # Optionally persist to disk if base_dir is configured
        if self.base_dir:
            stage_dir = os.path.join(self.base_dir, stage.value.lower())
            os.makedirs(stage_dir, exist_ok=True)
            file_path = os.path.join(stage_dir, f"{name}.parquet")
            try:
                df.to_parquet(file_path, index=False)
            except Exception:
                # Fallback to CSV if pyarrow/fastparquet not installed
                df.to_csv(os.path.join(stage_dir, f"{name}.csv"), index=False)

        return meta

    def get_table(self, stage: MedallionStage, name: str) -> pd.DataFrame | None:
        """Retrieves a DataFrame from the catalog."""
        key = f"{stage.value.lower()}:{name}"
        if key in self._tables:
            return self._tables[key][1].copy()
        return None

    def list_tables(self, stage: MedallionStage | None = None) -> list[LakehouseTableMeta]:
        """Lists metadata for registered lakehouse tables."""
        if stage:
            prefix = f"{stage.value.lower()}:"
            return [meta for k, (meta, _) in self._tables.items() if k.startswith(prefix)]
        return [meta for _, (meta, _) in self._tables.items()]

    def transition_stage(
        self,
        from_stage: MedallionStage,
        from_name: str,
        to_stage: MedallionStage,
        to_name: str,
        transformation_fn: Any | None = None,
    ) -> LakehouseTableMeta:
        """Transitions data between medallion layers with optional transformation."""
        source_df = self.get_table(from_stage, from_name)
        if source_df is None:
            raise KeyError(f"Table '{from_name}' not found in stage '{from_stage.value}'.")

        target_df = transformation_fn(source_df) if transformation_fn else source_df
        return self.register_table(to_name, to_stage, target_df)

