import pytest

from openflow_api.app import (
    LoadPresetRequest,
    MedallionRequest,
    S3CheckRequest,
    SQLCheckRequest,
    TransformExecuteRequest,
    api_promote_gold,
    api_promote_silver,
    api_register_bronze,
    check_s3_endpoint,
    check_sql_endpoint,
    execute_transform,
    get_medallion_tables,
    load_preset,
    serve_ui,
)
from openflow_api.deps import TenantContext


def test_serve_web_studio_html() -> None:
    res = serve_ui()
    assert "OpenFlow" in res.content
    assert "code-editor" in res.content
    assert "plot-target" in res.content
    # Strict all-local rule: ensure zero external CDN dependencies
    assert "https://" not in res.content
    assert "monaco-editor" not in res.content
    assert "chart.js" not in res.content


def test_api_transform_execute_with_capacity_and_audit() -> None:
    tenant = TenantContext(org_id="test-org", project_id="test-proj")
    load_preset(LoadPresetRequest(preset="ecommerce"), tenant=tenant)

    req = TransformExecuteRequest(
        dataset_key="ecommerce_sales.csv",
        engine="sql",
        code="SELECT country, COUNT(order_id) AS cnt FROM data GROUP BY country",
        limit=50,
    )
    data = execute_transform(req, tenant=tenant)
    assert data["status"] == "succeeded"
    assert data["row_count"] > 0
    assert "capacity_report" in data
    assert data["capacity_report"] is not None
    assert data["capacity_report"]["tier_used"] == "TIER_0_EMBEDDED"
    assert "audit_record" in data
    assert data["audit_record"] is not None
    assert data["audit_record"]["manifest_signature"] is not None


def test_api_connectors_check_endpoints() -> None:
    # SQL Endpoint Check
    res_sql = check_sql_endpoint(SQLCheckRequest(engine_type="sqlite", database=":memory:"))
    assert res_sql["status"] == "connected"
    assert res_sql["engine"] == "sqlite"

    # S3 Endpoint Check
    res_s3 = check_s3_endpoint(S3CheckRequest(bucket_name="openflow-lakehouse", region="us-east-1"))
    assert res_s3["status"] == "connected"
    assert res_s3["bucket"] == "openflow-lakehouse"


def test_api_medallion_lifecycle_endpoints() -> None:
    tenant = TenantContext(org_id="test-org", project_id="test-proj")

    # 1. Register Bronze
    res_b = api_register_bronze(MedallionRequest(dataset_key="ecommerce_sales.csv"), tenant=tenant)
    assert res_b["status"] == "registered"

    # 2. Promote Silver
    res_s = api_promote_silver(MedallionRequest(dataset_key="ecommerce_sales.csv"), tenant=tenant)
    assert res_s["status"] == "promoted"

    # 3. Promote Gold
    res_g = api_promote_gold(MedallionRequest(dataset_key="ecommerce_sales.csv"), tenant=tenant)
    assert res_g["status"] == "promoted"

    # 4. List Tables
    tables = get_medallion_tables()
    assert len(tables["bronze"]) > 0
    assert len(tables["silver"]) > 0
    assert len(tables["gold"]) > 0

