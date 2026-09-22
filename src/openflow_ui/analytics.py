from __future__ import annotations

import tkinter as tk
from typing import Any, Literal
import pandas as pd

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
    """Computes descriptive statistics and aggregated plotting data."""

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
            # Fallback to count for non-numeric Y
            grouped = clean_df.groupby(x_col)[y_col].count().reset_index()
        else:
            grouped = clean_df.groupby(x_col)[y_col].agg(func).reset_index()

        # Sort by value descending and limit top categories
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

        min_val, max_val = series.min(), series.max()
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


class InteractiveChartCanvas:
    """Pure-native vector graphics charting canvas for Tkinter."""

    def __init__(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.canvas.configure(bg=VS_CANVAS_BG, highlightthickness=0)
        self.canvas.bind("<Configure>", lambda event: self.redraw())

        # Last plotted data cache for responsive redraw
        self._last_plot_args: dict[str, Any] | None = None

    def clear(self) -> None:
        self.canvas.delete("all")

    def plot_bar(self, labels: list[str], values: list[float], title: str = "BAR CHART") -> None:
        self._last_plot_args = {"type": "bar", "labels": labels, "values": values, "title": title}
        self.clear()

        w = self.canvas.winfo_width() or 600
        h = self.canvas.winfo_height() or 240

        if not labels or not values or max(values, default=0) <= 0:
            self.canvas.create_text(w / 2, h / 2, text="No numeric data available to plot.", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 10))
            return

        margin_left = 65
        margin_right = 30
        margin_top = 35
        margin_bottom = 45

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        max_val = max(values)
        num_bars = len(labels)
        bar_gap = 12
        bar_w = max(10, min(60, int((plot_w - (num_bars + 1) * bar_gap) / num_bars)))

        # Title
        self.canvas.create_text(margin_left, 16, text=title, fill=VS_TITLE_COLOR, font=("DejaVu Sans Mono", 9, "bold"), anchor="w")

        # Grid and Y Ticks
        num_ticks = 4
        for i in range(num_ticks + 1):
            y_tick_val = (max_val / num_ticks) * i
            y_pos = margin_top + plot_h - (i / num_ticks) * plot_h
            # Grid line
            self.canvas.create_line(margin_left, y_pos, w - margin_right, y_pos, fill=VS_GRID_COLOR, dash=(2, 4))
            # Tick text
            self.canvas.create_text(margin_left - 8, y_pos, text=f"{y_tick_val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="e")

        # Axes
        self.canvas.create_line(margin_left, margin_top, margin_left, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)
        self.canvas.create_line(margin_left, margin_top + plot_h, w - margin_right, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)

        # Draw Bars
        for i, (label, val) in enumerate(zip(labels, values)):
            bx = margin_left + bar_gap + i * (bar_w + bar_gap)
            bh = int((val / max_val) * plot_h) if max_val > 0 else 0
            by = margin_top + plot_h - bh

            # Bar rectangle
            self.canvas.create_rectangle(bx, by, bx + bar_w, margin_top + plot_h, fill=VS_BAR_COLOR, outline=VS_BAR_COLOR)

            # Value label on top of bar
            self.canvas.create_text(bx + bar_w / 2, by - 6, text=f"{val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 7), anchor="s")

            # X label
            short_lbl = label if len(label) <= 10 else f"{label[:8]}.."
            self.canvas.create_text(bx + bar_w / 2, margin_top + plot_h + 12, text=short_lbl, fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="n")

    def plot_line(self, labels: list[str], values: list[float], title: str = "LINE CHART") -> None:
        self._last_plot_args = {"type": "line", "labels": labels, "values": values, "title": title}
        self.clear()

        w = self.canvas.winfo_width() or 600
        h = self.canvas.winfo_height() or 240

        if not labels or not values or max(values, default=0) <= 0:
            self.canvas.create_text(w / 2, h / 2, text="No numeric data available to plot.", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 10))
            return

        margin_left = 65
        margin_right = 30
        margin_top = 35
        margin_bottom = 45

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        max_val = max(values)
        num_points = len(values)
        step_x = plot_w / max(1, num_points - 1)

        # Title
        self.canvas.create_text(margin_left, 16, text=title, fill=VS_TITLE_COLOR, font=("DejaVu Sans Mono", 9, "bold"), anchor="w")

        # Grid lines
        num_ticks = 4
        for i in range(num_ticks + 1):
            y_tick_val = (max_val / num_ticks) * i
            y_pos = margin_top + plot_h - (i / num_ticks) * plot_h
            self.canvas.create_line(margin_left, y_pos, w - margin_right, y_pos, fill=VS_GRID_COLOR, dash=(2, 4))
            self.canvas.create_text(margin_left - 8, y_pos, text=f"{y_tick_val:g}", fill=VS_TEXT_COLOR, font=("DejaVu Sans Mono", 8), anchor="e")

        # Axes
        self.canvas.create_line(margin_left, margin_top, margin_left, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)
        self.canvas.create_line(margin_left, margin_top + plot_h, w - margin_right, margin_top + plot_h, fill=VS_AXIS_COLOR, width=1)

        # Points and Line
        points = []
        for i, val in enumerate(values):
            px = margin_left + i * step_x
            py = margin_top + plot_h - (int((val / max_val) * plot_h) if max_val > 0 else 0)
            points.append((px, py))

        # Draw connecting line segments
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            self.canvas.create_line(x1, y1, x2, y2, fill=VS_LINE_COLOR, width=2)

        # Draw point dots and labels
        for i, (px, py) in enumerate(points):
            self.canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=VS_POINT_COLOR, outline=VS_POINT_COLOR)
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

