from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from .errors import InvalidExpressionError


class SafeASTCompiler:
    """Safely validates and compiles filter expressions for multiple execution engines.
    
    Prevents arbitrary code execution (S1) by allowing only a strict whitelist of
    AST node types: column references, literals, comparisons, boolean operators,
    and unary negation.
    """

    ALLOWED_COMPARE_OPS = (
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
    )

    def __init__(self, condition: str) -> None:
        self.condition = condition.strip()
        if not self.condition:
            raise InvalidExpressionError("filter condition cannot be empty")
        try:
            self.tree = ast.parse(self.condition, mode="eval")
        except SyntaxError as exc:
            raise InvalidExpressionError(f"invalid expression syntax: {exc}") from exc

    def validate(self, columns: set[str] | None = None) -> set[str]:
        """Validates that the expression tree contains only safe nodes.
        
        Returns the set of column names referenced in the expression.
        """
        referenced_columns: set[str] = set()
        self._validate_node(self.tree.body, columns, referenced_columns)
        return referenced_columns

    def evaluate_pandas(self, frame: pd.DataFrame) -> pd.Series:
        """Evaluates the expression against a pandas DataFrame, returning a boolean Series mask."""
        self.validate(set(frame.columns))
        mask = self._eval_pandas_node(self.tree.body, frame)
        if not isinstance(mask, pd.Series):
            mask = pd.Series(bool(mask), index=frame.index)
        return mask

    def compile_pyspark_column(self, columns: set[str] | None = None) -> Any:
        """Compiles the expression into a PySpark Column expression.
        
        Avoids passing raw strings to df.filter() or expr(), avoiding SQL injection.
        """
        self.validate(columns)
        try:
            from pyspark.sql import functions as F  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PySpark is required to compile PySpark expressions") from exc

        return self._compile_spark_node(self.tree.body, F)

    def _validate_node(
        self,
        node: ast.AST,
        columns: set[str] | None,
        referenced_columns: set[str],
    ) -> None:
        if isinstance(node, ast.Name):
            referenced_columns.add(node.id)
            if columns is not None and node.id not in columns:
                raise InvalidExpressionError(f"unknown column: {node.id}")
            return

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise InvalidExpressionError(f"unsupported constant type: {type(node.value).__name__}")
            return

        if isinstance(node, ast.List | ast.Tuple):
            for elt in node.elts:
                if not isinstance(elt, ast.Constant):
                    raise InvalidExpressionError("lists and sets in expressions must contain only literal constants")
            return

        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                raise InvalidExpressionError("unsupported boolean operator")
            for val in node.values:
                self._validate_node(val, columns, referenced_columns)
            return

        if isinstance(node, ast.Compare):
            self._validate_node(node.left, columns, referenced_columns)
            for comparator in node.comparators:
                self._validate_node(comparator, columns, referenced_columns)
            if not all(isinstance(op, self.ALLOWED_COMPARE_OPS) for op in node.ops):
                raise InvalidExpressionError("unsupported comparison operator")
            return

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ast.Not):
                raise InvalidExpressionError("unsupported unary operator")
            self._validate_node(node.operand, columns, referenced_columns)
            return

        # Explicitly reject attribute access, function calls, imports, subscripts, etc.
        raise InvalidExpressionError(f"forbidden or unsupported syntax: {type(node).__name__}")

    def _eval_pandas_node(self, node: ast.AST, frame: pd.DataFrame) -> Any:
        if isinstance(node, ast.Name):
            return frame[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List | ast.Tuple):
            return [elt.value for elt in node.elts]  # type: ignore
        if isinstance(node, ast.BoolOp):
            values = [self._eval_pandas_node(v, frame) for v in node.values]
            result = values[0]
            for v in values[1:]:
                result = result & v if isinstance(node.op, ast.And) else result | v
            return result
        if isinstance(node, ast.Compare):
            left = self._eval_pandas_node(node.left, frame)
            result = pd.Series(True, index=frame.index)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._eval_pandas_node(comparator, frame)
                if isinstance(operator, ast.Eq):
                    current = left == right
                elif isinstance(operator, ast.NotEq):
                    current = left != right
                elif isinstance(operator, ast.Lt):
                    current = left < right
                elif isinstance(operator, ast.LtE):
                    current = left <= right
                elif isinstance(operator, ast.Gt):
                    current = left > right
                elif isinstance(operator, ast.GtE):
                    current = left >= right
                elif isinstance(operator, ast.In):
                    if isinstance(left, pd.Series):
                        current = left.isin(right)
                    else:
                        current = left in right
                elif isinstance(operator, ast.NotIn):
                    if isinstance(left, pd.Series):
                        current = ~left.isin(right)
                    else:
                        current = left not in right
                else:
                    raise InvalidExpressionError("unsupported comparison operator")
                result = result & current
                left = right
            return result
        if isinstance(node, ast.UnaryOp):
            return ~self._eval_pandas_node(node.operand, frame)

        raise InvalidExpressionError(f"unsupported expression node: {type(node).__name__}")

    def _compile_spark_node(self, node: ast.AST, F: Any) -> Any:
        """Compiles AST node into a PySpark Column object."""
        if isinstance(node, ast.Name):
            return F.col(node.id)
        if isinstance(node, ast.Constant):
            return F.lit(node.value)
        if isinstance(node, ast.List | ast.Tuple):
            return [elt.value for elt in node.elts]  # type: ignore
        if isinstance(node, ast.BoolOp):
            values = [self._compile_spark_node(v, F) for v in node.values]
            result = values[0]
            for v in values[1:]:
                result = (result & v) if isinstance(node.op, ast.And) else (result | v)
            return result
        if isinstance(node, ast.Compare):
            left = self._compile_spark_node(node.left, F)
            result = None
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._compile_spark_node(comparator, F)
                if isinstance(operator, ast.Eq):
                    current = left == right
                elif isinstance(operator, ast.NotEq):
                    current = left != right
                elif isinstance(operator, ast.Lt):
                    current = left < right
                elif isinstance(operator, ast.LtE):
                    current = left <= right
                elif isinstance(operator, ast.Gt):
                    current = left > right
                elif isinstance(operator, ast.GtE):
                    current = left >= right
                elif isinstance(operator, ast.In):
                    current = left.isin(right)
                elif isinstance(operator, ast.NotIn):
                    current = ~left.isin(right)
                else:
                    raise InvalidExpressionError("unsupported comparison operator")

                result = current if result is None else (result & current)
                left = right
            return result
        if isinstance(node, ast.UnaryOp):
            return ~self._compile_spark_node(node.operand, F)

        raise InvalidExpressionError(f"unsupported expression node: {type(node).__name__}")
