from __future__ import annotations

import io
import os
from typing import Any, Literal
import pandas as pd

# Set safe writable directory for matplotlib cache
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib_openflow")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.io as pio

VS_CANVAS_BG = "#1e1e1e"
VS_GRID_COLOR = "#2d2d2d"
VS_AXIS_COLOR = "#444444"
VS_BAR_COLOR = "#007acc"
VS_BAR_HOVER = "#0098ff"
VS_LINE_COLOR = "#3fb950"
VS_POINT_COLOR = "#58a6ff"
VS_TEXT_COLOR = "#cccccc"
VS_TITLE_COLOR = "#ffffff"


class AnalyticsEngine:
    """Enterprise visual analytics engine integrating Plotly, Seaborn, and Matplotlib."""

    @classmethod
    def compute_summary_stats(cls, df: pd.DataFrame, column: str) -> dict[str, float]:
        """Calculates count, sum, mean, min, max, and std for a numeric column."""
        if column not in df.columns or not pd.api.types.is_numeric_dtype(df[column]):
            return {"count": len(df), "sum": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}

        series = df[column].dropna()
        if series.empty:
            return {"count": 0, "sum": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}

        return {
            "count": float(len(series)),
            "sum": round(float(series.sum()), 2),
            "mean": round(float(series.mean()), 2),
            "min": round(float(series.min()), 2),
            "max": round(float(series.max()), 2),
            "std": round(float(series.std() if len(series) > 1 else 0.0), 2),
        }

    @classmethod
    def aggregate_data(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        agg_func: Literal["NONE", "SUM", "AVG", "COUNT", "MIN", "MAX"] = "SUM",
        max_categories: int = 15,
    ) -> tuple[list[str], list[float]]:
        """Groups data by x_col and applies agg_func to y_col."""
        if df.empty or x_col not in df.columns or y_col not in df.columns:
            return [], []

        clean_df = df[[x_col, y_col]].dropna().copy()
        if clean_df.empty:
            return [], []

        if agg_func == "NONE":
            subset = clean_df.head(max_categories)
            labels = [str(x) for x in subset[x_col]]
            values = [float(y) if pd.api.types.is_numeric_dtype(clean_df[y_col]) else 1.0 for y in subset[y_col]]
            return labels, values

        agg_map = {
            "SUM": "sum",
            "AVG": "mean",
            "COUNT": "count",
            "MIN": "min",
            "MAX": "max",
        }
        func = agg_map.get(agg_func, "sum")

        if not pd.api.types.is_numeric_dtype(clean_df[y_col]) and func != "count":
            grouped = clean_df.groupby(x_col)[y_col].count().reset_index()
        else:
            grouped = clean_df.groupby(x_col)[y_col].agg(func).reset_index()

        grouped = grouped.sort_values(by=y_col, ascending=False).head(max_categories)
        labels = [str(x) for x in grouped[x_col]]
        values = [round(float(y), 2) for y in grouped[y_col]]

        return labels, values

    @classmethod
    def compute_histogram(
        cls,
        df: pd.DataFrame,
        col: str,
        bins: int = 8,
    ) -> tuple[list[str], list[float]]:
        """Computes histogram bins and frequency counts for a continuous numeric column."""
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            return [], []

        series = df[col].dropna()
        if series.empty:
            return [], []

        min_val, max_val = float(series.min()), float(series.max())
        if min_val == max_val:
            return [f"{min_val}"], [float(len(series))]

        bin_width = (max_val - min_val) / bins
        bin_counts = [0] * bins
        bin_labels = []

        for b in range(bins):
            b_start = min_val + b * bin_width
            b_end = b_start + bin_width
            bin_labels.append(f"{b_start:.1f}-{b_end:.1f}")

        for val in series:
            b_idx = min(int((val - min_val) / bin_width), bins - 1)
            bin_counts[b_idx] += 1

        return bin_labels, [float(c) for c in bin_counts]

    @classmethod
    def generate_plotly_figure(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        chart_type: str = "LINE",
        agg_func: str = "SUM",
    ) -> str:
        """Generates an interactive Plotly dark-themed plot rendered to an HTML snippet."""
        if df.empty or x_col not in df.columns:
            return "<div style='color:#858585;padding:20px;'>No data available for Plotly rendering.</div>"

        ctype = chart_type.upper()
        title = f"{ctype} — {agg_func} of {y_col} by {x_col}" if y_col else f"{ctype} of {x_col}"

        if ctype == "HISTOGRAM":
            fig = px.histogram(
                df, x=y_col or x_col, nbins=20,
                title=title, template="plotly_dark",
                color_discrete_sequence=["#007acc"]
            )
        elif ctype == "BAR":
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            agg_df = pd.DataFrame({x_col: labels, y_col: values})
            fig = px.bar(
                agg_df, x=x_col, y=y_col,
                title=title, template="plotly_dark",
                color_discrete_sequence=["#007acc"]
            )
        elif ctype == "SCATTER":
            fig = px.scatter(
                df, x=x_col, y=y_col,
                title=title, template="plotly_dark",
                color_discrete_sequence=["#3fb950"]
            )
        elif ctype == "BOX":
            fig = px.box(
                df, x=x_col, y=y_col,
                title=title, template="plotly_dark",
                color_discrete_sequence=["#d29922"]
            )
        else:  # LINE
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            agg_df = pd.DataFrame({x_col: labels, y_col: values})
            fig = px.line(
                agg_df, x=x_col, y=y_col,
                title=title, template="plotly_dark",
                markers=True, color_discrete_sequence=["#3fb950"]
            )

        fig.update_layout(
            paper_bgcolor="#1e1e1e",
            plot_bgcolor="#1e1e1e",
            font=dict(color="#cccccc", family="monospace"),
            margin=dict(l=40, r=40, t=50, b=40),
        )
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    @classmethod
    def generate_seaborn_figure(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        chart_type: str = "BAR",
        agg_func: str = "SUM",
    ) -> str:
        """Generates a publication-grade statistical Seaborn plot rendered as crisp vector SVG."""
        if df.empty or x_col not in df.columns:
            return "<svg><text fill='#858585'>No data</text></svg>"

        plt.close("all")
        sns.set_theme(
            style="darkgrid",
            rc={
                "axes.facecolor": "#1e1e1e",
                "figure.facecolor": "#1e1e1e",
                "text.color": "#cccccc",
                "axes.labelcolor": "#cccccc",
                "xtick.color": "#858585",
                "ytick.color": "#858585",
                "grid.color": "#2d2d2d",
            },
        )

        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        ctype = chart_type.upper()

        if ctype == "HISTOGRAM":
            col_to_plot = y_col if (y_col in df.columns and pd.api.types.is_numeric_dtype(df[y_col])) else x_col
            sns.histplot(data=df, x=col_to_plot, kde=True, ax=ax, color="#007acc")
            ax.set_title(f"SEABORN HISTOGRAM & KDE — {col_to_plot}", color="#ffffff", fontsize=11, fontweight="bold")
        elif ctype == "BOX":
            sns.boxplot(data=df, x=x_col, y=y_col, ax=ax, palette="mako")
            ax.set_title(f"SEABORN BOXPLOT — {y_col} BY {x_col}", color="#ffffff", fontsize=11, fontweight="bold")
            plt.xticks(rotation=30, ha="right")
        elif ctype == "SCATTER":
            sns.scatterplot(data=df, x=x_col, y=y_col, ax=ax, color="#3fb950", s=60)
            ax.set_title(f"SEABORN SCATTER — {y_col} VS {x_col}", color="#ffffff", fontsize=11, fontweight="bold")
        elif ctype == "LINE":
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            ax.plot(labels, values, marker="o", color="#3fb950", linewidth=2.5, markersize=5)
            ax.fill_between(range(len(labels)), values, color="#122a18", alpha=0.6)
            ax.set_title(f"SEABORN LINE TREND — {agg_func} OF {y_col}", color="#ffffff", fontsize=11, fontweight="bold")
            plt.xticks(rotation=30, ha="right")
        else:  # BAR
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            sns.barplot(x=labels, y=values, ax=ax, hue=labels, palette="crest", legend=False)
            ax.set_title(f"SEABORN BAR — {agg_func} OF {y_col} BY {x_col}", color="#ffffff", fontsize=11, fontweight="bold")
            plt.xticks(rotation=30, ha="right")

        fig.tight_layout()
        buf = io.StringIO()
        fig.savefig(buf, format="svg", transparent=True)
        plt.close(fig)
        return buf.getvalue()

    @classmethod
    def generate_matplotlib_figure(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        chart_type: str = "BAR",
        agg_func: str = "SUM",
    ) -> str:
        """Generates a dark industrial Matplotlib figure rendered as crisp vector SVG."""
        if df.empty or x_col not in df.columns:
            return "<svg><text fill='#858585'>No data</text></svg>"

        plt.close("all")
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        fig.patch.set_facecolor("#1e1e1e")
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="#858585")
        ax.grid(True, color="#2d2d2d", linestyle="--", alpha=0.7)
        for spine in ax.spines.values():
            spine.set_color("#444444")

        ctype = chart_type.upper()
        if ctype == "HISTOGRAM":
            col_to_plot = y_col if (y_col in df.columns and pd.api.types.is_numeric_dtype(df[y_col])) else x_col
            ax.hist(df[col_to_plot].dropna(), bins=15, color="#007acc", edgecolor="#005999")
            ax.set_title(f"MATPLOTLIB DISTRIBUTION — {col_to_plot}", color="#ffffff", fontsize=11, fontweight="bold")
        elif ctype == "LINE":
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            ax.plot(labels, values, color="#3fb950", marker="o", linewidth=2)
            ax.fill_between(range(len(labels)), values, color="#122a18", alpha=0.5)
            ax.set_title(f"MATPLOTLIB TREND — {agg_func} OF {y_col}", color="#ffffff", fontsize=11, fontweight="bold")
            plt.xticks(rotation=30, ha="right")
        else:  # BAR
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            bars = ax.bar(labels, values, color="#007acc", edgecolor="#58a6ff")
            ax.set_title(f"MATPLOTLIB BAR — {agg_func} OF {y_col} BY {x_col}", color="#ffffff", fontsize=11, fontweight="bold")
            plt.xticks(rotation=30, ha="right")

        fig.tight_layout()
        buf = io.StringIO()
        fig.savefig(buf, format="svg", transparent=True)
        plt.close(fig)
        return buf.getvalue()

    @classmethod
    def plot_dataset(
        cls,
        df: pd.DataFrame,
        engine: str = "plotly",
        chart_type: str = "BAR",
        x_col: str = "",
        y_col: str = "",
        agg_func: str = "SUM",
    ) -> dict[str, Any]:
        """Unified dispatch method for all plotting backends."""
        engine_norm = engine.lower().strip()
        stats = cls.compute_summary_stats(df, y_col or x_col)

        if engine_norm in ("plotly", "plotpy"):
            content = cls.generate_plotly_figure(df, x_col, y_col, chart_type, agg_func)
            format_type = "html"
        elif engine_norm == "seaborn":
            content = cls.generate_seaborn_figure(df, x_col, y_col, chart_type, agg_func)
            format_type = "svg"
        elif engine_norm in ("matplotlib", "mattplot"):
            content = cls.generate_matplotlib_figure(df, x_col, y_col, chart_type, agg_func)
            format_type = "svg"
        else:
            labels, values = cls.aggregate_data(df, x_col, y_col, agg_func=agg_func)
            content = cls.to_chartjs_payload(chart_type, labels, values)
            format_type = "json"

        return {
            "engine": engine_norm,
            "chart_type": chart_type,
            "format": format_type,
            "content": content,
            "stats": stats,
        }

    @classmethod
    def to_chartjs_payload(
        cls,
        chart_type: str,
        labels: list[str],
        values: list[float],
        title: str = "ANALYTICS CHART",
    ) -> dict[str, Any]:
        """Formats aggregated data into standard Chart.js JSON structure for web/react UI."""
        return {
            "type": chart_type.lower(),
            "title": title,
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": title,
                        "data": values,
                        "borderColor": VS_LINE_COLOR if chart_type.lower() == "line" else VS_BAR_COLOR,
                        "backgroundColor": "rgba(35, 134, 54, 0.2)" if chart_type.lower() == "line" else "rgba(0, 122, 204, 0.7)",
                        "borderWidth": 2,
                    }
                ],
            },
        }


