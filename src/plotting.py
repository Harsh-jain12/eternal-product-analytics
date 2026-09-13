"""Shared plotting/reporting helpers for the Eternal Product Analytics notebooks.

Defined once here (per CLAUDE.md convention) and imported by every notebook
after 00_data_quality.ipynb instead of being redefined.
"""

import os

import matplotlib.pyplot as plt
import pandas as pd

FIGURES_DIR = os.path.join("outputs", "figures")
TABLES_DIR = os.path.join("outputs", "tables")

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(TABLES_DIR, exist_ok=True)


def frame(figsize=(10, 6)):
    """Create a fig/ax pair with room reserved at top (title) and bottom (takeaway box)."""
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(top=0.84, bottom=0.20)
    return fig, ax


def add_title(fig, title, subtitle=None):
    """Title via fig.text plus an optional one-line subtitle stating scope/caveats."""
    fig.text(0.02, 0.97, title, fontsize=14, fontweight="bold", ha="left", va="top")
    if subtitle:
        fig.text(0.02, 0.905, subtitle, fontsize=9.5, color="dimgray", ha="left", va="top")


def add_takeaway(fig, text):
    """Bottom-anchored TAKEAWAY box stating the point of the figure in one sentence."""
    fig.text(
        0.02,
        0.03,
        f"TAKEAWAY: {text}",
        fontsize=9.5,
        ha="left",
        va="bottom",
        wrap=True,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#FFF3CD", edgecolor="#8a6d3b", linewidth=0.8),
    )


def save(fig, name):
    """Save a figure to outputs/figures/<name>.png at report quality."""
    path = os.path.join(FIGURES_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path


def show_df(df, name=None, max_rows=20):
    """Display a dataframe truncated for notebook output; optionally persist full table to CSV."""
    if name is not None:
        path = os.path.join(TABLES_DIR, f"{name}.csv")
        df.to_csv(path, index=False)
    with pd.option_context("display.max_rows", max_rows, "display.max_columns", None, "display.width", 160):
        print(df.head(max_rows) if len(df) > max_rows else df)
    return df


def thousands(x, _pos=None):
    """Matplotlib tick formatter: 1234567 -> '1,234,567'."""
    try:
        return f"{x:,.0f}"
    except (TypeError, ValueError):
        return str(x)
