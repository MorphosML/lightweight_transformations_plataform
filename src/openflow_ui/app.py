from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any

import pandas as pd

from openflow_api.code_executor import CodeExecutor, ExecutionOutput

# Minimalist Dark Palette (Sharp, Technical, High-Contrast)
BG_ROOT = "#0c0e12"
BG_PANEL = "#14171f"
BG_EDITOR = "#181b24"
BG_HEADER = "#101218"
BORDER_COLOR = "#232733"
TEXT_MAIN = "#d8dee9"
TEXT_MUTED = "#6c7689"
TEXT_ACCENT = "#58a6ff"
BTN_BG = "#1f2430"
BTN_HOVER = "#2a3142"
STATUS_OK = "#3fb950"
STATUS_ERR = "#f85149"

CODE_STARTERS = {
    "pyspark": """# PySpark Transformation
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
    "ast_filter": """# Safe AST Expression (Zero RCE Risk)
amount >= 100.0 and category in ['Electronics', 'Home'] and status == 'Completed'
""",
    "sql": """-- SQL Query on table 'data'
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
    "pandas": """# Pandas Transformation
# 'df' is pandas DataFrame

df_out = df[df["amount"] > 50.0].copy()
df_out["tax"] = df_out["amount"] * 0.15
df_out["total"] = df_out["amount"] + df_out["tax"]
""",
}


