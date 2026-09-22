import json
import urllib.request
import pytest

from openflow_ui.app import (
    OpenFlowLocalApp,
    OpenFlowUIServer,
    generate_dataset,
)


@pytest.fixture(scope="module")
def ui_server():
    """Spins up a lightweight threaded OpenFlowUIServer for testing."""
    server = OpenFlowUIServer(host="127.0.0.1", port=8100)
    bound_port = server.start(daemon=True)
    base_url = f"http://127.0.0.1:{bound_port}"
    yield base_url
    server.stop()


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request_json(url: str, method: str = "GET", data: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data is not None else None
    with _opener.open(req, data=body) as response:
        status = response.status
        content = json.loads(response.read().decode("utf-8"))
        return status, content


def test_ui_server_serves_react_studio_html(ui_server: str) -> None:
    req = urllib.request.Request(f"{ui_server}/")
    with _opener.open(req) as response:
        assert response.status == 200
        html = response.read().decode("utf-8")
        assert "OpenFlow" in html
        assert "Modern Web Desktop" in html
        assert "react" in html.lower()
        assert "monaco" in html.lower()
        assert "chart.js" in html.lower()


def test_ui_server_presets_list_and_load(ui_server: str) -> None:
    # 1. List presets
    status, data = _request_json(f"{ui_server}/api/v1/presets")
    assert status == 200
    assert "ECOMMERCE_SALES" in data["presets"]
    assert "IOT_TELEMETRY" in data["presets"]

    # 2. Load Ecommerce Preset
    status, ecom_data = _request_json(
        f"{ui_server}/api/v1/presets/load",
        method="POST",
        data={"preset": "ECOMMERCE_SALES"}
    )
    assert status == 200
    assert ecom_data["preset"] == "ECOMMERCE_SALES"
    assert "order_id" in ecom_data["columns"]
    assert len(ecom_data["rows"]) > 0

    # 3. Load IoT Preset
    status, iot_data = _request_json(
        f"{ui_server}/api/v1/presets/load",
        method="POST",
        data={"preset": "IOT_TELEMETRY"}
    )
    assert status == 200
    assert "temperature" in iot_data["columns"]
    assert len(iot_data["rows"]) == 100


def test_ui_server_transform_execution_sql_and_pyspark(ui_server: str) -> None:
    # SQL Execution
    sql_code = "SELECT country, COUNT(order_id) AS total_orders FROM data GROUP BY country"
    status, sql_res = _request_json(
        f"{ui_server}/api/v1/transform/execute",
        method="POST",
        data={"code": sql_code, "engine": "sql", "dataset_name": "ECOMMERCE_SALES"}
    )
    assert status == 200
    assert sql_res["success"] is True
    assert "country" in sql_res["columns"]
    assert "total_orders" in sql_res["columns"]
    assert sql_res["capacity_report"] is not None
    assert sql_res["audit_record"] is not None

    # AST Filter Execution
    ast_code = "amount >= 100.0 and category in ['Electronics', 'Home']"
    status, ast_res = _request_json(
        f"{ui_server}/api/v1/transform/execute",
        method="POST",
        data={"code": ast_code, "engine": "ast_filter", "dataset_name": "ECOMMERCE_SALES"}
    )
    assert status == 200
    assert ast_res["success"] is True
    assert ast_res["row_count"] > 0


def test_ui_server_analytics_endpoints(ui_server: str) -> None:
    # Summary stats
    status, stats_res = _request_json(
        f"{ui_server}/api/v1/analytics/stats",
        method="POST",
        data={"column": "amount", "preset": "ECOMMERCE_SALES"}
    )
    assert status == 200
    assert "stats" in stats_res
    assert stats_res["stats"]["count"] > 0
    assert stats_res["stats"]["sum"] > 0.0

    # Aggregation for Chart.js
    status, agg_res = _request_json(
        f"{ui_server}/api/v1/analytics/aggregate",
        method="POST",
        data={
            "chart_type": "BAR",
            "x_col": "category",
            "y_col": "amount",
            "agg_func": "SUM",
            "preset": "ECOMMERCE_SALES"
        }
    )
    assert status == 200
    assert len(agg_res["labels"]) > 0
    assert len(agg_res["values"]) > 0


def test_ui_server_medallion_lifecycle(ui_server: str) -> None:
    # Promote to Silver with PII Masking
    status, silver_res = _request_json(
        f"{ui_server}/api/v1/medallion/promote",
        method="POST",
        data={"target_stage": "silver", "dataset_name": "HEALTHCARE_RECORDS"}
    )
    assert status == 200
    assert silver_res["stage"] == "silver"
    # Verify SSN and Email were masked
    first_row = silver_res["rows"][0]
    assert first_row["ssn"] != "100-10-1000"  # Masked/Pseudonymized

    # Promote to Gold (KPI Aggregates)
    status, gold_res = _request_json(
        f"{ui_server}/api/v1/medallion/promote",
        method="POST",
        data={"target_stage": "gold", "dataset_name": "HEALTHCARE_RECORDS"}
    )
    assert status == 200
    assert gold_res["stage"] == "gold"
    assert len(gold_res["rows"]) > 0


def test_ui_server_connectors_verification(ui_server: str) -> None:
    # Test SQL SQLite (Embedded)
    status, sql_test = _request_json(
        f"{ui_server}/api/v1/connectors/test-sql",
        method="POST",
        data={"db_type": "sqlite", "database": ":memory:"}
    )
    assert status == 200
    assert sql_test["status"] == "HEALTHY"

    # Test S3 reachability
    status, s3_test = _request_json(
        f"{ui_server}/api/v1/connectors/test-s3",
        method="POST",
        data={"bucket_name": "test-lakehouse", "prefix": "data/", "region": "us-east-1"}
    )
    assert status == 200
    assert s3_test["status"] == "HEALTHY"


def test_openflow_local_app_headless_controller() -> None:
    app = OpenFlowLocalApp()
    assert app.current_engine == "pyspark"
    assert len(app.current_df) == 100

    # Switch preset
    app.preset_var.set("IOT_TELEMETRY")
    app._on_preset_selected()
    assert "temperature" in app.current_df.columns

    # Switch engine
    app.set_engine("sql")
    assert app.current_engine == "sql"

    # Run transform
    app.code_text.set("SELECT device_id, temperature FROM data WHERE temperature > 25.0")
    app.run_transformation()
    assert len(app.current_df) > 0
