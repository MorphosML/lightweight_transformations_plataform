from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Any

import pandas as pd


class ComputeTier(str, Enum):
    """Execution tiers for economic capacity management."""
    TIER_0_EMBEDDED = "TIER_0_EMBEDDED"       # In-memory vectorized / SQLite OLAP (0 CU, $0 cloud cost)
    TIER_1_DISTRIBUTED_SPARK = "TIER_1_SPARK"  # PySpark cluster distributed execution
    AUTO = "AUTO"                             # Workload-adaptive economic tiering


@dataclass
class CapacityReport:
    """Execution capacity and FinOps metrics."""
    tier_used: ComputeTier
    row_count: int
    column_count: int
    memory_mb: float
    duration_ms: float
    capacity_units: float           # Fabric Capacity Units (CU-seconds)
    spark_equivalent_cu: float      # What a Spark cluster would have consumed
    cost_avoidance_usd: float       # Money saved by running on Tier 0 vs Tier 1
    governor_action: str            # e.g. "OPTIMIZED_TO_TIER_0" or "SCALED_TO_SPARK"


class CapacityMeter:
    """Calculates Capacity Units (CU) and financial cost avoidance."""

    # Baseline cost estimates modeled after cloud capacity units ($0.18/CU-hour or ~$0.00005/CU-sec)
    CU_HOURLY_RATE_USD = 0.18
    CU_PER_SEC_USD = CU_HOURLY_RATE_USD / 3600.0

    # Spark cluster allocation minimum overhead: 2 nodes * 4 vCPU = 8 CU baseline allocation
    SPARK_BASELINE_CU = 2.50

    @classmethod
    def estimate_dataframe_size(cls, df: pd.DataFrame) -> float:
        """Returns approximate in-memory size in MB."""
        if df.empty:
            return 0.01
        try:
            bytes_used = df.memory_usage(deep=True).sum()
            return round(bytes_used / (1024 * 1024), 3)
        except Exception:
            return round((len(df) * len(df.columns) * 8) / (1024 * 1024), 3)

    @classmethod
    def calculate_metrics(
        cls,
        tier: ComputeTier,
        row_count: int,
        col_count: int,
        memory_mb: float,
        duration_ms: float,
    ) -> CapacityReport:
        """Computes CU consumed and financial cost avoidance."""
        duration_sec = max(duration_ms / 1000.0, 0.001)

        if tier == ComputeTier.TIER_0_EMBEDDED:
            # Micro-OLAP: fractional micro-CU based purely on local CPU time
            cu_consumed = round(0.01 * duration_sec * max(1.0, memory_mb / 10.0), 5)
            # Spark baseline overhead if a cluster were spun up for this batch
            spark_equiv_cu = round(cls.SPARK_BASELINE_CU * max(1.0, duration_sec), 3)
            # Cost avoided
            cost_saved = round((spark_equiv_cu - cu_consumed) * (duration_sec * cls.CU_PER_SEC_USD * 100), 4)
            action = f"ECONOMIC_TIER_0 (Saved {spark_equiv_cu:g} CU)"
        else:
            cu_consumed = round(cls.SPARK_BASELINE_CU * duration_sec, 3)
            spark_equiv_cu = cu_consumed
            cost_saved = 0.0
            action = "SCALED_TO_DISTRIBUTED_SPARK"

        return CapacityReport(
            tier_used=tier,
            row_count=row_count,
            column_count=col_count,
            memory_mb=memory_mb,
            duration_ms=round(duration_ms, 2),
            capacity_units=cu_consumed,
            spark_equivalent_cu=spark_equiv_cu,
            cost_avoidance_usd=max(cost_saved, 0.0),
            governor_action=action,
        )


class FabricCapacityRouter:
    """Dynamically routes workloads to the most economical compute tier."""

    # Default threshold: datasets below 50k rows are economically processed on Tier 0
    DEFAULT_ROW_THRESHOLD = 50_000
    # Memory ceiling in MB to protect local worker from OOM
    DEFAULT_MEMORY_CEILING_MB = 1024.0
    # Execution timeout in seconds
    DEFAULT_TIMEOUT_SEC = 60.0

    def __init__(
        self,
        row_threshold: int = DEFAULT_ROW_THRESHOLD,
        memory_ceiling_mb: float = DEFAULT_MEMORY_CEILING_MB,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.row_threshold = row_threshold
        self.memory_ceiling_mb = memory_ceiling_mb
        self.timeout_sec = timeout_sec

    def evaluate_tier(self, df: pd.DataFrame, preferred_engine: str = "auto") -> ComputeTier:
        """Determines the optimal execution tier."""
        if preferred_engine.lower() == "pyspark":
            # Explicit user preference for distributed Spark
            return ComputeTier.TIER_1_DISTRIBUTED_SPARK

        row_count = len(df)
        mem_mb = CapacityMeter.estimate_dataframe_size(df)

        if row_count < self.row_threshold and mem_mb < self.memory_ceiling_mb:
            return ComputeTier.TIER_0_EMBEDDED

        return ComputeTier.TIER_1_DISTRIBUTED_SPARK

    def validate_resource_bounds(self, df: pd.DataFrame) -> None:
        """Ensures input fits within security and memory limits."""
        mem_mb = CapacityMeter.estimate_dataframe_size(df)
        if mem_mb > self.memory_ceiling_mb * 2:
            raise MemoryError(
                f"Workload size ({mem_mb:.1f} MB) exceeds maximum allowed worker memory ceiling ({self.memory_ceiling_mb} MB)."
            )
