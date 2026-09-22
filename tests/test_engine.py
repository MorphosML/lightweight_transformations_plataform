import pandas as pd
import pytest

from openflow_engine import CycleError, InMemoryConnector, InvalidExpressionError, PipelineRunner
from openflow_engine.errors import PipelineExecutionError
from openflow_engine.nodes import FilterNode, InputNode, OutputNode, UnionNode


def test_runner_preserves_multiple_inputs_and_order() -> None:
    connector = InMemoryConnector(
        {
            "tenant-a/left.csv": pd.DataFrame({"value": [1, 2]}),
            "tenant-a/right.csv": pd.DataFrame({"value": [3]}),
        }
    )
    runner = PipelineRunner(
        {
            "left": InputNode(connector, "tenant-a", "left.csv"),
            "right": InputNode(connector, "tenant-a", "right.csv"),
            "union": UnionNode(),
        },
        [("left", "union"), ("right", "union")],
    )

    result = runner.run()

    assert result.outputs["union"]["value"].tolist() == [1, 2, 3]
    assert [log.status for log in result.logs] == ["succeeded"] * 3


def test_runner_rejects_cycles() -> None:
    with pytest.raises(CycleError):
        PipelineRunner({"a": UnionNode(), "b": UnionNode()}, [("a", "b"), ("b", "a")])


def test_filter_rejects_code_execution_syntax() -> None:
    frame = pd.DataFrame({"value": [1]})

    with pytest.raises(InvalidExpressionError):
        FilterNode("__import__('os').system('touch /tmp/pwned')").execute([frame])


def test_filter_supports_columns_literals_and_boolean_logic() -> None:
    frame = pd.DataFrame({"value": [1, 2, 3], "kind": ["a", "b", "a"]})

    result = FilterNode("value >= 2 and kind == 'a'").execute([frame])

    assert result["value"].tolist() == [3]


def test_failed_nodes_are_logged_and_wrapped() -> None:
    connector = InMemoryConnector({"tenant-a/input.csv": pd.DataFrame({"value": [1]})})
    runner = PipelineRunner(
        {
            "input": InputNode(connector, "tenant-a", "input.csv"),
            "filter": FilterNode("missing == 1"),
            "output": OutputNode(connector, "tenant-a", "output.csv"),
        },
        [("input", "filter"), ("filter", "output")],
    )

    with pytest.raises(PipelineExecutionError, match="filter") as error:
        runner.run()

    assert error.value.logs[-1].node_id == "filter"
    assert error.value.logs[-1].status == "failed"
