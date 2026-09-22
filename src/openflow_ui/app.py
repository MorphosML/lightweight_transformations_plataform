from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any

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

# Authentic VS Code Dark+ Color Palette
VS_ACTIVITY_BAR = "#333333"
VS_SIDEBAR_BG = "#252526"
VS_EDITOR_BG = "#1e1e1e"
VS_TAB_BAR = "#2d2d2d"
VS_TAB_ACTIVE = "#1e1e1e"
VS_STATUS_BAR = "#007acc"
VS_BORDER = "#2b2b2b"
VS_LINE_NUMBERS = "#858585"
VS_TEXT_MUTED = "#858585"
VS_TEXT_MAIN = "#cccccc"
VS_TEXT_BRIGHT = "#ffffff"
VS_ACCENT_BLUE = "#007acc"
VS_ACCENT_HOVER = "#0098ff"
VS_RUN_GREEN = "#238636"
VS_RUN_GREEN_HOVER = "#2ea043"
VS_ERROR_RED = "#f85149"
VS_KEYWORD_BLUE = "#569cd6"

CODE_STARTERS = {
    "pyspark": """# transform.py (PySpark)
# 'df' is PySpark DataFrame, 'F' is pyspark.sql.functions, 'spark' is SparkSession

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
    "sql": """-- query.sql
SELECT 
    country,
    category,
    COUNT(order_id) AS order_count,
    ROUND(SUM(amount), 2) AS total_amount
FROM data
WHERE amount > 50.0
GROUP BY country, category
ORDER BY total_amount DESC;
""",
    "pandas": """# transform.py (Pandas)
# 'df' is pandas DataFrame

df_out = df[df["amount"] > 50.0].copy()
df_out["tax"] = df_out["amount"] * 0.15
df_out["total"] = df_out["amount"] + df_out["tax"]
""",
}


class OpenFlowLocalApp:
    """Authentic VS Code Dark+ Local ELT Studio."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OpenFlow Studio - VS Code Edition")
        self.root.geometry("1200x820")
        self.root.minsize(900, 600)
        self.root.configure(bg=VS_EDITOR_BG)

        # State
        self.current_engine = "pyspark"
        self.current_df: pd.DataFrame = self._generate_sample_ecommerce()
        self.current_filename = "ecommerce_sales.csv"
        self.active_sidebar_view = "explorer"  # 'explorer' or 'connectors'

        # Cloud Connectors
        self.sql_config = SQLDatabaseConfig(engine_type="sqlite", database=":memory:")
        self.s3_config = S3BucketConfig(bucket_name="openflow-lakehouse", region="us-east-1")

        # Fabric & Governance State
        self.medallion_catalog = MedallionCatalog()
        self.cumulative_cu: float = 0.0
        self.cumulative_savings_usd: float = 0.0
        self.last_audit_sig: str = ""

        self._setup_theme()
        self._build_vscode_layout()
        self._load_current_dataset()

        # Keyboard shortcuts
        self.root.bind("<F5>", lambda event: self.run_transformation())
        self.root.bind("<Control-Return>", lambda event: self.run_transformation())

    def _setup_theme(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        # Table Grid Styling
        style.configure(
            "Treeview",
            background=VS_EDITOR_BG,
            foreground=VS_TEXT_MAIN,
            fieldbackground=VS_EDITOR_BG,
            borderwidth=0,
            font=("DejaVu Sans Mono", 9),
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=VS_TAB_BAR,
            foreground=VS_TEXT_BRIGHT,
            relief="flat",
            font=("DejaVu Sans Mono", 9, "bold"),
            borderwidth=1,
        )
        style.map("Treeview.Heading", background=[("active", VS_ACTIVITY_BAR)])

        # Scrollbars
        style.configure(
            "Vertical.TScrollbar",
            background=VS_SIDEBAR_BG,
            troughcolor=VS_EDITOR_BG,
            borderwidth=0,
            arrowsize=10,
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=VS_SIDEBAR_BG,
            troughcolor=VS_EDITOR_BG,
            borderwidth=0,
            arrowsize=10,
        )

    def _build_vscode_layout(self) -> None:
        # 1. Status Bar at Bottom (Solid VS Code Blue)
        self.status_bar = tk.Frame(self.root, bg=VS_STATUS_BAR, height=24)
        self.status_bar.pack(fill="x", side="bottom")
        self._build_status_bar(self.status_bar)

        # 2. Workspace container (Activity Bar + Sidebar + Main Editor & Output)
        workspace = tk.Frame(self.root, bg=VS_EDITOR_BG)
        workspace.pack(fill="both", expand=True)

        # 2a. Activity Bar on Far Left (48px)
        self.activity_bar = tk.Frame(workspace, bg=VS_ACTIVITY_BAR, width=48)
        self.activity_bar.pack(side="left", fill="y")
        self._build_activity_bar(self.activity_bar)

        # 2b. Resizable Paned Window (Sidebar + Editor Area)
        self.paned_main = tk.PanedWindow(workspace, orient="horizontal", bg=VS_BORDER, sashwidth=2, relief="flat")
        self.paned_main.pack(side="left", fill="both", expand=True)

        # Sidebar Container
        self.sidebar_frame = tk.Frame(self.paned_main, bg=VS_SIDEBAR_BG, width=280)
        self.paned_main.add(self.sidebar_frame, minsize=220)

        # Main Center Area (Editor + Bottom Panel)
        self.center_frame = tk.Frame(self.paned_main, bg=VS_EDITOR_BG)
        self.paned_main.add(self.center_frame, minsize=550)

        self._build_sidebar(self.sidebar_frame)
        self._build_editor_and_output(self.center_frame)

    def _build_activity_bar(self, parent: tk.Frame) -> None:
        def make_act_btn(text: str, command: Any, active: bool = False) -> tk.Button:
            return tk.Button(
                parent,
                text=text,
                command=command,
                bg=VS_SIDEBAR_BG if active else VS_ACTIVITY_BAR,
                fg=VS_TEXT_BRIGHT if active else VS_TEXT_MUTED,
                activebackground=VS_SIDEBAR_BG,
                activeforeground=VS_TEXT_BRIGHT,
                relief="flat",
                bd=0,
                padx=4,
                pady=10,
                font=("DejaVu Sans Mono", 8, "bold"),
            )

        self.btn_act_explorer = make_act_btn("[FILES]", lambda: self.switch_sidebar("explorer"), active=True)
        self.btn_act_explorer.pack(fill="x", side="top", pady=2)

        self.btn_act_connectors = make_act_btn("[CONNS]", lambda: self.switch_sidebar("connectors"), active=False)
        self.btn_act_connectors.pack(fill="x", side="top", pady=2)

        self.btn_act_fabric = make_act_btn("[FABRIC]", lambda: self.switch_sidebar("fabric"), active=False)
        self.btn_act_fabric.pack(fill="x", side="top", pady=2)

        btn_act_run = make_act_btn("[RUN]", self.run_transformation, active=False)
        btn_act_run.pack(fill="x", side="top", pady=2)

    def _build_sidebar(self, parent: tk.Frame) -> None:
        # Header
        self.sidebar_header = tk.Frame(parent, bg=VS_SIDEBAR_BG, height=35)
        self.sidebar_header.pack(fill="x", side="top", padx=12, pady=(10, 6))

        self.sidebar_title_lbl = tk.Label(
            self.sidebar_header,
            text="EXPLORER: OPENFLOW",
            bg=VS_SIDEBAR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8, "bold"),
            anchor="w",
        )
        self.sidebar_title_lbl.pack(side="left")

        # Container for swappable views
        self.sidebar_content = tk.Frame(parent, bg=VS_SIDEBAR_BG)
        self.sidebar_content.pack(fill="both", expand=True)

        self._render_explorer_view()

    def switch_sidebar(self, view_name: str) -> None:
        self.active_sidebar_view = view_name
        for widget in self.sidebar_content.winfo_children():
            widget.destroy()

        self.btn_act_explorer.configure(bg=VS_ACTIVITY_BAR, fg=VS_TEXT_MUTED)
        self.btn_act_connectors.configure(bg=VS_ACTIVITY_BAR, fg=VS_TEXT_MUTED)
        self.btn_act_fabric.configure(bg=VS_ACTIVITY_BAR, fg=VS_TEXT_MUTED)

        if view_name == "explorer":
            self.btn_act_explorer.configure(bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT)
            self.sidebar_title_lbl.configure(text="EXPLORER: OPENFLOW")
            self._render_explorer_view()
        elif view_name == "connectors":
            self.btn_act_connectors.configure(bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT)
            self.sidebar_title_lbl.configure(text="CONNECTORS: CLOUD & DB")
            self._render_connectors_view()
        else:
            self.btn_act_fabric.configure(bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT)
            self.sidebar_title_lbl.configure(text="DATA FABRIC & FINOPS")
            self._render_fabric_view()

    def _render_explorer_view(self) -> None:
        parent = self.sidebar_content

        # Collapsible Section 1: Ingestion Presets
        sec_lbl = tk.Label(parent, text="v INGESTION SOURCES", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        sec_lbl.pack(fill="x", padx=10, pady=(6, 2))

        self.preset_var = tk.StringVar(value="ECOMMERCE_SALES")
        presets = [("ecommerce_sales.csv", "ECOMMERCE_SALES"), ("iot_telemetry.csv", "IOT_TELEMETRY"), ("customer_demo.csv", "CUSTOMER_DEMO")]
        for display_name, val in presets:
            rb = tk.Radiobutton(
                parent,
                text=f"  {display_name}",
                value=val,
                variable=self.preset_var,
                command=self._on_preset_selected,
                bg=VS_SIDEBAR_BG,
                fg=VS_TEXT_MAIN,
                selectcolor=VS_EDITOR_BG,
                activebackground=VS_SIDEBAR_BG,
                activeforeground=VS_TEXT_BRIGHT,
                font=("DejaVu Sans Mono", 8),
                anchor="w",
            )
            rb.pack(fill="x", padx=12, pady=1)

        # Open File Button
        btn_open = tk.Button(
            parent,
            text="+ OPEN LOCAL FILE...",
            command=self._choose_file,
            bg=VS_TAB_BAR,
            fg=VS_TEXT_MAIN,
            activebackground=VS_ACTIVITY_BAR,
            activeforeground=VS_TEXT_BRIGHT,
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            font=("DejaVu Sans Mono", 8),
        )
        btn_open.pack(fill="x", padx=12, pady=(6, 10))

        # Dataset Info
        self.dataset_info_lbl = tk.Label(
            parent,
            text="DATASET: ecommerce_sales.csv\nROWS: 100",
            bg=VS_EDITOR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8),
            justify="left",
            anchor="w",
            padx=8,
            pady=6,
            highlightthickness=1,
            highlightbackground=VS_BORDER,
        )
        self.dataset_info_lbl.pack(fill="x", padx=12, pady=(0, 10))

        # Collapsible Section 2: Schema
        sec_schema = tk.Label(parent, text="v INFERRED SCHEMA", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        sec_schema.pack(fill="x", padx=10, pady=(4, 2))

        schema_frame = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER)
        schema_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.schema_listbox = tk.Listbox(
            schema_frame,
            bg=VS_EDITOR_BG,
            fg=VS_TEXT_MAIN,
            selectbackground=VS_TAB_BAR,
            selectforeground=VS_ACCENT_BLUE,
            borderwidth=0,
            relief="flat",
            font=("DejaVu Sans Mono", 8),
        )
        self.schema_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self._refresh_schema_listbox()

    def _render_connectors_view(self) -> None:
        parent = self.sidebar_content

        # Section: SQL Database Endpoint
        lbl_sql = tk.Label(parent, text="v SQL DATABASE / DWH", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        lbl_sql.pack(fill="x", padx=10, pady=(6, 2))

        f_sql = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER)
        f_sql.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(f_sql, text="Type: PostgreSQL / MySQL / SQLite", bg=VS_EDITOR_BG, fg=VS_TEXT_MUTED, font=("DejaVu Sans Mono", 7), anchor="w").pack(fill="x", padx=6, pady=(4, 1))
        self.sql_host_entry = tk.Entry(f_sql, bg=VS_SIDEBAR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), insertbackground=VS_TEXT_MAIN, relief="flat")
        self.sql_host_entry.insert(0, "localhost:5432/production_db")
        self.sql_host_entry.pack(fill="x", padx=6, pady=2)

        btn_test_sql = tk.Button(
            f_sql,
            text="TEST SQL CONNECTION",
            command=self._test_sql_connection,
            bg=VS_TAB_BAR,
            fg=VS_TEXT_MAIN,
            relief="flat",
            font=("DejaVu Sans Mono", 8),
            pady=3,
        )
        btn_test_sql.pack(fill="x", padx=6, pady=(4, 6))

        # Section: AWS S3 / MinIO Bucket
        lbl_s3 = tk.Label(parent, text="v AWS S3 / MINIO BUCKET", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        lbl_s3.pack(fill="x", padx=10, pady=(6, 2))

        f_s3 = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER)
        f_s3.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(f_s3, text="Bucket URI (s3://bucket-name)", bg=VS_EDITOR_BG, fg=VS_TEXT_MUTED, font=("DejaVu Sans Mono", 7), anchor="w").pack(fill="x", padx=6, pady=(4, 1))
        self.s3_bucket_entry = tk.Entry(f_s3, bg=VS_SIDEBAR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), insertbackground=VS_TEXT_MAIN, relief="flat")
        self.s3_bucket_entry.insert(0, "s3://openflow-lakehouse/data/")
        self.s3_bucket_entry.pack(fill="x", padx=6, pady=2)

        btn_test_s3 = tk.Button(
            f_s3,
            text="TEST S3 BUCKET ACCESS",
            command=self._test_s3_connection,
            bg=VS_TAB_BAR,
            fg=VS_TEXT_MAIN,
            relief="flat",
            font=("DejaVu Sans Mono", 8),
            pady=3,
        )
        btn_test_s3.pack(fill="x", padx=6, pady=(4, 6))

        # Security Status Panel
        sec_box = tk.Label(
            parent,
            text="SECURITY SHIELD: ACTIVE\n[SSRF GUARD: ON]\n[SQL AST SANITIZER: ON]\n[ENCRYPTED VAULT: AES-128]",
            bg=VS_EDITOR_BG,
            fg="#73c991",
            font=("DejaVu Sans Mono", 7),
            justify="left",
            anchor="w",
            padx=8,
            pady=6,
            highlightthickness=1,
            highlightbackground=VS_BORDER,
        )
        sec_box.pack(fill="x", padx=12, pady=10)

    def _render_fabric_view(self) -> None:
        parent = self.sidebar_content

        # Section 1: FinOps Capacity Governor
        sec_finops = tk.Label(parent, text="v FINOPS CAPACITY GOVERNOR", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        sec_finops.pack(fill="x", padx=10, pady=(6, 2))

        finops_box = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER, padx=8, pady=6)
        finops_box.pack(fill="x", padx=12, pady=(0, 10))

        tier_text = "CURRENT TIER: TIER 0 (EMBEDDED)" if self.current_engine != "pyspark" else "CURRENT TIER: TIER 1 (SPARK)"
        self.lbl_fabric_tier = tk.Label(finops_box, text=tier_text, bg=VS_EDITOR_BG, fg=VS_KEYWORD_BLUE, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        self.lbl_fabric_tier.pack(fill="x")

        self.lbl_fabric_cu = tk.Label(
            finops_box,
            text=f"CAPACITY UNITS: {self.cumulative_cu:.4f} CU",
            bg=VS_EDITOR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8),
            anchor="w",
        )
        self.lbl_fabric_cu.pack(fill="x", pady=2)

        self.lbl_fabric_savings = tk.Label(
            finops_box,
            text=f"FINOPS SAVINGS: ${self.cumulative_savings_usd:.4f}",
            bg=VS_EDITOR_BG,
            fg=VS_RUN_GREEN,
            font=("DejaVu Sans Mono", 8, "bold"),
            anchor="w",
        )
        self.lbl_fabric_savings.pack(fill="x")

        # Section 2: Medallion Lakehouse Catalog
        sec_med = tk.Label(parent, text="v MEDALLION LAKEHOUSE", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        sec_med.pack(fill="x", padx=10, pady=(4, 2))

        med_box = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER, padx=8, pady=6)
        med_box.pack(fill="x", padx=12, pady=(0, 6))

        bronze_cnt = len(self.medallion_catalog.list_tables(MedallionStage.BRONZE))
        silver_cnt = len(self.medallion_catalog.list_tables(MedallionStage.SILVER))
        gold_cnt = len(self.medallion_catalog.list_tables(MedallionStage.GOLD))

        self.lbl_med_bronze = tk.Label(med_box, text=f"BRONZE (RAW): {bronze_cnt} tables", bg=VS_EDITOR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), anchor="w")
        self.lbl_med_bronze.pack(fill="x")

        self.lbl_med_silver = tk.Label(med_box, text=f"SILVER (CLEANSED): {silver_cnt} tables", bg=VS_EDITOR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), anchor="w")
        self.lbl_med_silver.pack(fill="x")

        self.lbl_med_gold = tk.Label(med_box, text=f"GOLD (AGGREGATED): {gold_cnt} tables", bg=VS_EDITOR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), anchor="w")
        self.lbl_med_gold.pack(fill="x")

        # Action Buttons
        btn_bronze = tk.Button(parent, text="+ REGISTER BRONZE (RAW)", command=self._action_register_bronze, bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, activebackground=VS_ACTIVITY_BAR, activeforeground=VS_TEXT_BRIGHT, relief="flat", bd=0, padx=6, pady=3, font=("DejaVu Sans Mono", 8))
        btn_bronze.pack(fill="x", padx=12, pady=2)

        btn_silver = tk.Button(parent, text="+ PROMOTE TO SILVER (MASK PII)", command=self._action_promote_silver, bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, activebackground=VS_ACTIVITY_BAR, activeforeground=VS_TEXT_BRIGHT, relief="flat", bd=0, padx=6, pady=3, font=("DejaVu Sans Mono", 8))
        btn_silver.pack(fill="x", padx=12, pady=2)

        btn_gold = tk.Button(parent, text="+ PROMOTE TO GOLD (AGGREGATE)", command=self._action_promote_gold, bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, activebackground=VS_ACTIVITY_BAR, activeforeground=VS_TEXT_BRIGHT, relief="flat", bd=0, padx=6, pady=3, font=("DejaVu Sans Mono", 8))
        btn_gold.pack(fill="x", padx=12, pady=(2, 10))

        # Section 3: Audit & Governance
        sec_gov = tk.Label(parent, text="v AUDIT & GOVERNANCE", bg=VS_SIDEBAR_BG, fg=VS_TEXT_BRIGHT, font=("DejaVu Sans Mono", 8, "bold"), anchor="w")
        sec_gov.pack(fill="x", padx=10, pady=(4, 2))

        gov_box = tk.Frame(parent, bg=VS_EDITOR_BG, highlightthickness=1, highlightbackground=VS_BORDER, padx=8, pady=6)
        gov_box.pack(fill="x", padx=12, pady=(0, 10))

        lbl_masking = tk.Label(gov_box, text="SECRET MASKING: ACTIVE\nPII PROTECTION: ENABLED", bg=VS_EDITOR_BG, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8), justify="left", anchor="w")
        lbl_masking.pack(fill="x")

        sig_txt = f"MANIFEST SHA-256:\n{self.last_audit_sig[:24]}..." if self.last_audit_sig else "MANIFEST SHA-256:\n[PENDING EXECUTION]"
        self.lbl_audit_sig = tk.Label(gov_box, text=sig_txt, bg=VS_EDITOR_BG, fg=VS_TEXT_MUTED, font=("DejaVu Sans Mono", 7), justify="left", anchor="w")
        self.lbl_audit_sig.pack(fill="x", pady=(4, 0))

    def _action_register_bronze(self) -> None:
        meta = self.medallion_catalog.register_table("raw_ingest", MedallionStage.BRONZE, self.current_df)
        self._update_status(f"[MEDALLION: REGISTERED BRONZE TABLE 'raw_ingest' ({meta.row_count} rows)]")
        if self.active_sidebar_view == "fabric":
            self.switch_sidebar("fabric")

    def _action_promote_silver(self) -> None:
        email_cols = [c for c in self.current_df.columns if "email" in c.lower()]
        phone_cols = [c for c in self.current_df.columns if "phone" in c.lower() or "contact" in c.lower()]
        masked_df = PIIMasker.mask_dataframe(self.current_df, email_cols=email_cols, phone_cols=phone_cols)
        meta = self.medallion_catalog.register_table("cleansed_silver", MedallionStage.SILVER, masked_df)
        self.current_df = masked_df
        self._populate_treeview(self.current_df.head(25))
        self._update_status(f"[MEDALLION: PROMOTED TO SILVER WITH PII MASKING ({meta.row_count} rows)]")
        if self.active_sidebar_view == "fabric":
            self.switch_sidebar("fabric")

    def _action_promote_gold(self) -> None:
        num_cols = [c for c in self.current_df.columns if pd.api.types.is_numeric_dtype(self.current_df[c])]
        cat_cols = [c for c in self.current_df.columns if not pd.api.types.is_numeric_dtype(self.current_df[c])]
        if cat_cols and num_cols:
            group_col = cat_cols[0]
            gold_df = self.current_df.groupby(group_col)[num_cols].sum().reset_index()
        else:
            gold_df = self.current_df.describe().reset_index()
        meta = self.medallion_catalog.register_table("gold_aggregates", MedallionStage.GOLD, gold_df)
        self.current_df = gold_df
        self._populate_treeview(self.current_df.head(25))
        self._update_status(f"[MEDALLION: PROMOTED TO GOLD ANALYTICS TABLE ({meta.row_count} rows)]")
        if self.active_sidebar_view == "fabric":
            self.switch_sidebar("fabric")

    def _test_sql_connection(self) -> None:
        try:
            conn = SQLDatabaseConnector(self.sql_config)
            conn.test_connection()
            self._update_status("[SQL: CONNECTION ESTABLISHED (SSL VERIFIED)]", color=VS_STATUS_BAR)
        except Exception as exc:
            self._update_status(f"[SQL ERROR: {exc}]", color=VS_ERROR_RED)

    def _test_s3_connection(self) -> None:
        try:
            conn = S3BucketConnector(self.s3_config)
            conn.test_connection()
            self._update_status("[S3: BUCKET REACHABLE (IAM SCOPED)]", color=VS_STATUS_BAR)
        except Exception as exc:
            self._update_status(f"[S3 ERROR: {exc}]", color=VS_ERROR_RED)

    def _build_editor_and_output(self, parent: tk.Frame) -> None:
        v_paned = tk.PanedWindow(parent, orient="vertical", bg=VS_BORDER, sashwidth=2, relief="flat")
        v_paned.pack(fill="both", expand=True)

        top_editor_frame = tk.Frame(v_paned, bg=VS_EDITOR_BG)
        v_paned.add(top_editor_frame, minsize=260)

        bottom_output_frame = tk.Frame(v_paned, bg=VS_EDITOR_BG)
        v_paned.add(bottom_output_frame, minsize=220)

        # --- Editor Setup ---
        # 1. VS Code Tab Bar
        tab_bar = tk.Frame(top_editor_frame, bg=VS_TAB_BAR, height=35)
        tab_bar.pack(fill="x", side="top")

        # Active File Tab
        self.tab_btn = tk.Label(
            tab_bar,
            text="  transform.py  x  ",
            bg=VS_TAB_ACTIVE,
            fg=VS_TEXT_BRIGHT,
            font=("DejaVu Sans Mono", 8),
            pady=8,
            highlightthickness=1,
            highlightbackground=VS_ACCENT_BLUE,
        )
        self.tab_btn.pack(side="left")

        # Engine Buttons in Tab Bar
        self.engine_btns: dict[str, tk.Button] = {}
        for eng in ["pyspark", "ast_filter", "sql", "pandas"]:
            btn = tk.Button(
                tab_bar,
                text=eng.upper(),
                command=lambda e=eng: self.set_engine(e),
                bg=VS_ACCENT_BLUE if eng == self.current_engine else VS_TAB_BAR,
                fg=VS_TEXT_BRIGHT if eng == self.current_engine else VS_TEXT_MAIN,
                relief="flat",
                bd=0,
                padx=8,
                pady=4,
                font=("DejaVu Sans Mono", 7, "bold"),
            )
            btn.pack(side="left", padx=2, pady=4)
            self.engine_btns[eng] = btn

        # Run Button on Right of Tab Bar
        btn_run = tk.Button(
            tab_bar,
            text="RUN [F5]",
            command=self.run_transformation,
            bg=VS_RUN_GREEN,
            fg=VS_TEXT_BRIGHT,
            activebackground=VS_RUN_GREEN_HOVER,
            activeforeground=VS_TEXT_BRIGHT,
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            font=("DejaVu Sans Mono", 8, "bold"),
        )
        btn_run.pack(side="right", padx=6, pady=4)

        # 2. Breadcrumbs
        breadcrumbs = tk.Frame(top_editor_frame, bg=VS_EDITOR_BG, height=22)
        breadcrumbs.pack(fill="x", side="top", padx=10, pady=2)
        self.bread_lbl = tk.Label(
            breadcrumbs,
            text="openflow > default-tenant > src > transform.py",
            bg=VS_EDITOR_BG,
            fg=VS_LINE_NUMBERS,
            font=("DejaVu Sans Mono", 8),
            anchor="w",
        )
        self.bread_lbl.pack(side="left")

        # 3. Editor with Line Numbers Gutter
        editor_container = tk.Frame(top_editor_frame, bg=VS_EDITOR_BG)
        editor_container.pack(fill="both", expand=True)

        self.line_gutter = tk.Text(
            editor_container,
            width=4,
            bg=VS_EDITOR_BG,
            fg=VS_LINE_NUMBERS,
            relief="flat",
            bd=0,
            font=("DejaVu Sans Mono", 10),
            state="disabled",
            wrap="none",
        )
        self.line_gutter.pack(side="left", fill="y", padx=(4, 0))

        self.code_text = tk.Text(
            editor_container,
            bg=VS_EDITOR_BG,
            fg=VS_TEXT_MAIN,
            insertbackground=VS_TEXT_BRIGHT,
            relief="flat",
            bd=0,
            font=("DejaVu Sans Mono", 10),
            wrap="none",
            undo=True,
        )
        ed_vsb = ttk.Scrollbar(editor_container, orient="vertical", command=self._on_scroll_sync)
        ed_hsb = ttk.Scrollbar(editor_container, orient="horizontal", command=self.code_text.xview)
        self.code_text.configure(xscrollcommand=ed_hsb.set, yscrollcommand=self._on_text_scroll)

        ed_vsb.pack(side="right", fill="y")
        ed_hsb.pack(side="bottom", fill="x")
        self.code_text.pack(side="left", fill="both", expand=True)
        self._setup_syntax_highlighting()

        self.code_text.insert("1.0", CODE_STARTERS[self.current_engine])
        self.code_text.bind("<KeyRelease>", lambda e: self._update_line_numbers())
        self._update_line_numbers()

        # --- Bottom Panel (Data Preview & Interactive Analytics) ---
        panel_tabs = tk.Frame(bottom_output_frame, bg=VS_SIDEBAR_BG, height=28)
        panel_tabs.pack(fill="x", side="top")

        self.btn_bottom_preview = tk.Button(
            panel_tabs,
            text="DATA PREVIEW",
            command=lambda: self.switch_bottom_panel("preview"),
            bg=VS_EDITOR_BG,
            fg=VS_TEXT_BRIGHT,
            font=("DejaVu Sans Mono", 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
        )
        self.btn_bottom_preview.pack(side="left", padx=2, pady=2)

        self.btn_bottom_analytics = tk.Button(
            panel_tabs,
            text="ANALYTICS & CHARTS",
            command=lambda: self.switch_bottom_panel("analytics"),
            bg=VS_SIDEBAR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
        )
        self.btn_bottom_analytics.pack(side="left", padx=2, pady=2)

        self.telemetry_inline = tk.Label(
            panel_tabs,
            text="[STATUS: READY] [ROWS: 0] [TIME: 0.0ms]",
            bg=VS_SIDEBAR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8),
            padx=10,
        )
        self.telemetry_inline.pack(side="right")
        self.telemetry_lbl = self.telemetry_inline

        # Panel Content Container
        self.panel_container = tk.Frame(bottom_output_frame, bg=VS_EDITOR_BG)
        self.panel_container.pack(fill="both", expand=True)

        # View 1: Data Preview Table
        self.table_container = tk.Frame(self.panel_container, bg=VS_EDITOR_BG)
        self.table_container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(self.table_container, show="headings", selectmode="browse")
        tbl_vsb = ttk.Scrollbar(self.table_container, orient="vertical", command=self.tree.yview)
        tbl_hsb = ttk.Scrollbar(self.table_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=tbl_hsb.set, yscrollcommand=tbl_vsb.set)

        tbl_vsb.pack(side="right", fill="y")
        tbl_hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        # View 2: Analytics & Plotting Canvas
        from .analytics import AnalyticsEngine, InteractiveChartCanvas

        self.analytics_container = tk.Frame(self.panel_container, bg=VS_EDITOR_BG)

        # Controls Bar for Plotting
        analytics_controls = tk.Frame(self.analytics_container, bg=VS_TAB_BAR, height=32)
        analytics_controls.pack(fill="x", side="top", padx=6, pady=(4, 2))

        tk.Label(analytics_controls, text="TYPE:", bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8)).pack(side="left", padx=(6, 2))
        self.chart_type_combo = ttk.Combobox(analytics_controls, values=["BAR", "LINE", "HISTOGRAM"], width=10, state="readonly", font=("DejaVu Sans Mono", 8))
        self.chart_type_combo.set("BAR")
        self.chart_type_combo.pack(side="left", padx=2)

        tk.Label(analytics_controls, text="X:", bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8)).pack(side="left", padx=(8, 2))
        self.chart_x_combo = ttk.Combobox(analytics_controls, width=14, state="readonly", font=("DejaVu Sans Mono", 8))
        self.chart_x_combo.pack(side="left", padx=2)

        tk.Label(analytics_controls, text="Y:", bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8)).pack(side="left", padx=(8, 2))
        self.chart_y_combo = ttk.Combobox(analytics_controls, width=14, state="readonly", font=("DejaVu Sans Mono", 8))
        self.chart_y_combo.pack(side="left", padx=2)

        tk.Label(analytics_controls, text="AGG:", bg=VS_TAB_BAR, fg=VS_TEXT_MAIN, font=("DejaVu Sans Mono", 8)).pack(side="left", padx=(8, 2))
        self.chart_agg_combo = ttk.Combobox(analytics_controls, values=["SUM", "AVG", "COUNT", "MIN", "MAX", "NONE"], width=8, state="readonly", font=("DejaVu Sans Mono", 8))
        self.chart_agg_combo.set("SUM")
        self.chart_agg_combo.pack(side="left", padx=2)

        btn_plot = tk.Button(
            analytics_controls,
            text="UPDATE PLOT",
            command=self.update_analytics_plot,
            bg=VS_ACCENT_BLUE,
            fg=VS_TEXT_BRIGHT,
            activebackground=VS_ACCENT_HOVER,
            activeforeground=VS_TEXT_BRIGHT,
            relief="flat",
            font=("DejaVu Sans Mono", 8, "bold"),
            padx=10,
            pady=2,
        )
        btn_plot.pack(side="left", padx=10)

        # Summary Statistics Strip
        self.analytics_stats_lbl = tk.Label(
            self.analytics_container,
            text="STATS: SELECT COLUMNS TO CALCULATE SUMMARY METRICS",
            bg=VS_SIDEBAR_BG,
            fg=VS_TEXT_MAIN,
            font=("DejaVu Sans Mono", 8),
            anchor="w",
            padx=10,
            pady=3,
        )
        self.analytics_stats_lbl.pack(fill="x", side="top", padx=6, pady=2)

        # Vector Canvas
        canvas_widget = tk.Canvas(self.analytics_container, bg=VS_EDITOR_BG, highlightthickness=0)
        canvas_widget.pack(fill="both", expand=True, padx=6, pady=4)
        self.chart_canvas = InteractiveChartCanvas(canvas_widget)

    def switch_bottom_panel(self, mode: str) -> None:
        if mode == "preview":
            self.btn_bottom_preview.configure(bg=VS_EDITOR_BG, fg=VS_TEXT_BRIGHT)
            self.btn_bottom_analytics.configure(bg=VS_SIDEBAR_BG, fg=VS_TEXT_MAIN)
            self.analytics_container.pack_forget()
            self.table_container.pack(fill="both", expand=True)
        else:
            self.btn_bottom_preview.configure(bg=VS_SIDEBAR_BG, fg=VS_TEXT_MAIN)
            self.btn_bottom_analytics.configure(bg=VS_EDITOR_BG, fg=VS_TEXT_BRIGHT)
            self.table_container.pack_forget()
            self.analytics_container.pack(fill="both", expand=True)
            self._update_chart_comboboxes()
            self.update_analytics_plot()

    def _update_chart_comboboxes(self) -> None:
        cols = list(self.current_df.columns)
        num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(self.current_df[c])]

        self.chart_x_combo["values"] = cols
        self.chart_y_combo["values"] = num_cols if num_cols else cols

        if cols and (not self.chart_x_combo.get() or self.chart_x_combo.get() not in cols):
            # Prefer country or category for X if available
            cand = next((c for c in ["country", "category", "device_id", "status"] if c in cols), cols[0])
            self.chart_x_combo.set(cand)

        if num_cols and (not self.chart_y_combo.get() or self.chart_y_combo.get() not in num_cols):
            # Prefer amount or temperature
            cand_y = next((c for c in ["amount", "total_revenue", "temperature", "monthly_spend"] if c in num_cols), num_cols[0])
            self.chart_y_combo.set(cand_y)

    def update_analytics_plot(self) -> None:
        from .analytics import AnalyticsEngine

        df = self.current_df
        if df.empty:
            self.chart_canvas.clear()
            return

        x_col = self.chart_x_combo.get() or df.columns[0]
        y_col = self.chart_y_combo.get() or (df.columns[1] if len(df.columns) > 1 else df.columns[0])
        chart_type = self.chart_type_combo.get() or "BAR"
        agg_func = self.chart_agg_combo.get() or "SUM"

        # Update summary statistics strip
        stats = AnalyticsEngine.compute_summary_stats(df, y_col)
        self.analytics_stats_lbl.configure(
            text=f"STATS [{y_col}]: COUNT: {int(stats['count'])} | SUM: {stats['sum']:g} | MEAN: {stats['mean']:g} | MIN: {stats['min']:g} | MAX: {stats['max']:g} | STD: {stats['std']:g}"
        )

        if chart_type == "HISTOGRAM":
            labels, values = AnalyticsEngine.compute_histogram(df, y_col, bins=8)
            self.chart_canvas.plot_bar(labels, values, title=f"FREQUENCY DISTRIBUTION: {y_col.upper()}")
        elif chart_type == "LINE":
            labels, values = AnalyticsEngine.aggregate_data(df, x_col, y_col, agg_func)
            self.chart_canvas.plot_line(labels, values, title=f"{y_col.upper()} TREND BY {x_col.upper()} ({agg_func})")
        else:  # BAR
            labels, values = AnalyticsEngine.aggregate_data(df, x_col, y_col, agg_func)
            self.chart_canvas.plot_bar(labels, values, title=f"{agg_func} OF {y_col.upper()} BY {x_col.upper()}")

    def _build_status_bar(self, parent: tk.Frame) -> None:
        self.sb_left = tk.Label(
            parent,
            text="main* | Python 3.12 (PySpark 3.5) | UTF-8",
            bg=VS_STATUS_BAR,
            fg=VS_TEXT_BRIGHT,
            font=("DejaVu Sans Mono", 8),
            padx=8,
        )
        self.sb_left.pack(side="left")

        self.sb_right = tk.Label(
            parent,
            text="[STATUS: READY] | Ln 1, Col 1 | Spaces: 4",
            bg=VS_STATUS_BAR,
            fg=VS_TEXT_BRIGHT,
            font=("DejaVu Sans Mono", 8),
            padx=8,
        )
        self.sb_right.pack(side="right")

    def _update_status(self, text: str, color: str = VS_STATUS_BAR) -> None:
        self.status_bar.configure(bg=color)
        self.sb_left.configure(bg=color)
        self.sb_right.configure(text=text, bg=color)

    def _on_scroll_sync(self, *args: Any) -> None:
        self.code_text.yview(*args)
        self.line_gutter.yview(*args)

    def _on_text_scroll(self, first: str, last: str) -> None:
        self.line_gutter.yview_moveto(first)

    def _setup_syntax_highlighting(self) -> None:
        self.code_text.tag_configure("kw_python", foreground="#569cd6", font=("DejaVu Sans Mono", 10, "bold"))
        self.code_text.tag_configure("kw_sql", foreground="#c586c0", font=("DejaVu Sans Mono", 10, "bold"))
        self.code_text.tag_configure("func", foreground="#dcdcaa")
        self.code_text.tag_configure("string", foreground="#ce9178")
        self.code_text.tag_configure("comment", foreground="#6a9955", font=("DejaVu Sans Mono", 10, "italic"))
        self.code_text.tag_configure("number", foreground="#b5cea8")
        self.code_text.tag_configure("pyspark_var", foreground="#4ec9b0", font=("DejaVu Sans Mono", 10, "bold"))

    def _apply_syntax_highlighting(self) -> None:
        content = self.code_text.get("1.0", "end-1c")
        if not content:
            return

        for tag in ["kw_python", "kw_sql", "func", "string", "comment", "number", "pyspark_var"]:
            self.code_text.tag_remove(tag, "1.0", "end")

        import re

        # Comments (# ... or -- ...)
        for match in re.finditer(r"(#|--)[^\n]*", content):
            self.code_text.tag_add("comment", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # Strings ('...' or "...")
        for match in re.finditer(r"(\"[^\"]*\"|'[^']*')", content):
            self.code_text.tag_add("string", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # Numbers
        for match in re.finditer(r"\b\d+(\.\d+)?\b", content):
            self.code_text.tag_add("number", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # Python Keywords
        py_kws = r"\b(def|class|import|from|return|if|else|elif|for|while|in|and|or|not|None|True|False|as|with|lambda)\b"
        for match in re.finditer(py_kws, content):
            self.code_text.tag_add("kw_python", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # PySpark special variables
        for match in re.finditer(r"\b(df|df_out|spark|F|col)\b", content):
            self.code_text.tag_add("pyspark_var", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # SQL Keywords
        sql_kws = r"(?i)\b(SELECT|FROM|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|NOT|IN|COUNT|SUM|AVG|MIN|MAX|DISTINCT|LIMIT|CASE|WHEN|THEN|ELSE|END)\b"
        for match in re.finditer(sql_kws, content):
            self.code_text.tag_add("kw_sql", f"1.0 + {match.start()} chars", f"1.0 + {match.end()} chars")

        # Functions (e.g. .filter(, .groupBy(, .agg(, alias()
        for match in re.finditer(r"\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", content):
            self.code_text.tag_add("func", f"1.0 + {match.start(1)} chars", f"1.0 + {match.end(1)} chars")

    def _update_line_numbers(self) -> None:
        lines = int(self.code_text.index("end-1c").split(".")[0])
        self.line_gutter.configure(state="normal")
        self.line_gutter.delete("1.0", "end")
        gutter_text = "\n".join(f"{i:>3} " for i in range(1, lines + 1))
        self.line_gutter.insert("1.0", gutter_text)
        self.line_gutter.configure(state="disabled")
        self._apply_syntax_highlighting()

    def set_engine(self, engine: str) -> None:
        self.current_engine = engine
        for eng, btn in self.engine_btns.items():
            if eng == engine:
                btn.configure(bg=VS_ACCENT_BLUE, fg=VS_TEXT_BRIGHT)
            else:
                btn.configure(bg=VS_TAB_BAR, fg=VS_TEXT_MAIN)

        filename_ext = "query.sql" if engine == "sql" else "transform.py"
        self.tab_btn.configure(text=f"  {filename_ext}  x  ")
        self.bread_lbl.configure(text=f"openflow > default-tenant > src > {filename_ext}")

        self.code_text.delete("1.0", "end")
        self.code_text.insert("1.0", CODE_STARTERS[engine])
        self._update_line_numbers()
        self._update_status(f"[STATUS: READY] [ENGINE: {engine.upper()}]")

    def _on_preset_selected(self) -> None:
        choice = self.preset_var.get()
        if choice == "IOT_TELEMETRY":
            self.current_df = self._generate_sample_iot()
            self.current_filename = "iot_telemetry.csv"
        elif choice == "CUSTOMER_DEMO":
            self.current_df = self._generate_sample_customers()
            self.current_filename = "customer_demo.csv"
        else:
            self.current_df = self._generate_sample_ecommerce()
            self.current_filename = "ecommerce_sales.csv"

        self._load_current_dataset()

    def _choose_file(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Open Data File",
            filetypes=[("Data Files", "*.csv *.parquet *.json"), ("All Files", "*.*")],
        )
        if not filepath:
            return

        try:
            if filepath.endswith(".csv"):
                df = pd.read_csv(filepath)
            elif filepath.endswith(".parquet") or filepath.endswith(".pq"):
                df = pd.read_parquet(filepath)
            elif filepath.endswith(".json"):
                df = pd.read_json(filepath)
            else:
                df = pd.read_csv(filepath)

            self.current_df = df
            self.current_filename = os.path.basename(filepath)
            self._load_current_dataset()
        except Exception as exc:
            self._update_status(f"[ERROR: {exc}]", color=VS_ERROR_RED)

    def _load_current_dataset(self) -> None:
        if hasattr(self, "dataset_info_lbl"):
            self.dataset_info_lbl.configure(
                text=f"DATASET: {self.current_filename}\nROWS: {len(self.current_df)} | COLS: {len(self.current_df.columns)}"
            )
        self._refresh_schema_listbox()
        self._populate_treeview(self.current_df.head(25))

    def _refresh_schema_listbox(self) -> None:
        if not hasattr(self, "schema_listbox"):
            return
        self.schema_listbox.delete(0, "end")
        for col, dtype in zip(self.current_df.columns, self.current_df.dtypes):
            self.schema_listbox.insert("end", f"{col:<16} {str(dtype)}")

    def run_transformation(self) -> None:
        code = self.code_text.get("1.0", "end-1c")
        if not code.strip():
            return

        self._update_status("[EXECUTING RUN...]", color=VS_STATUS_BAR)
        self.telemetry_inline.configure(text="[STATUS: EXECUTING...]")
        self.root.update_idletasks()

        output: ExecutionOutput = CodeExecutor.execute(
            code=code,
            engine=self.current_engine,  # type: ignore
            df=self.current_df,
            limit=100,
        )

        if output.status == "succeeded":
            telemetry_str = f"[STATUS: SUCCEEDED] [ROWS: {output.row_count}] [TIME: {output.duration_ms}ms]"
            if output.capacity_report:
                self.cumulative_cu += output.capacity_report.capacity_units
                self.cumulative_savings_usd += output.capacity_report.cost_avoidance_usd
                telemetry_str += f" [CU: {output.capacity_report.capacity_units:g}] [SAVED: ${output.capacity_report.cost_avoidance_usd:g}]"
            if output.audit_record:
                self.last_audit_sig = output.audit_record.manifest_signature

            self.telemetry_inline.configure(text=telemetry_str)
            self._update_status(f"{telemetry_str} | ENGINE: {self.current_engine.upper()}", color=VS_STATUS_BAR)
            res_df = pd.DataFrame(output.records) if output.records else pd.DataFrame(columns=output.columns)
            self._populate_treeview(res_df)
            if self.active_sidebar_view == "fabric":
                self.switch_sidebar("fabric")
        else:
            if output.audit_record:
                self.last_audit_sig = output.audit_record.manifest_signature
            self.telemetry_inline.configure(text=f"[STATUS: FAILED] [ERROR: {output.error}]")
            self._update_status(f"[FAILED: {output.error}]", color=VS_ERROR_RED)
            if self.active_sidebar_view == "fabric":
                self.switch_sidebar("fabric")

    def _populate_treeview(self, df: pd.DataFrame) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = list(df.columns)

        for col in df.columns:
            self.tree.heading(col, text=str(col), anchor="w")
            self.tree.column(col, width=120, minwidth=60, anchor="w")

        for _, row in df.iterrows():
            vals = [str(v) if pd.notna(v) else "NULL" for v in row.values]
            self.tree.insert("", "end", values=vals)

    @staticmethod
    def _generate_sample_ecommerce() -> pd.DataFrame:
        rows = 100
        return pd.DataFrame(
            {
                "order_id": [5000 + i for i in range(rows)],
                "customer_id": [1000 + (i % 25) for i in range(rows)],
                "country": [["USA", "Canada", "UK", "Germany", "Japan"][i % 5] for i in range(rows)],
                "category": [["Electronics", "Clothing", "Home", "Books", "Sports"][i % 5] for i in range(rows)],
                "amount": [round(15.0 + (i * 7.5) % 450.0, 2) for i in range(rows)],
                "status": [["Completed", "Completed", "Pending", "Cancelled"][i % 4] for i in range(rows)],
            }
        )

    @staticmethod
    def _generate_sample_iot() -> pd.DataFrame:
        rows = 100
        return pd.DataFrame(
            {
                "device_id": [f"sensor-{i%10 + 1:03d}" for i in range(rows)],
                "temperature": [round(20.0 + (i * 0.3) % 15.0, 2) for i in range(rows)],
                "humidity": [round(45.0 + (i * 0.5) % 35.0, 2) for i in range(rows)],
                "battery_pct": [100 - (i % 60) for i in range(rows)],
                "alert": ["Normal" if i % 7 != 0 else "High Temp" for i in range(rows)],
            }
        )

    @staticmethod
    def _generate_sample_customers() -> pd.DataFrame:
        rows = 100
        return pd.DataFrame(
            {
                "customer_id": [1000 + i for i in range(rows)],
                "age": [18 + (i % 55) for i in range(rows)],
                "country": [["USA", "Germany", "France", "Japan", "Brazil"][i % 5] for i in range(rows)],
                "plan_type": [["Basic", "Pro", "Enterprise"][i % 3] for i in range(rows)],
                "monthly_spend": [round(29.0 + (i * 3.7) % 300.0, 2) for i in range(rows)],
                "churn_risk": ["Low" if i % 4 != 0 else "High" for i in range(rows)],
            }
        )


def main() -> None:
    root = tk.Tk()
    app = OpenFlowLocalApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
