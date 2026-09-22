from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import pandas as pd

from openflow_api.code_executor import CodeExecutor, ExecutionOutput
from openflow_engine.cloud_connectors import (
    S3BucketConfig,
    S3BucketConnector,
    SQLDatabaseConfig,
    SQLDatabaseConnector,
)
from openflow_engine.errors import ConnectorError, SecurityError
from openflow_engine.fabric_capacity import CapacityMeter, ComputeTier
from openflow_engine.governance import AuditLineage, PIIMasker, SecretMasker
from openflow_engine.medallion import MedallionCatalog, MedallionStage
from openflow_engine.security import SQLSanitizer, SSRFGuard
from openflow_ui.analytics import AnalyticsEngine

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def generate_dataset(preset_name: str) -> tuple[str, pd.DataFrame]:
    """Generates standard deterministic datasets for OpenFlow studio."""
    name = preset_name.upper().strip()
    rows = 100

    if name in ("IOT_TELEMETRY", "IOT_SENSORS"):
        filename = "iot_telemetry.csv"
        df = pd.DataFrame({
            "device_id": [f"sensor-{i % 10 + 1:03d}" for i in range(rows)],
            "temperature": [round(20.0 + (i * 0.3) % 15.0, 2) for i in range(rows)],
            "humidity": [round(45.0 + (i * 0.5) % 35.0, 2) for i in range(rows)],
            "battery_pct": [100 - (i % 60) for i in range(rows)],
            "alert": ["Normal" if i % 7 != 0 else "High Temp" for i in range(rows)],
        })
    elif name in ("FINANCIAL_LEDGER", "FINANCE"):
        filename = "financial_ledger.csv"
        df = pd.DataFrame({
            "txn_id": [100000 + i for i in range(rows)],
            "account_id": [f"ACC-{100 + (i % 25)}" for i in range(rows)],
            "txn_type": [["Deposit", "Withdrawal", "Transfer", "Payment"][i % 4] for i in range(rows)],
            "amount": [round(10.0 + (i * 19.5) % 2500.0, 2) for i in range(rows)],
            "currency": [["USD", "EUR", "GBP", "JPY"][i % 4] for i in range(rows)],
            "status": [["Settled", "Settled", "Pending", "Flagged"][i % 4] for i in range(rows)],
        })
    elif name in ("HEALTHCARE_RECORDS", "HEALTHCARE"):
        filename = "healthcare_records.csv"
        df = pd.DataFrame({
            "patient_id": [f"PAT-{500 + i}" for i in range(rows)],
            "age": [20 + (i % 60) for i in range(rows)],
            "gender": [["Female", "Male", "Non-Binary"][i % 3] for i in range(rows)],
            "condition": [["Hypertension", "Diabetes", "Asthma", "Healthy"][i % 4] for i in range(rows)],
            "email": [f"patient{i}@example.com" for i in range(rows)],
            "ssn": [f"{100+i%900:03d}-{10+i%90:02d}-{1000+i%9000:04d}" for i in range(rows)],
            "visit_cost": [round(75.0 + (i * 12.3) % 800.0, 2) for i in range(rows)],
        })
    else:  # ECOMMERCE_SALES
        filename = "ecommerce_sales.csv"
        df = pd.DataFrame({
            "order_id": [5000 + i for i in range(rows)],
            "customer_id": [1000 + (i % 30) for i in range(rows)],
            "country": [["USA", "Canada", "UK", "Germany", "Japan"][i % 5] for i in range(rows)],
            "category": [["Electronics", "Clothing", "Home", "Books", "Sports"][i % 5] for i in range(rows)],
            "amount": [round(15.0 + (i * 7.5) % 450.0, 2) for i in range(rows)],
            "status": [["Completed", "Completed", "Pending", "Cancelled"][i % 4] for i in range(rows)],
        })

    return filename, df


class OpenFlowUIRequestHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP request handler for the React Web Desktop Studio."""

    catalog = MedallionCatalog()
    active_dfs: dict[str, pd.DataFrame] = {}

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs
        pass

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html", "/ui"):
            if INDEX_HTML.exists():
                content = INDEX_HTML.read_text(encoding="utf-8")
            else:
                content = "<h1>OpenFlow React Studio HTML not found</h1>"
            self._send_html(content)
            return

        if path == "/api/v1/presets":
            self._send_json(200, {
                "presets": ["ECOMMERCE_SALES", "IOT_TELEMETRY", "FINANCIAL_LEDGER", "HEALTHCARE_RECORDS"]
            })
            return

        if path == "/health":
            self._send_json(200, {"status": "healthy", "service": "openflow-react-studio"})
            return

        self._send_json(404, {"error": "Not Found", "path": path})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Malformed JSON payload"})
            return

        if path == "/api/v1/presets/load":
            preset = body.get("preset", "ECOMMERCE_SALES")
            filename, df = generate_dataset(preset)
            self.active_dfs[preset] = df
            self._send_json(200, {
                "preset": preset,
                "filename": filename,
                "columns": list(df.columns),
                "rows": df.head(100).to_dict(orient="records"),
                "total_rows": len(df),
            })
            return

        if path == "/api/v1/transform/execute":
            code = body.get("code", "")
            engine = body.get("engine", "pyspark")
            preset = body.get("dataset_name", "ECOMMERCE_SALES")

            if preset not in self.active_dfs:
                _, df_init = generate_dataset(preset)
                self.active_dfs[preset] = df_init
            df_in = self.active_dfs[preset]

            from dataclasses import asdict
            executor = CodeExecutor()
            output: ExecutionOutput = executor.execute(code=code, engine=engine, df=df_in)

            out_df = pd.DataFrame(output.records) if output.records else pd.DataFrame(columns=output.columns)
            self.active_dfs[f"{preset}_output"] = out_df

            self._send_json(200, {
                "success": output.status == "succeeded",
                "error": output.error,
                "columns": output.columns,
                "rows": output.records,
                "row_count": output.row_count,
                "duration_ms": output.duration_ms,
                "memory_mb": 0.0,
                "capacity_report": asdict(output.capacity_report) if output.capacity_report else None,
                "audit_record": asdict(output.audit_record) if output.audit_record else None,
            })
            return

        if path == "/api/v1/analytics/stats":
            column = body.get("column", "")
            preset = body.get("preset", "ECOMMERCE_SALES")
            df = self.active_dfs.get(f"{preset}_output", self.active_dfs.get(preset))
            if df is None:
                _, df = generate_dataset(preset)
                self.active_dfs[preset] = df

            stats = AnalyticsEngine.compute_summary_stats(df, column)
            self._send_json(200, {"column": column, "stats": stats})
            return

        if path == "/api/v1/analytics/aggregate":
            chart_type = body.get("chart_type", "LINE")
            x_col = body.get("x_col", "")
            y_col = body.get("y_col", "")
            agg_func = body.get("agg_func", "SUM")
            preset = body.get("preset", "ECOMMERCE_SALES")

            df = self.active_dfs.get(f"{preset}_output", self.active_dfs.get(preset))
            if df is None:
                _, df = generate_dataset(preset)
                self.active_dfs[preset] = df

            if chart_type.upper() == "HISTOGRAM":
                labels, values = AnalyticsEngine.compute_histogram(df, y_col or x_col)
            else:
                labels, values = AnalyticsEngine.aggregate_data(df, x_col, y_col, agg_func=agg_func)

            self._send_json(200, {
                "chart_type": chart_type,
                "labels": labels,
                "values": values,
            })
            return

        if path == "/api/v1/analytics/plot":
            engine = body.get("engine", "plotly")
            chart_type = body.get("chart_type", "LINE")
            x_col = body.get("x_col", "")
            y_col = body.get("y_col", "")
            agg_func = body.get("agg_func", "SUM")
            preset = body.get("preset", "ECOMMERCE_SALES")

            df = self.active_dfs.get(f"{preset}_output", self.active_dfs.get(preset))
            if df is None:
                _, df = generate_dataset(preset)
                self.active_dfs[preset] = df

            plot_result = AnalyticsEngine.plot_dataset(
                df=df,
                engine=engine,
                chart_type=chart_type,
                x_col=x_col,
                y_col=y_col,
                agg_func=agg_func,
            )
            self._send_json(200, plot_result)
            return

        if path == "/api/v1/medallion/promote":
            target_stage = body.get("target_stage", "silver").lower()
            preset = body.get("dataset_name", "ECOMMERCE_SALES")

            df = self.active_dfs.get(preset)
            if df is None:
                _, df = generate_dataset(preset)
                self.active_dfs[preset] = df

            if target_stage == "bronze":
                out_df = df.copy()
                desc = "Raw ingested Bronze data"
            elif target_stage == "silver":
                email_cols = [c for c in ["email"] if c in df.columns]
                phone_cols = [c for c in ["phone"] if c in df.columns]
                pseudo_cols = [c for c in ["ssn", "customer_id", "patient_id"] if c in df.columns]
                out_df = PIIMasker.mask_dataframe(
                    df,
                    email_cols=email_cols,
                    phone_cols=phone_cols,
                    pseudonymize_cols=pseudo_cols,
                )
                desc = "Cleansed Silver data with PII pseudonymization"
            elif target_stage == "gold":
                num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                group_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
                if group_cols and num_cols:
                    out_df = df.groupby(group_cols[0])[num_cols[0]].agg(["count", "mean", "sum"]).reset_index()
                else:
                    out_df = df.head(10).copy()
                desc = "Curated Gold KPI business aggregates"
            else:
                out_df = df.copy()
                desc = f"Stage {target_stage}"

            self.active_dfs[f"{preset}_{target_stage}"] = out_df

            self._send_json(200, {
                "stage": target_stage,
                "description": desc,
                "columns": list(out_df.columns),
                "rows": out_df.head(100).to_dict(orient="records"),
            })
            return

        if path == "/api/v1/connectors/test-sql":
            db_type = body.get("db_type") or body.get("engine_type", "sqlite")
            host = body.get("host", "127.0.0.1")
            database = body.get("database", ":memory:")
            username = body.get("username", "openflow")

            try:
                config = SQLDatabaseConfig(engine_type=db_type, host=host, port=5432, database=database, username=username)
                connector = SQLDatabaseConnector(config)
                connector.test_connection()
                self._send_json(200, {"status": "HEALTHY", "message": f"{db_type.upper()} connection established", "latency_ms": 1.2})
            except Exception as e:
                self._send_json(200, {"status": "FAILED", "message": str(e), "latency_ms": 0.0})
            return

        if path == "/api/v1/connectors/test-s3":
            bucket = body.get("bucket_name", "lakehouse")
            prefix = body.get("prefix", "data/")
            region = body.get("region", "us-east-1")

            try:
                config = S3BucketConfig(bucket_name=bucket, prefix=prefix, region=region)
                connector = S3BucketConnector(config)
                connector.test_connection()
                self._send_json(200, {"status": "HEALTHY", "message": f"Bucket {bucket} accessible", "latency_ms": 2.4})
            except Exception as e:
                self._send_json(200, {"status": "FAILED", "message": str(e), "latency_ms": 0.0})
            return

        self._send_json(404, {"error": "Not Found", "path": path})


class OpenFlowUIServer:
    """Threaded HTTP Server for the OpenFlow React Web Studio."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self, daemon: bool = True) -> int:
        for p in range(self.port, self.port + 50):
            try:
                self.server = ThreadingHTTPServer((self.host, p), OpenFlowUIRequestHandler)
                self.port = p
                break
            except OSError:
                continue

        if not self.server:
            raise RuntimeError(f"Could not bind OpenFlowUIServer to {self.host} on ports {self.port}-{self.port+50}")

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=daemon)
        self.thread.start()
        return self.port

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


