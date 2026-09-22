import tkinter as tk
import pandas as pd
import pytest

from openflow_engine import (
    ConnectorError,
    S3BucketConfig,
    S3BucketConnector,
    SQLDatabaseConfig,
    SQLDatabaseConnector,
    SQLSanitizer,
    SSRFGuard,
    SecurityError,
)
from openflow_ui.app import OpenFlowLocalApp


def test_ssrf_guard_blocks_cloud_metadata() -> None:
    # AWS IMDS v1 & v2
    with pytest.raises(SecurityError, match="blocked"):
        SSRFGuard.validate_endpoint_url("http://169.254.169.254/latest/meta-data/")

    # GCP Metadata
    with pytest.raises(SecurityError, match="blocked"):
        SSRFGuard.validate_endpoint_url("http://metadata.google.internal/computeMetadata/v1/")

    # Link-local IP range
    with pytest.raises(SecurityError, match="blocked"):
        SSRFGuard.validate_endpoint_url("http://169.254.50.1:8080/secret")


def test_ssrf_guard_allows_valid_endpoints() -> None:
    valid_urls = [
        "https://s3.us-east-1.amazonaws.com",
        "https://my-minio-cluster.company.net:9000",
        "http://localhost:5432",
    ]
    for url in valid_urls:
        assert SSRFGuard.validate_endpoint_url(url, allow_localhost=True) == url


def test_sql_sanitizer_blocks_destructive_commands() -> None:
    malicious_queries = [
        "SELECT * FROM data; DROP TABLE users;",
        "DROP TABLE customers",
        "ALTER TABLE data DROP COLUMN secret",
        "TRUNCATE TABLE logs",
        "GRANT ALL PRIVILEGES ON data TO hacker",
        "DELETE FROM data WHERE 1=1",
        "ATTACH DATABASE '/etc/passwd' AS pwned",
    ]
    for q in malicious_queries:
        with pytest.raises(SecurityError):
            SQLSanitizer.sanitize_read_query(q)


def test_sql_sanitizer_allows_read_only_queries() -> None:
    safe_queries = [
        "SELECT country, COUNT(*) FROM data GROUP BY country",
        "WITH cleaned AS (SELECT * FROM data WHERE amount > 0) SELECT * FROM cleaned",
        "SELECT * FROM data WHERE status = 'Completed' ORDER BY amount DESC LIMIT 10",
    ]
    for q in safe_queries:
        sanitized = SQLSanitizer.sanitize_read_query(q)
        assert sanitized.startswith("SELECT") or sanitized.startswith("WITH")


def test_sql_database_connector_sqlite() -> None:
    config = SQLDatabaseConfig(engine_type="sqlite", database=":memory:")
    connector = SQLDatabaseConnector(config)

    assert connector.test_connection() is True

    # Write test data
    test_df = pd.DataFrame({"user_id": [1, 2], "score": [95, 88]})
    connector.write("tenant-1", "user_scores", test_df)

    # Read test data
    read_df = connector.read("tenant-1", "user_scores")
    assert len(read_df) == 2
    assert read_df["score"].tolist() == [95, 88]


def test_s3_connector_path_confinement_and_security() -> None:
    config = S3BucketConfig(bucket_name="my-production-bucket", prefix="lakehouse")
    connector = S3BucketConnector(config)

    assert connector.test_connection() is True

    uri = connector._s3_uri("tenant-a", "orders.parquet", project_id="analytics")
    assert uri == "s3a://my-production-bucket/lakehouse/tenant-a/analytics/orders.parquet"

    # Reject traversal
    with pytest.raises(ValueError):
        connector._s3_uri("tenant-a", "../../../etc/passwd")


def test_vscode_ui_sidebar_switching() -> None:
    root = tk.Tk()
    root.withdraw()
    app = OpenFlowLocalApp(root)

    assert app.active_sidebar_view == "explorer"

    # Switch to Connectors sidebar view
    app.switch_sidebar("connectors")
    assert app.active_sidebar_view == "connectors"
    assert "CONNECTORS" in app.sidebar_title_lbl.cget("text")

    # Test SQL and S3 buttons inside UI
    app._test_sql_connection()
    assert "SQL" in app.sb_right.cget("text")

    app._test_s3_connection()
    assert "S3" in app.sb_right.cget("text")

    # Switch back to Explorer view
    app.switch_sidebar("explorer")
    assert app.active_sidebar_view == "explorer"

    root.destroy()