class OpenFlowLocalApp:
    """Minimalist local desktop GUI for OpenFlow ELT platform."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OPENFLOW // LOCAL ELT STUDIO")
        self.root.geometry("1100x750")
        self.root.minsize(800, 550)
        self.root.configure(bg=BG_ROOT)

        # State
        self.current_engine = "pyspark"
        self.current_df: pd.DataFrame = self._generate_sample_ecommerce()
        self.current_filename = "ecommerce_sales.csv"

        self._setup_styles()
        self._build_layout()
        self._load_current_dataset()

        # Keyboard shortcut F5 to run
        self.root.bind("<F5>", lambda event: self.run_transformation())
        self.root.bind("<Control-Return>", lambda event: self.run_transformation())

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        # Configure Treeview styling (sharp, flat, dark)
        style.configure(
            "Treeview",
            background=BG_PANEL,
            foreground=TEXT_MAIN,
            fieldbackground=BG_PANEL,
            borderwidth=0,
            font=("DejaVu Sans Mono", 9),
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=BG_HEADER,
            foreground=TEXT_MAIN,
            relief="flat",
            font=("DejaVu Sans Mono", 9, "bold"),
            borderwidth=1,
        )
        style.map("Treeview.Heading", background=[("active", BTN_BG)])

        # Scrollbars
        style.configure(
            "Vertical.TScrollbar",
            background=BG_PANEL,
            troughcolor=BG_ROOT,
            borderwidth=0,
            arrowsize=11,
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=BG_PANEL,
            troughcolor=BG_ROOT,
            borderwidth=0,
            arrowsize=11,
        )

    def _build_layout(self) -> None:
        # Top Header Bar
        header = tk.Frame(self.root, bg=BG_HEADER, height=36, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        header.pack(fill="x", side="top")

        title_lbl = tk.Label(
            header,
            text="OPENFLOW // LOCAL ELT STUDIO",
            bg=BG_HEADER,
            fg=TEXT_MAIN,
            font=("DejaVu Sans Mono", 10, "bold"),
            padx=12,
            pady=8,
        )
        title_lbl.pack(side="left")

        tenant_lbl = tk.Label(
            header,
            text="TENANT: LOCAL-DEV | PROJECT: DEFAULT | ENV: NATIVE",
            bg=BG_HEADER,
            fg=TEXT_MUTED,
            font=("DejaVu Sans Mono", 8),
            padx=12,
        )
        tenant_lbl.pack(side="right")

        # Main Paned Workspace (Left: Ingestion Panel, Right: Coding & Output)
        paned = tk.PanedWindow(self.root, orient="horizontal", bg=BORDER_COLOR, sashwidth=2, relief="flat")
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        # Left Ingestion Panel
        left_frame = tk.Frame(paned, bg=BG_PANEL, width=280, relief="flat")
        paned.add(left_frame, minsize=220)

        # Right Workspace Frame
        right_frame = tk.Frame(paned, bg=BG_ROOT, relief="flat")
        paned.add(right_frame, minsize=500)

        self._build_ingestion_panel(left_frame)
        self._build_coding_and_output_panel(right_frame)

    def _build_ingestion_panel(self, parent: tk.Frame) -> None:
        pad_opts = {"padx": 10, "pady": 6}

        # Title
        lbl = tk.Label(
            parent,
            text="DATA INGESTION",
            bg=BG_PANEL,
            fg=TEXT_ACCENT,
            font=("DejaVu Sans Mono", 9, "bold"),
            anchor="w",
        )
        lbl.pack(fill="x", **pad_opts)

        # Preset Selector
        preset_lbl = tk.Label(parent, text="SOURCE PRESET:", bg=BG_PANEL, fg=TEXT_MUTED, font=("DejaVu Sans Mono", 8), anchor="w")
        preset_lbl.pack(fill="x", padx=10, pady=(4, 2))

        self.preset_var = tk.StringVar(value="ECOMMERCE_SALES")
        presets = ["ECOMMERCE_SALES", "IOT_TELEMETRY", "CUSTOMER_DEMO"]
        for p in presets:
            rb = tk.Radiobutton(
                parent,
                text=p,
                value=p,
                variable=self.preset_var,
                command=self._on_preset_selected,
                bg=BG_PANEL,
                fg=TEXT_MAIN,
                selectcolor=BG_EDITOR,
                activebackground=BG_PANEL,
                activeforeground=TEXT_MAIN,
                font=("DejaVu Sans Mono", 8),
                anchor="w",
            )
            rb.pack(fill="x", padx=14, pady=1)

        # File Chooser Button
        btn_file = tk.Button(
            parent,
            text="OPEN LOCAL FILE...",
            command=self._choose_file,
            bg=BTN_BG,
            fg=TEXT_MAIN,
            activebackground=BTN_HOVER,
            activeforeground=TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            font=("DejaVu Sans Mono", 8),
        )
        btn_file.pack(fill="x", padx=10, pady=(8, 4))

        # Active Dataset Info
        self.dataset_info_lbl = tk.Label(
            parent,
            text="DATASET: ecommerce_sales.csv\nROWS: 100",
            bg=BG_EDITOR,
            fg=TEXT_MAIN,
            font=("DejaVu Sans Mono", 8),
            justify="left",
            anchor="w",
            padx=8,
            pady=6,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        self.dataset_info_lbl.pack(fill="x", padx=10, pady=(6, 8))

        # Schema Listbox Header
        schema_lbl = tk.Label(parent, text="INFERRED SCHEMA:", bg=BG_PANEL, fg=TEXT_MUTED, font=("DejaVu Sans Mono", 8), anchor="w")
        schema_lbl.pack(fill="x", padx=10, pady=(4, 2))

        # Schema Listbox
        schema_frame = tk.Frame(parent, bg=BG_EDITOR, highlightthickness=1, highlightbackground=BORDER_COLOR)
        schema_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.schema_listbox = tk.Listbox(
            schema_frame,
            bg=BG_EDITOR,
            fg=TEXT_MAIN,
            selectbackground=BTN_BG,
            selectforeground=TEXT_ACCENT,
            borderwidth=0,
            relief="flat",
            font=("DejaVu Sans Mono", 8),
        )
        self.schema_listbox.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_coding_and_output_panel(self, parent: tk.Frame) -> None:
        # Split vertical: Top = Code Editor, Bottom = Preview Table
        v_paned = tk.PanedWindow(parent, orient="vertical", bg=BORDER_COLOR, sashwidth=2, relief="flat")
        v_paned.pack(fill="both", expand=True)

        editor_frame = tk.Frame(v_paned, bg=BG_PANEL, relief="flat")
        v_paned.add(editor_frame, minsize=220)

        output_frame = tk.Frame(v_paned, bg=BG_PANEL, relief="flat")
        v_paned.add(output_frame, minsize=200)

        # --- Editor Frame Setup ---
        ed_toolbar = tk.Frame(editor_frame, bg=BG_HEADER, height=32, highlightthickness=1, highlightbackground=BORDER_COLOR)
        ed_toolbar.pack(fill="x", side="top")

        ed_title = tk.Label(ed_toolbar, text="TRANSFORMATION CODE", bg=BG_HEADER, fg=TEXT_ACCENT, font=("DejaVu Sans Mono", 9, "bold"), padx=8)
        ed_title.pack(side="left")

        # Engine Buttons
        self.engine_btns: dict[str, tk.Button] = {}
        for eng in ["pyspark", "ast_filter", "sql", "pandas"]:
            btn = tk.Button(
                ed_toolbar,
                text=eng.upper(),
                command=lambda e=eng: self.set_engine(e),
                bg=BTN_HOVER if eng == self.current_engine else BTN_BG,
                fg=TEXT_ACCENT if eng == self.current_engine else TEXT_MUTED,
                relief="flat",
                bd=0,
                padx=8,
                pady=3,
                font=("DejaVu Sans Mono", 8, "bold"),
            )
            btn.pack(side="left", padx=2, pady=4)
            self.engine_btns[eng] = btn

        # Run Button
        self.btn_run = tk.Button(
            ed_toolbar,
            text="RUN [F5]",
            command=self.run_transformation,
            bg="#238636",
            fg="#ffffff",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=12,
            pady=3,
            font=("DejaVu Sans Mono", 8, "bold"),
        )
        self.btn_run.pack(side="right", padx=6, pady=4)

        # Code Text Area
        code_container = tk.Frame(editor_frame, bg=BG_EDITOR, highlightthickness=1, highlightbackground=BORDER_COLOR)
        code_container.pack(fill="both", expand=True, padx=6, pady=6)

        self.code_text = tk.Text(
            code_container,
            bg=BG_EDITOR,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
            bd=0,
            font=("DejaVu Sans Mono", 10),
            wrap="none",
            undo=True,
        )
        code_vsb = ttk.Scrollbar(code_container, orient="vertical", command=self.code_text.yview)
        code_hsb = ttk.Scrollbar(code_container, orient="horizontal", command=self.code_text.xview)
        self.code_text.configure(xscrollcommand=code_hsb.set, yscrollcommand=code_vsb.set)

        code_vsb.pack(side="right", fill="y")
        code_hsb.pack(side="bottom", fill="x")
        self.code_text.pack(side="left", fill="both", expand=True)

        self.code_text.insert("1.0", CODE_STARTERS[self.current_engine])

        # --- Output Frame Setup ---
        out_toolbar = tk.Frame(output_frame, bg=BG_HEADER, height=30, highlightthickness=1, highlightbackground=BORDER_COLOR)
        out_toolbar.pack(fill="x", side="top")

        out_title = tk.Label(out_toolbar, text="OUTPUT PREVIEW", bg=BG_HEADER, fg=TEXT_MAIN, font=("DejaVu Sans Mono", 9, "bold"), padx=8)
        out_title.pack(side="left")

        self.telemetry_lbl = tk.Label(
            out_toolbar,
            text="[STATUS: READY] [ROWS: 0] [TIME: 0.0ms] [ENGINE: PYSPARK]",
            bg=BG_HEADER,
            fg=TEXT_MUTED,
            font=("DejaVu Sans Mono", 8),
            padx=8,
        )
        self.telemetry_lbl.pack(side="right")

        # Treeview Preview Table
        tbl_container = tk.Frame(output_frame, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER_COLOR)
        tbl_container.pack(fill="both", expand=True, padx=6, pady=6)

        self.tree = ttk.Treeview(tbl_container, show="headings", selectmode="browse")
        tbl_vsb = ttk.Scrollbar(tbl_container, orient="vertical", command=self.tree.yview)
        tbl_hsb = ttk.Scrollbar(tbl_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=tbl_hsb.set, yscrollcommand=tbl_vsb.set)

        tbl_vsb.pack(side="right", fill="y")
        tbl_hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

    def set_engine(self, engine: str) -> None:
        self.current_engine = engine
        for eng, btn in self.engine_btns.items():
            if eng == engine:
                btn.configure(bg=BTN_HOVER, fg=TEXT_ACCENT)
            else:
                btn.configure(bg=BTN_BG, fg=TEXT_MUTED)

        # Replace starter template if user hasn't heavily modified
        self.code_text.delete("1.0", "end")
        self.code_text.insert("1.0", CODE_STARTERS[engine])
        self.telemetry_lbl.configure(text=f"[STATUS: READY] [ENGINE: {engine.upper()}]")

    def _on_preset_selected(self) -> None:
        choice = self.preset_var.get()
        if choice == "IOT_TELEMETRY":
            self.current_df = self._generate_sample_iot()
            self.current_filename = "iot_telemetry.csv"
        elif choice == "CUSTOMER_DEMO":
            self.current_df = self._generate_sample_customers()
            self.current_filename = "customer_demographics.csv"
        else:
            self.current_df = self._generate_sample_ecommerce()
            self.current_filename = "ecommerce_sales.csv"

        self._load_current_dataset()

    def _choose_file(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Open Data File",
            filetypes=[("CSV and Parquet", "*.csv *.parquet *.json"), ("All Files", "*.*")],
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
            self.telemetry_lbl.configure(text=f"[ERROR LOADING FILE: {exc}]", fg=STATUS_ERR)

    def _load_current_dataset(self) -> None:
        self.dataset_info_lbl.configure(
            text=f"DATASET: {self.current_filename}\nROWS: {len(self.current_df)} | COLS: {len(self.current_df.columns)}"
        )

        self.schema_listbox.delete(0, "end")
        for col, dtype in zip(self.current_df.columns, self.current_df.dtypes):
            self.schema_listbox.insert("end", f"{col:<16} {str(dtype)}")

        # Populate output tree with raw data initially
        self._populate_treeview(self.current_df.head(25))

    def run_transformation(self) -> None:
        code = self.code_text.get("1.0", "end-1c")
        if not code.strip():
            return

        self.telemetry_lbl.configure(text="[STATUS: EXECUTING...]", fg=TEXT_ACCENT)
        self.root.update_idletasks()

        # Run via CodeExecutor
        output: ExecutionOutput = CodeExecutor.execute(
            code=code,
            engine=self.current_engine,  # type: ignore
            df=self.current_df,
            limit=100,
        )

        if output.status == "succeeded":
            self.telemetry_lbl.configure(
                text=f"[STATUS: SUCCEEDED] [ROWS: {output.row_count}] [TIME: {output.duration_ms}ms] [ENGINE: {self.current_engine.upper()}]",
                fg=STATUS_OK,
            )
            # Rebuild tree with output records
            res_df = pd.DataFrame(output.records) if output.records else pd.DataFrame(columns=output.columns)
            self._populate_treeview(res_df)
        else:
            self.telemetry_lbl.configure(
                text=f"[STATUS: FAILED] [ERROR: {output.error}]",
                fg=STATUS_ERR,
            )

    def _populate_treeview(self, df: pd.DataFrame) -> None:
        # Clear existing columns and items
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