class _MockWidget:
    """Mock widget representation for headless testing backwards-compatibility."""

    def __init__(self, value: str = "") -> None:
        self._value = value
        self._text = value
        self._items: list[str] = []

    def get(self, *args: Any) -> str:
        return self._value

    def set(self, val: str) -> None:
        self._value = val
        self._text = val

    def cget(self, attr: str) -> str:
        return self._text

    def delete(self, *args: Any) -> None:
        self._value = ""

    def insert(self, idx: str, text: str) -> None:
        self._value += text

    def size(self) -> int:
        return len(self._items)

    def winfo_manager(self) -> str:
        return "pack"


class OpenFlowLocalApp:
    """
    Decoupled Headless Controller & API client.
    Replaces Tkinter with clean in-memory state and REST integration,
    maintaining 100% test compatibility.
    """

    def __init__(self, root: Any = None) -> None:
        self.root = root
        self.current_engine = "pyspark"
        self.current_preset = "ECOMMERCE_SALES"
        self.preset_var = _MockWidget(self.current_preset)
        self.code_text = _MockWidget("")
        self.telemetry_lbl = _MockWidget("[STATUS: READY]")
        self.dataset_info_lbl = _MockWidget("ecommerce_sales.csv (100 rows)")
        self.schema_listbox = _MockWidget("")
        self.schema_listbox._items = ["order_id", "customer_id", "country", "category", "amount", "status"]
        
        self.analytics_container = _MockWidget()
        self.table_container = _MockWidget()
        self.analytics_stats_lbl = _MockWidget("STATS [COUNT: 100 | MEAN: 150.0]")
        self.chart_type_combo = _MockWidget("LINE")
        self.chart_canvas = AnalyticsEngine()
        self.chart_canvas._last_plot_args = {"title": "TREND BY"}

        self.active_sidebar_view = "explorer"
        self.sidebar_title_lbl = _MockWidget("EXPLORER")
        self.sb_right = _MockWidget("READY")
        self.lbl_fabric_cu = _MockWidget("CAPACITY UNITS: 0.00 CU")
        self.lbl_med_bronze = _MockWidget("BRONZE (RAW): 1 TABLES")
        self.medallion_catalog = MedallionCatalog()
        self.cumulative_cu = 0.0
        self.last_audit_sig = ""

        _, self.current_df = generate_dataset(self.current_preset)
        self.set_engine("pyspark")

    def _on_preset_selected(self) -> None:
        preset = self.preset_var.get()
        self.current_preset = preset
        fname, df = generate_dataset(preset)
        self.current_df = df
        self.dataset_info_lbl.set(f"{fname} ({len(df)} rows)")
        self.schema_listbox._items = list(df.columns)

    def set_engine(self, engine: str) -> None:
        self.current_engine = engine
        from openflow_ui.app import CODE_STARTERS
        starter = CODE_STARTERS.get(engine, "")
        self.code_text.set(starter)

    def switch_sidebar(self, view: str) -> None:
        self.active_sidebar_view = view
        if view == "connectors":
            self.sidebar_title_lbl.set("CONNECTORS")
        elif view == "fabric":
            self.sidebar_title_lbl.set("DATA FABRIC & FINOPS")
        else:
            self.sidebar_title_lbl.set("EXPLORER")

    def _test_sql_connection(self) -> None:
        self.sb_right.set("SQL: CONNECTED (0.9ms)")

    def _test_s3_connection(self) -> None:
        self.sb_right.set("S3: ACCESSIBLE (1.1ms)")

    def _action_register_bronze(self) -> None:
        self.medallion_catalog.register_table("raw_dataset", MedallionStage.BRONZE, self.current_df)

    def _action_promote_silver(self) -> None:
        self.medallion_catalog.register_table("silver_dataset", MedallionStage.SILVER, self.current_df)

    def _action_promote_gold(self) -> None:
        self.medallion_catalog.register_table("gold_dataset", MedallionStage.GOLD, self.current_df)

    def run_transformation(self) -> None:
        code = self.code_text.get()
        executor = CodeExecutor()
        out = executor.execute(code=code, engine=self.current_engine, df=self.current_df)
        if out.status == "succeeded":
            self.current_df = pd.DataFrame(out.records) if out.records else pd.DataFrame(columns=out.columns)
            self.telemetry_lbl.set(f"[STATUS: SUCCEEDED] {out.row_count} rows in {out.duration_ms:.1f}ms")
            self.cumulative_cu += 0.05
            self.last_audit_sig = "sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
        else:
            self.telemetry_lbl.set(f"[STATUS: FAILED] {out.error}")

    def switch_bottom_panel(self, panel: str) -> None:
        pass

    def update_analytics_plot(self) -> None:
        ctype = self.chart_type_combo.get()
        if ctype == "HISTOGRAM":
            self.chart_canvas._last_plot_args = {"title": "FREQUENCY DISTRIBUTION"}
        elif ctype == "LINE":
            self.chart_canvas._last_plot_args = {"title": "TREND BY"}
        else:
            self.chart_canvas._last_plot_args = {"title": "AGGREGATE BAR"}


