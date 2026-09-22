from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from openflow_engine.ast_compiler import SafeASTCompiler
from openflow_engine.errors import InvalidExpressionError, PipelineExecutionError


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
    ) -> ExecutionOutput:
        start_time = time.perf_counter()
        clean_code = code.strip()

        try:
            if engine == "ast_filter":
                result_df = cls._execute_ast_filter(clean_code, df)
                engine_info = "Safe AST Filter Engine (0 RCE risk)"

            elif engine == "pandas":
                result_df = cls._execute_pandas(clean_code, df)
                engine_info = "Pandas In-Memory Engine"

            elif engine == "pyspark":
                result_df, engine_info = cls._execute_pyspark(clean_code, df, spark_session)

            elif engine == "sql":
                result_df = cls._execute_sql(clean_code, df)
                engine_info = "SQL Query Engine"

            else:
                raise ValueError(f"Unsupported engine: {engine}")

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            bounded_df = result_df.head(limit)
            
            schema = [
                {"name": str(col), "type": str(dtype)}
                for col, dtype in zip(bounded_df.columns, bounded_df.dtypes)
            ]

            return ExecutionOutput(
                status="succeeded",
                duration_ms=round(duration_ms, 2),
                row_count=len(result_df),
                columns=list(bounded_df.columns),
                schema=schema,
                records=bounded_df.to_dict(orient="records"),
                engine_details=engine_info,
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionOutput(
                status="failed",
                duration_ms=round(duration_ms, 2),
                row_count=0,
                columns=[],
                schema=[],
                records=[],
                error=str(exc),
                engine_details=f"Engine execution error in {engine}",
            )

    @classmethod
    def _execute_ast_filter(cls, condition: str, df: pd.DataFrame) -> pd.DataFrame:
        compiler = SafeASTCompiler(condition)
        mask = compiler.evaluate_pandas(df)
        return df[mask].copy()

    @classmethod
    def _execute_pandas(cls, code: str, df: pd.DataFrame) -> pd.DataFrame:
        """Executes a Pandas transformation snippet.
        
        The code can define a `transform(df)` function or assign to `df_out = ...` / `df = ...`.
        """
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
        """Executes PySpark DataFrame transformation."""
        spark = spark_session
        if spark is None:
            try:
                from openflow_engine.pyspark_engine import SparkSessionManager
                spark = SparkSessionManager.get_or_create_session()
            except Exception as exc:
                # If PySpark is not available in current environment, simulate with mock-compatible execution
                # or explain that Spark connection is needed
                raise RuntimeError(f"PySpark session could not be initialized: {exc}") from exc

        # Create Spark DataFrame from ingested pandas DataFrame
        spark_df = spark.createDataFrame(df)
        
        # Safe scope with standard pyspark functions
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

        # Convert back to pandas for UI preview
        if hasattr(res_spark, "toPandas"):
            res_pandas = res_spark.toPandas()
        elif isinstance(res_spark, pd.DataFrame):
            res_pandas = res_spark
        else:
            raise TypeError(f"Expected Spark DataFrame or pandas DataFrame, got {type(res_spark).__name__}")

        return res_pandas, f"PySpark Execution Engine (Master: {getattr(spark, 'master', 'cluster')})"

    @classmethod
    def _execute_sql(cls, query: str, df: pd.DataFrame) -> pd.DataFrame:
        """Executes a SQL query against the ingested DataFrame as table `data`."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        df.to_sql("data", conn, index=False, if_exists="replace")
        result = pd.read_sql_query(query, conn)
        conn.close()
        return result
