import tkinter as tk
import pandas as pd
import pytest

from openflow_ui.app import OpenFlowLocalApp


@pytest.fixture
def tk_app():
    """Provides a headless/hidden Tkinter root and OpenFlowLocalApp instance."""
    root = tk.Tk()
    root.withdraw()  # Hide window during test session
    app = OpenFlowLocalApp(root)
    yield app
    root.destroy()


def test_ui_initialization(tk_app: OpenFlowLocalApp) -> None:
    # Verify initial dataset and state
    assert tk_app.current_engine == "pyspark"
    assert len(tk_app.current_df) == 100
    assert "order_id" in tk_app.current_df.columns
    assert tk_app.schema_listbox.size() > 0
    assert "[STATUS: READY]" in tk_app.telemetry_lbl.cget("text")


def test_ui_preset_switching(tk_app: OpenFlowLocalApp) -> None:
    # Switch to IOT Telemetry
    tk_app.preset_var.set("IOT_TELEMETRY")
    tk_app._on_preset_selected()

    assert "device_id" in tk_app.current_df.columns
    assert "temperature" in tk_app.current_df.columns
    assert len(tk_app.current_df) == 100
    assert "iot_telemetry.csv" in tk_app.dataset_info_lbl.cget("text")


def test_ui_engine_switching(tk_app: OpenFlowLocalApp) -> None:
    # Switch to SQL engine
    tk_app.set_engine("sql")
    assert tk_app.current_engine == "sql"
    assert "SELECT" in tk_app.code_text.get("1.0", "end")

    # Switch to Safe AST engine
    tk_app.set_engine("ast_filter")
    assert tk_app.current_engine == "ast_filter"
    assert "amount" in tk_app.code_text.get("1.0", "end")


def test_ui_execution_sql_query(tk_app: OpenFlowLocalApp) -> None:
    tk_app.preset_var.set("ECOMMERCE_SALES")
    tk_app._on_preset_selected()

    tk_app.set_engine("sql")
    query = "SELECT country, COUNT(order_id) AS cnt FROM data GROUP BY country"
    tk_app.code_text.delete("1.0", "end")
    tk_app.code_text.insert("1.0", query)

    tk_app.run_transformation()

    # Check telemetry label and treeview rows
    telemetry = tk_app.telemetry_lbl.cget("text")
    assert "SUCCEEDED" in telemetry
    children = tk_app.tree.get_children()
    assert len(children) > 0
    assert "country" in tk_app.tree["columns"]
    assert "cnt" in tk_app.tree["columns"]


def test_ui_execution_ast_filter(tk_app: OpenFlowLocalApp) -> None:
    tk_app.preset_var.set("ECOMMERCE_SALES")
    tk_app._on_preset_selected()

    tk_app.set_engine("ast_filter")
    tk_app.code_text.delete("1.0", "end")
    tk_app.code_text.insert("1.0", "amount > 200.0 and status == 'Completed'")

    tk_app.run_transformation()

    telemetry = tk_app.telemetry_lbl.cget("text")
    assert "SUCCEEDED" in telemetry
    children = tk_app.tree.get_children()
    assert len(children) > 0


def test_ui_execution_error_reporting(tk_app: OpenFlowLocalApp) -> None:
    tk_app.set_engine("pandas")
    tk_app.code_text.delete("1.0", "end")
    tk_app.code_text.insert("1.0", "df_out = 1 / 0")

    tk_app.run_transformation()

    telemetry = tk_app.telemetry_lbl.cget("text")
    assert "FAILED" in telemetry
    assert "division by zero" in telemetry
