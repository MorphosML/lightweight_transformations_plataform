import tkinter as tk
import pandas as pd
import pytest

from openflow_ui.analytics import AnalyticsEngine, InteractiveChartCanvas
from openflow_ui.app import OpenFlowLocalApp


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


@pytest.fixture
def tk_app():
    root = tk.Tk()
    root.withdraw()
    app = OpenFlowLocalApp(root)
    yield app
    root.destroy()


def test_interactive_canvas_plotting(tk_app: OpenFlowLocalApp) -> None:
    canvas_widget = tk.Canvas(tk_app.root, width=400, height=200)
    chart = InteractiveChartCanvas(canvas_widget)

    # Plot bar
    chart.plot_bar(["A", "B", "C"], [10.0, 20.0, 30.0], title="TEST BAR")
    assert len(canvas_widget.find_all()) > 0

    # Plot line
    chart.plot_line(["A", "B", "C"], [10.0, 20.0, 30.0], title="TEST LINE")
    assert len(canvas_widget.find_all()) > 0

    # Clear and redraw
    chart.redraw()
    assert len(canvas_widget.find_all()) > 0
    chart.clear()
    assert len(canvas_widget.find_all()) == 0


def test_studio_bottom_panel_analytics_toggle(tk_app: OpenFlowLocalApp) -> None:
    # Switch to analytics tab
    tk_app.switch_bottom_panel("analytics")
    assert tk_app.analytics_container.winfo_manager() == "pack"

    # Verify summary stats label populated
    stats_text = tk_app.analytics_stats_lbl.cget("text")
    assert "STATS [" in stats_text
    assert "COUNT:" in stats_text
    assert "MEAN:" in stats_text

    # Change chart type to HISTOGRAM and re-plot
    tk_app.chart_type_combo.set("HISTOGRAM")
    tk_app.update_analytics_plot()
    assert "FREQUENCY DISTRIBUTION" in tk_app.chart_canvas._last_plot_args["title"]

    # Change chart type to LINE
    tk_app.chart_type_combo.set("LINE")
    tk_app.update_analytics_plot()
    assert "TREND BY" in tk_app.chart_canvas._last_plot_args["title"]

    # Switch back to preview
    tk_app.switch_bottom_panel("preview")
    assert tk_app.table_container.winfo_manager() == "pack"
