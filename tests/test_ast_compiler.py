import pandas as pd
import pytest

from openflow_engine.ast_compiler import SafeASTCompiler
from openflow_engine.errors import InvalidExpressionError


def test_ast_compiler_blocks_rce_and_attribute_access() -> None:
    malicious_inputs = [
        "__import__('os').system('echo pwned')",
        "getattr(df, 'drop')()",
        "lambda x: x + 1",
        "open('/etc/passwd').read()",
        "math.sqrt(value) > 10",
        "frame.iloc[0]",
    ]

    for malicious in malicious_inputs:
        with pytest.raises(InvalidExpressionError):
            compiler = SafeASTCompiler(malicious)
            compiler.evaluate_pandas(pd.DataFrame({"value": [1]}))


def test_ast_compiler_allows_valid_comparisons_and_boolean_logic() -> None:
    df = pd.DataFrame(
        {
            "age": [20, 25, 30, 35],
            "role": ["intern", "engineer", "manager", "director"],
            "active": [True, True, False, True],
        }
    )

    compiler = SafeASTCompiler("age >= 25 and role == 'engineer' and active == True")
    mask = compiler.evaluate_pandas(df)
    filtered = df[mask]

    assert filtered["age"].tolist() == [25]
    assert filtered["role"].tolist() == ["engineer"]


def test_ast_compiler_supports_in_and_not_in() -> None:
    df = pd.DataFrame({"category": ["electronics", "furniture", "clothing"]})

    compiler = SafeASTCompiler("category in ['electronics', 'clothing']")
    filtered = df[compiler.evaluate_pandas(df)]

    assert filtered["category"].tolist() == ["electronics", "clothing"]


def test_ast_compiler_rejects_unknown_columns() -> None:
    df = pd.DataFrame({"col_a": [1, 2]})

    compiler = SafeASTCompiler("non_existent_column > 5")
    with pytest.raises(InvalidExpressionError, match="unknown column"):
        compiler.evaluate_pandas(df)
