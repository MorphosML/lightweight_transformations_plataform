import pandas as pd
import pytest

from openflow_api.code_executor import CodeExecutor


def test_code_executor_ast_filter_mode() -> None:
    df = pd.DataFrame(
        {
            "amount": [10.0, 50.0, 150.0, 200.0],
            "category": ["Book", "Electronics", "Electronics", "Home"],
        }
    )

    out = CodeExecutor.execute(
        code="amount > 100 and category == 'Electronics'",
        engine="ast_filter",
        df=df,
    )

    assert out.status == "succeeded"
    assert out.row_count == 1
    assert out.records[0]["amount"] == 150.0
    assert out.records[0]["category"] == "Electronics"


def test_code_executor_pandas_mode() -> None:
    df = pd.DataFrame({"val": [1, 2, 3]})
    code = """
df_out = df.copy()
df_out['squared'] = df_out['val'] ** 2
"""
    out = CodeExecutor.execute(code=code, engine="pandas", df=df)

    assert out.status == "succeeded"
    assert out.row_count == 3
    assert "squared" in out.columns
    assert [r["squared"] for r in out.records] == [1, 4, 9]


def test_code_executor_sql_mode() -> None:
    df = pd.DataFrame(
        {
            "country": ["USA", "USA", "Canada"],
            "amount": [100.0, 200.0, 50.0],
        }
    )
    query = """
SELECT country, SUM(amount) AS total
FROM data
GROUP BY country
ORDER BY total DESC;
"""
    out = CodeExecutor.execute(code=query, engine="sql", df=df)

    assert out.status == "succeeded"
    assert out.row_count == 2
    assert out.records[0]["country"] == "USA"
    assert out.records[0]["total"] == 300.0


def test_code_executor_handles_errors_gracefully() -> None:
    df = pd.DataFrame({"val": [1]})
    out = CodeExecutor.execute(code="1 / 0", engine="pandas", df=df)

    assert out.status == "failed"
    assert "division by zero" in str(out.error)
    assert out.row_count == 0
