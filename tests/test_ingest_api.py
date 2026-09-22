from openflow_api.app import (
    LoadPresetRequest,
    TransformExecuteRequest,
    UploadDatasetRequest,
    execute_transform,
    load_preset,
    serve_ui,
    upload_dataset,
)
from openflow_api.deps import TenantContext


def test_serve_ui_returns_html() -> None:
    res = serve_ui()
    assert "OpenFlow ELT Platform" in res.content
    assert "monaco-editor" in res.content


def test_load_preset_and_execute_transform() -> None:
    tenant = TenantContext(org_id="test-tenant", project_id="test-proj")

    # 1. Load preset
    preset_res = load_preset(LoadPresetRequest(preset="ecommerce"), tenant=tenant)
    assert preset_res["status"] == "ingested"
    assert preset_res["row_count"] == 100
    assert "amount" in preset_res["columns"]

    # 2. Execute transform on ingested data
    req = TransformExecuteRequest(
        dataset_key=preset_res["key"],
        engine="ast_filter",
        code="amount > 100",
        limit=10,
    )
    tx_res = execute_transform(req, tenant=tenant)

    assert tx_res["status"] == "succeeded"
    assert len(tx_res["records"]) <= 10
    assert all(r["amount"] > 100 for r in tx_res["records"])


def test_upload_custom_csv_and_sql_transform() -> None:
    tenant = TenantContext(org_id="test-tenant", project_id="test-proj")

    csv_content = """item,qty,price
apple,10,1.5
banana,5,2.0
orange,8,3.0
"""
    upload_res = upload_dataset(
        UploadDatasetRequest(filename="fruits.csv", content=csv_content),
        tenant=tenant,
    )
    assert upload_res["status"] == "ingested"
    assert upload_res["row_count"] == 3

    # Execute SQL
    sql_req = TransformExecuteRequest(
        dataset_key="fruits.csv",
        engine="sql",
        code="SELECT item, (qty * price) AS subtotal FROM data WHERE qty >= 8",
        limit=10,
    )
    sql_res = execute_transform(sql_req, tenant=tenant)
    assert sql_res["status"] == "succeeded"
    assert sql_res["row_count"] == 2
    assert sql_res["records"][0]["item"] == "apple"
    assert sql_res["records"][0]["subtotal"] == 15.0