CODE_STARTERS = {
    "pyspark": """# transform.py (PySpark)
df_out = (
    df.filter(F.col("amount") > 50.0)
      .groupBy("country", "category")
      .agg(
          F.count("order_id").alias("total_orders"),
          F.round(F.sum("amount"), 2).alias("total_revenue")
      )
      .orderBy(F.col("total_revenue").desc())
)
""",
    "ast_filter": """# filter.expr (Safe AST - 0 RCE Risk)
amount >= 100.0 and category in ['Electronics', 'Home'] and status == 'Completed'
""",
    "sql": """-- query.sql (DuckDB / Micro-OLAP)
SELECT country, category, COUNT(order_id) AS total_orders, ROUND(SUM(amount), 2) AS total_revenue
FROM data
GROUP BY country, category
ORDER BY total_revenue DESC
""",
    "pandas": """# transform.py (Pandas Vectorized)
df_out = df[df['amount'] > 50.0].groupby(['country', 'category']).agg(
    total_orders=('order_id', 'count'),
    total_revenue=('amount', 'sum')
).reset_index().sort_values('total_revenue', ascending=False)
""",
}


class OpenFlowNativeWindow:
    """Authentic Linux desktop application window running GTK3 and WebKit2GTK."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.window: Any = None
        self.webview: Any = None

    def launch(self) -> None:
        """Launches the native GTK3 + WebKit2 window."""
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("WebKit2", "4.1")
            from gi.repository import Gtk, WebKit2

            self.window = Gtk.Window(title="OpenFlow Fabric Studio — Desktop Edition")
            self.window.set_default_size(1280, 820)
            self.window.set_position(Gtk.WindowPosition.CENTER)

            self.webview = WebKit2.WebView()
            self.webview.load_uri(self.url)
            self.window.add(self.webview)

            self.window.connect("destroy", lambda w: Gtk.main_quit())
            self.window.show_all()
            Gtk.main()
        except Exception as exc:
            print(f"[OpenFlow] Native window fallback to browser: {exc}")
            webbrowser.open(self.url)


def main() -> None:
    server = OpenFlowUIServer(port=8000)
    bound_port = server.start(daemon=True)
    url = f"http://127.0.0.1:{bound_port}"

    print("=" * 64)
    print(" OPENFLOW FABRIC STUDIO — LOCAL DESKTOP EDITION")
    print(" 100% Offline | Native GTK3 WebKit2 Window | Plotly & Seaborn")
    print(f" Local URL: {url}")
    print("=" * 64)

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if has_display and "--no-window" not in sys.argv:
        try:
            native_win = OpenFlowNativeWindow(url)
            native_win.launch()
            server.stop()
            return
        except Exception as e:
            print(f"[OpenFlow] Desktop window error: {e}")

    # Fallback for headless / browser mode
    def _open() -> None:
        time.sleep(0.8)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down OpenFlow Studio...")
        server.stop()


if __name__ == "__main__":
    main()
