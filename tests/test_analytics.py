from typing import Any
import pandas as pd
import pytest

from openflow_ui.analytics import AnalyticsEngine, InteractiveChartCanvas


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "category": ["Electronics", "Clothing", "Electronics", "Home", "Clothing", "Electronics"],
        "amount": [150.0, 50.0, 200.0, 75.0, 25.0, 100.0],
        "status": ["Completed", "Pending", "Completed", "Refunded", "Completed", "Completed"]
    })


def test_analytics_summary_stats(sample_df: pd.DataFrame) -> None:
    stats = AnalyticsEngine.compute_summary_stats(sample_df, "amount")
    assert stats["count"] == 6.0
    assert stats["sum"] == 600.0
    assert stats["mean"] == 100.0
    assert stats["min"] == 25.0
    assert stats["max"] == 200.0
    assert stats["std"] > 0.0

    # Non-numeric column handling
    non_num = AnalyticsEngine.compute_summary_stats(sample_df, "category")
    assert non_num["sum"] == 0.0
    assert non_num["count"] == 6

    # Missing column handling
    missing = AnalyticsEngine.compute_summary_stats(sample_df, "non_existent")
    assert missing["sum"] == 0.0


def test_analytics_aggregate_data_sum_and_avg(sample_df: pd.DataFrame) -> None:
    labels, values = AnalyticsEngine.aggregate_data(sample_df, "category", "amount", agg_func="SUM")
    # Electronics: 150 + 200 + 100 = 450
    # Home: 75
    # Clothing: 50 + 25 = 75
    assert labels[0] == "Electronics"
    assert values[0] == 450.0

    labels_avg, values_avg = AnalyticsEngine.aggregate_data(sample_df, "category", "amount", agg_func="AVG")
    assert labels_avg[0] == "Electronics"
    assert values_avg[0] == 150.0  # 450 / 3


def test_analytics_aggregate_data_count_and_none(sample_df: pd.DataFrame) -> None:
    labels, values = AnalyticsEngine.aggregate_data(sample_df, "status", "amount", agg_func="COUNT")
    assert "Completed" in labels
    idx = labels.index("Completed")
    assert values[idx] == 4.0

    # Unaggregated NONE
    labels_raw, values_raw = AnalyticsEngine.aggregate_data(sample_df, "category", "amount", agg_func="NONE")
    assert len(labels_raw) == 6
    assert values_raw[0] == 150.0


def test_analytics_histogram_binning(sample_df: pd.DataFrame) -> None:
    labels, counts = AnalyticsEngine.compute_histogram(sample_df, "amount", bins=4)
    assert len(labels) == 4
    assert len(counts) == 4
    assert sum(counts) == 6.0

    # Single value edge case
    single_val_df = pd.DataFrame({"val": [10.0, 10.0, 10.0]})
    lbls, cnts = AnalyticsEngine.compute_histogram(single_val_df, "val", bins=4)
    assert len(lbls) == 1
    assert cnts[0] == 3.0


def test_chartjs_payload_generation(sample_df: pd.DataFrame) -> None:
    labels, values = AnalyticsEngine.aggregate_data(sample_df, "category", "amount", agg_func="SUM")
    payload = AnalyticsEngine.to_chartjs_payload("bar", labels, values, title="CATEGORY SUM")
    assert payload["type"] == "bar"
    assert payload["title"] == "CATEGORY SUM"
    assert payload["data"]["labels"] == labels
    assert payload["data"]["datasets"][0]["data"] == values


class MockCanvas:
    """Mock canvas object simulating vector drawing commands."""

    def __init__(self) -> None:
        self.elements: list[dict[str, Any]] = []

    def winfo_width(self) -> int:
        return 600

    def winfo_height(self) -> int:
        return 240

    def delete(self, tag: str) -> None:
        self.elements.clear()

    def create_rectangle(self, *args: Any, **kwargs: Any) -> int:
        self.elements.append({"type": "rect", "args": args, "kwargs": kwargs})
        return len(self.elements)

    def create_line(self, *args: Any, **kwargs: Any) -> int:
        self.elements.append({"type": "line", "args": args, "kwargs": kwargs})
        return len(self.elements)

    def create_text(self, *args: Any, **kwargs: Any) -> int:
        self.elements.append({"type": "text", "args": args, "kwargs": kwargs})
        return len(self.elements)

    def create_oval(self, *args: Any, **kwargs: Any) -> int:
        self.elements.append({"type": "oval", "args": args, "kwargs": kwargs})
        return len(self.elements)

    def create_polygon(self, *args: Any, **kwargs: Any) -> int:
        self.elements.append({"type": "poly", "args": args, "kwargs": kwargs})
        return len(self.elements)


def test_interactive_canvas_plotting() -> None:
    mock = MockCanvas()
    chart = InteractiveChartCanvas(mock)

    # Plot bar
    chart.plot_bar(["A", "B", "C"], [10.0, 20.0, 30.0], title="TEST BAR")
    assert len(mock.elements) > 0

    # Plot line
    chart.plot_line(["A", "B", "C"], [10.0, 20.0, 30.0], title="TEST LINE")
    assert len(mock.elements) > 0

    # Clear
    chart.clear()
    assert len(mock.elements) == 0
