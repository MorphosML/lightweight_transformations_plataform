import pandas as pd
import pytest

from openflow_engine import Edge, InMemoryConnector, InputNode, JoinNode, OutputNode, PipelineRunner


def test_join_node_with_left_and_right_ports() -> None:
    connector = InMemoryConnector(
        {
            "tenant-alpha/users.csv": pd.DataFrame(
                {"user_id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]}
            ),
            "tenant-alpha/orders.csv": pd.DataFrame(
                {"order_id": [101, 102], "user_id": [1, 2], "amount": [250.0, 150.0]}
            ),
        }
    )

    runner = PipelineRunner(
        nodes={
            "users_in": InputNode(connector, "tenant-alpha", "users.csv"),
            "orders_in": InputNode(connector, "tenant-alpha", "orders.csv"),
            "join": JoinNode(on="user_id", how="inner"),
            "out": OutputNode(connector, "tenant-alpha", "joined.csv"),
        },
        edges=[
            Edge(source="users_in", target="join", target_port="left"),
            Edge(source="orders_in", target="join", target_port="right"),
            Edge(source="join", target="out"),
        ],
    )

    result = runner.run()
    joined = result.outputs["join"]

    assert len(joined) == 2
    assert "name" in joined.columns
    assert "amount" in joined.columns
    assert joined[joined["user_id"] == 1]["name"].iloc[0] == "Alice"
    assert joined[joined["user_id"] == 1]["amount"].iloc[0] == 250.0


def test_preview_executes_only_upstream_dependencies_and_bounds_rows() -> None:
    connector = InMemoryConnector(
        {
            "tenant-alpha/large.csv": pd.DataFrame(
                {"id": list(range(1000)), "val": list(range(1000))}
            )
        }
    )

    runner = PipelineRunner(
        nodes={
            "src": InputNode(connector, "tenant-alpha", "large.csv"),
            "sink": OutputNode(connector, "tenant-alpha", "out.csv"),
        },
        edges=[("src", "sink")],
    )

    preview_result = runner.preview("src", limit=5)
    assert len(preview_result) == 5
    # The output node was never run
    with pytest.raises(KeyError):
        connector.read("tenant-alpha", "out.csv")

