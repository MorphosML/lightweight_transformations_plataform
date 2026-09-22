from unittest.mock import MagicMock
import pytest

from openflow_engine import (
    CycleError,
    FilterNode,
    InMemoryConnector,
    InputNode,
    JoinNode,
    OutputNode,
    PySparkPipelineRunner,
    SparkConnectionConfig,
    SparkSessionManager,
)


def test_spark_connection_config_defaults() -> None:
    config = SparkConnectionConfig(
        master="spark://cluster:7077",
        app_name="TestApp",
        connect_url="sc://spark-master:15002",
    )
    assert config.master == "spark://cluster:7077"
    assert config.app_name == "TestApp"
    assert config.connect_url == "sc://spark-master:15002"


def test_pyspark_runner_validates_cycles() -> None:
    with pytest.raises(CycleError):
        PySparkPipelineRunner(
            nodes={"n1": FilterNode("x > 1"), "n2": FilterNode("x > 2")},
            edges=[("n1", "n2"), ("n2", "n1")],
        )


def test_pyspark_runner_translates_and_executes_with_spark_mock() -> None:
    # Create mock Spark Session and DataFrame
    mock_spark = MagicMock()
    mock_df_in1 = MagicMock()
    mock_df_in2 = MagicMock()
    mock_df_joined = MagicMock()

    mock_df_in1.columns = ["user_id", "name"]
    mock_df_in2.columns = ["user_id", "salary"]
    mock_df_in1.join.return_value = mock_df_joined

    mock_connector = MagicMock()
    mock_connector.read_spark.side_effect = [mock_df_in1, mock_df_in2]

    runner = PySparkPipelineRunner(
        nodes={
            "users": InputNode(mock_connector, "tenant-1", "users.parquet"),
            "salaries": InputNode(mock_connector, "tenant-1", "salaries.parquet"),
            "join": JoinNode(on="user_id", how="inner"),
            "out": OutputNode(mock_connector, "tenant-1", "out.parquet"),
        },
        edges=[
            ("users", "join"),
            ("salaries", "join"),
            ("join", "out"),
        ],
        spark_session=mock_spark,
    )

    result = runner.run()

    # Verify nodes ran and generated logs
    assert len(result.logs) == 4
    assert all(l.status == "succeeded" for l in result.logs)
    assert mock_connector.read_spark.call_count == 2
    mock_df_in1.join.assert_called_once_with(mock_df_in2, on=["user_id"], how="inner")
    mock_connector.write_spark.assert_called_once_with("tenant-1", "out.parquet", mock_df_joined, None)