class InteractiveChartCanvas:
    """Vector canvas renderer supporting both Tkinter Canvas and headless mock/SVG."""

    def __init__(self, canvas: Any = None) -> None:
        self.canvas = canvas
        self._last_plot_args: dict[str, Any] | None = None
        if hasattr(self.canvas, "configure"):
            self.canvas.configure(bg=VS_CANVAS_BG, highlightthickness=0)
            self.canvas.bind("<Configure>", lambda event: self.redraw())

    def clear(self) -> None:
        if hasattr(self.canvas, "delete"):
            self.canvas.delete("all")

    def plot_bar(self, labels: list[str], values: list[float], title: str = "BAR CHART") -> None:
        self._last_plot_args = {"type": "bar", "labels": labels, "values": values, "title": title}
        self.clear()
        if not hasattr(self.canvas, "create_rectangle"):
            return

        w = getattr(self.canvas, "winfo_width", lambda: 600)() or 600
        h = getattr(self.canvas, "winfo_height", lambda: 240)() or 240

        if not labels or not values or max(values, default=0) <= 0:
            self.canvas.create_text(w / 2, h / 2, text="No numeric data available to plot.", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 10))
            return

        margin_left, margin_right, margin_top, margin_bottom = 65, 30, 35, 45
        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        max_val = max(values)
        num_bars = len(labels)
        bar_gap = 12
        bar_w = max(10, min(60, int((plot_w - (num_bars + 1) * bar_gap) / max(1, num_bars))))

        self.canvas.create_text(margin_left, 16, text=title, fill=VS_TITLE_COLOR, font=("DejaVu Sans Mono", 9, "bold"), anchor="w")

        num_ticks = 4
        for i in range(num_ticks + 1):
            y_tick_val = (max_val / num_ticks) * i
            y_pos = margin_top + plot_h - (i / num_ticks) * plot_h
            self.canvas.create_line(margin_left, y_pos, w - margin_right, y_pos, fill=VS_GRID_COLOR, dash=(2, 4))
            self.canvas.create_text(margin_left - 8, y_pos, text=f"{y_tick_val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="e")

        self.canvas.create_line(margin_left, margin_top, margin_left, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)
        self.canvas.create_line(margin_left, margin_top + plot_h, w - margin_right, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)

        for i, (label, val) in enumerate(zip(labels, values)):
            bx = margin_left + bar_gap + i * (bar_w + bar_gap)
            bh = int((val / max_val) * plot_h) if max_val > 0 else 0
            by = margin_top + plot_h - bh

            self.canvas.create_rectangle(bx, by, bx + bar_w, margin_top + plot_h, fill=VS_BAR_COLOR, outline="#005999")
            self.canvas.create_line(bx, by, bx + bar_w, by, fill="#58a6ff", width=2)
            self.canvas.create_text(bx + bar_w / 2, by - 6, text=f"{val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 7), anchor="s")

            short_lbl = label if len(label) <= 10 else f"{label[:8]}.."
            self.canvas.create_text(bx + bar_w / 2, margin_top + plot_h + 12, text=short_lbl, fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="n")

    def plot_line(self, labels: list[str], values: list[float], title: str = "LINE CHART") -> None:
        self._last_plot_args = {"type": "line", "labels": labels, "values": values, "title": title}
        self.clear()
        if not hasattr(self.canvas, "create_line"):
            return

        w = getattr(self.canvas, "winfo_width", lambda: 600)() or 600
        h = getattr(self.canvas, "winfo_height", lambda: 240)() or 240

        if not labels or not values or max(values, default=0) <= 0:
            self.canvas.create_text(w / 2, h / 2, text="No numeric data available to plot.", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 10))
            return

        margin_left, margin_right, margin_top, margin_bottom = 65, 30, 35, 45
        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        max_val = max(values)
        num_points = len(values)
        step_x = plot_w / max(1, num_points - 1)

        self.canvas.create_text(margin_left, 16, text=title, fill=VS_TITLE_COLOR, font=("DejaVu Sans Mono", 9, "bold"), anchor="w")

        num_ticks = 4
        for i in range(num_ticks + 1):
            y_tick_val = (max_val / num_ticks) * i
            y_pos = margin_top + plot_h - (i / num_ticks) * plot_h
            self.canvas.create_line(margin_left, y_pos, w - margin_right, y_pos, fill=VS_GRID_COLOR, dash=(2, 4))
            self.canvas.create_text(margin_left - 8, y_pos, text=f"{y_tick_val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="e")

        self.canvas.create_line(margin_left, margin_top, margin_left, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)
        self.canvas.create_line(margin_left, margin_top + plot_h, w - margin_right, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)

        points = []
        for i, val in enumerate(values):
            px = margin_left + i * step_x
            py = margin_top + plot_h - (int((val / max_val) * plot_h) if max_val > 0 else 0)
            points.append((px, py))

        if len(points) >= 2 and hasattr(self.canvas, "create_polygon"):
            poly_coords = [margin_left, margin_top + plot_h]
            for px, py in points:
                poly_coords.extend([px, py])
            poly_coords.extend([points[-1][0], margin_top + plot_h])
            self.canvas.create_polygon(*poly_coords, fill="#122a18", outline="")

        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            self.canvas.create_line(x1, y1, x2, y2, fill=VS_LINE_COLOR, width=2)

        for i, (px, py) in enumerate(points):
            if hasattr(self.canvas, "create_oval"):
                self.canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill="#238636", outline="#3fb950")
                self.canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill="#ffffff", outline="#ffffff")
            lbl = labels[i]
            short_lbl = lbl if len(lbl) <= 8 else f"{lbl[:6]}.."
            self.canvas.create_text(px, margin_top + plot_h + 12, text=short_lbl, fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="n")

    def redraw(self) -> None:
        if not self._last_plot_args:
            return
        ptype = self._last_plot_args.get("type")
        if ptype == "bar":
            self.plot_bar(self._last_plot_args["labels"], self._last_plot_args["values"], self._last_plot_args["title"])
        elif ptype == "line":
            self.plot_line(self._last_plot_args["labels"], self._last_plot_args["values"], self._last_plot_args["title"])
