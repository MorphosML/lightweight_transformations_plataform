from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from openflow_engine.ast_compiler import SafeASTCompiler
from openflow_engine.errors import InvalidExpressionError, PipelineExecutionError
from openflow_engine.fabric_capacity import CapacityMeter, CapacityReport, ComputeTier
from openflow_engine.governance import AuditLineage, AuditRecord, SecretMasker


@dataclass
class ExecutionOutput:
    status: Literal["succeeded", "failed"]
    duration_ms: float
    row_count: int
    columns: list[str]
    schema: list[dict[str, str]]
    records: list[dict[str, Any]]
    error: str | None = None
    engine_details: str | None = None
    capacity_report: CapacityReport | None = None
    audit_record: AuditRecord | None = None


class CodeExecutor:
    """Executes user transformation code against ingested datasets across multiple engines."""

    @classmethod
    def execute(
        cls,
        code: str,
        engine: Literal["pyspark", "pandas", "ast_filter", "sql"],
        df: pd.DataFrame,
        spark_session: Any | None = None,
        limit: int = 100,
        tenant_id: str = "default_tenant",
        project_id: str = "default_project",
        user_id: str = "openflow_user",
    ) -> ExecutionOutput:
        start_time = time.perf_counter()
        clean_code = code.strip()

        tier = (
            ComputeTier.TIER_1_DISTRIBUTED_SPARK
            if engine == "pyspark"
            else ComputeTier.TIER_0_EMBEDDED
        )

        try:
            if engine == "ast_filter":
                result_df = cls._execute_ast_filter(clean_code, df)
                engine_info = "Safe AST Filter Engine (0 RCE risk)"

            elif engine == "pandas":
                result_df = cls._execute_pandas(clean_code, df)
                engine_info = "Pandas In-Memory Engine (Tier 0 Embedded)"

            elif engine == "pyspark":
                result_df, engine_info = cls._execute_pyspark(clean_code, df, spark_session)

            elif engine == "sql":
                result_df = cls._execute_sql(clean_code, df)
                engine_info = "SQL Query Engine (Tier 0 Micro-OLAP)"

            else:
                raise ValueError(f"Unsupported engine: {engine}")

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            bounded_df = result_df.head(limit)
            
            schema = [
                {"name": str(col), "type": str(dtype)}
                for col, dtype in zip(bounded_df.columns, bounded_df.dtypes)
            ]

            mem_mb = CapacityMeter.estimate_dataframe_size(result_df)
            cap_report = CapacityMeter.calculate_metrics(
                tier=tier,
                row_count=len(result_df),
                col_count=len(result_df.columns),
                memory_mb=mem_mb,
                duration_ms=duration_ms,
            )

            audit_rec = AuditLineage.create_record(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                engine=engine,
                code=clean_code,
                row_count=len(result_df),
                duration_ms=duration_ms,
                capacity_units=cap_report.capacity_units,
                status="succeeded",
            )

            return ExecutionOutput(
                status="succeeded",
                duration_ms=round(duration_ms, 2),
                row_count=len(result_df),
                columns=list(bounded_df.columns),
                schema=schema,
                records=bounded_df.to_dict(orient="records"),
                engine_details=engine_info,
                capacity_report=cap_report,
                audit_record=audit_rec,
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            sanitized_err = SecretMasker.mask(str(exc))

            audit_rec = AuditLineage.create_record(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                engine=engine,
                code=clean_code,
                row_count=0,
                duration_ms=duration_ms,
                capacity_units=0.0,
                status="failed",
            )

            return ExecutionOutput(
                status="failed",
                duration_ms=round(duration_ms, 2),
                row_count=0,
                columns=[],
                schema=[],
                records=[],
                error=sanitized_err,
                engine_details=f"Engine execution error in {engine}",
                audit_record=audit_rec,
            )

    @classmethod
    def _execute_ast_filter(cls, condition: str, df: pd.DataFrame) -> pd.DataFrame:
        compiler = SafeASTCompiler(condition)
        mask = compiler.evaluate_pandas(df)
        return df[mask].copy()

    @classmethod
    def _execute_pandas(cls, code: str, df: pd.DataFrame) -> pd.DataFrame:
        local_scope = {"df": df.copy(), "pd": pd}
        exec(code, {}, local_scope)

        if "transform" in local_scope and callable(local_scope["transform"]):
            result = local_scope["transform"](df.copy())
        elif "df_out" in local_scope:
            result = local_scope["df_out"]
        elif "df" in local_scope:
            result = local_scope["df"]
        else:
            raise ValueError("Code must assign to 'df_out', modify 'df', or define a 'transform(df)' function.")

        if not isinstance(result, pd.DataFrame):
            raise TypeError(f"Transformation result must be a pandas DataFrame, got {type(result).__name__}")
        return result

    @classmethod
    def _execute_pyspark(cls, code: str, df: pd.DataFrame, spark_session: Any | None) -> tuple[pd.DataFrame, str]:
        spark = spark_session
        if spark is None:
            try:
                from openflow_engine.pyspark_engine import SparkSessionManager
                spark = SparkSessionManager.get_or_create_session()
            except Exception as exc:
                raise RuntimeError(f"PySpark session could not be initialized: {exc}") from exc

        spark_df = spark.createDataFrame(df)
        
        try:
            from pyspark.sql import functions as F  # type: ignore
        except ImportError:
            F = None

        local_scope = {"df": spark_df, "spark": spark, "F": F}
        exec(code, {}, local_scope)

        if "transform" in local_scope and callable(local_scope["transform"]):
            res_spark = local_scope["transform"](spark_df, spark)
        elif "df_out" in local_scope:
            res_spark = local_scope["df_out"]
        elif "df" in local_scope:
            res_spark = local_scope["df"]
        else:
            raise ValueError("PySpark code must define 'transform(df, spark)', assign to 'df_out', or modify 'df'.")

        if hasattr(res_spark, "toPandas"):
            res_pandas = res_spark.toPandas()
        elif isinstance(res_spark, pd.DataFrame):
            res_pandas = res_spark
        else:
            raise TypeError(f"Expected Spark DataFrame or pandas DataFrame, got {type(res_spark).__name__}")

        return res_pandas, f"PySpark Distributed Engine (Tier 1 Cluster: {getattr(spark, 'master', 'cluster')})"

    @classmethod
    def _execute_sql(cls, query: str, df: pd.DataFrame) -> pd.DataFrame:
        import sqlite3
        conn = sqlite3.connect(":memory:")
        df.to_sql("data", conn, index=False, if_exists="replace")
        result = pd.read_sql_query(query, conn)
        conn.close()
        return result
