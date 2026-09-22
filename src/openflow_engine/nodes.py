from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

import pandas as pd

from .ast_compiler import SafeASTCompiler
from .connectors import BaseConnector


class Node(Protocol):
    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame: ...
    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any: ...


@dataclass
class InputNode:
    connector: BaseConnector
    tenant_id: str
    key: str
    project_id: str | None = None

    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        if inputs:
            raise ValueError("input nodes cannot receive upstream data")
        return self.connector.read(self.tenant_id, self.key, self.project_id)

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        if inputs:
            raise ValueError("input nodes cannot receive upstream data")
        return self.connector.read_spark(self.tenant_id, self.key, spark, self.project_id)


@dataclass
class FilterNode:
    condition: str

    def __post_init__(self) -> None:
        self.compiler = SafeASTCompiler(self.condition)

    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("filter nodes require exactly one input")
        frame = frames[0]
        mask = self.compiler.evaluate_pandas(frame)
        return frame[mask].copy()

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("filter nodes require exactly one input")
        df = frames[0]
        col_expr = self.compiler.compile_pyspark_column(set(df.columns))
        return df.filter(col_expr)


@dataclass
class JoinNode:
    on: str | list[str]
    how: str = "inner"

    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        left, right = self._extract_left_right(inputs)
        join_keys = [self.on] if isinstance(self.on, str) else list(self.on)
        return pd.merge(left, right, on=join_keys, how=self.how)

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        left, right = self._extract_left_right(inputs)
        join_keys = [self.on] if isinstance(self.on, str) else list(self.on)
        return left.join(right, on=join_keys, how=self.how)

    def _extract_left_right(self, inputs: list[Any] | dict[str, Any]) -> tuple[Any, Any]:
        if isinstance(inputs, dict):
            if "left" in inputs and "right" in inputs:
                return inputs["left"], inputs["right"]
            vals = list(inputs.values())
            if len(vals) == 2:
                return vals[0], vals[1]
            raise ValueError("join nodes require both 'left' and 'right' inputs")
        if len(inputs) != 2:
            raise ValueError(f"join nodes require exactly 2 inputs, got {len(inputs)}")
        return inputs[0], inputs[1]


@dataclass
class UnionNode:
    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) < 2:
            raise ValueError("union nodes require at least two inputs")
        return pd.concat(frames, ignore_index=True)

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) < 2:
            raise ValueError("union nodes require at least two inputs")
        result = frames[0]
        for df in frames[1:]:
            result = result.unionByName(df)
        return result


@dataclass
class TransformNode:
    """Selects, renames, or drops columns."""
    select_columns: list[str] | None = None
    rename_columns: dict[str, str] | None = None
    drop_columns: list[str] | None = None

    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("transform nodes require exactly one input")
        df = frames[0].copy()
        if self.select_columns:
            df = df[self.select_columns]
        if self.rename_columns:
            df = df.rename(columns=self.rename_columns)
        if self.drop_columns:
            df = df.drop(columns=self.drop_columns)
        return df

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("transform nodes require exactly one input")
        df = frames[0]
        if self.select_columns:
            df = df.select(*self.select_columns)
        if self.rename_columns:
            for old_col, new_col in self.rename_columns.items():
                df = df.withColumnRenamed(old_col, new_col)
        if self.drop_columns:
            df = df.drop(*self.drop_columns)
        return df


@dataclass
class OutputNode:
    connector: BaseConnector
    tenant_id: str
    key: str
    project_id: str | None = None

    def execute(self, inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("output nodes require exactly one input")
        self.connector.write(self.tenant_id, self.key, frames[0], self.project_id)
        return frames[0].copy()

    def execute_spark(self, inputs: list[Any] | dict[str, Any], spark: Any) -> Any:
        frames = list(inputs.values()) if isinstance(inputs, dict) else inputs
        if len(frames) != 1:
            raise ValueError("output nodes require exactly one input")
        self.connector.write_spark(self.tenant_id, self.key, frames[0], self.project_id)
        return frames[0]
