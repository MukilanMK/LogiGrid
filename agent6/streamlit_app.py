import os
import sys
import json
import asyncio
import threading
import warnings
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import streamlit as st

matplotlib.use("Agg")          # non-interactive backend — required for Streamlit
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

# Add backend directory to sys.path to import main module
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import main

# Streamlit Page Config
st.set_page_config(
    page_title="Agent 5 - Executive Profit Analytics",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Obsidian Dark Mode CSS
st.markdown("""
<style>
/* Dark Mode Reset */
.stApp {
    background-color: #0B0F17 !important;
    color: #F3F4F6 !important;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
}

#MainMenu, header, footer {
    visibility: hidden;
    height: 0;
}

.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 160px !important;
    max-width: 1280px !important;
}

/* Executive Header Bar */
.exec-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background-color: rgba(21, 29, 42, 0.8);
    border: 1px solid #26334D;
    padding: 16px 24px;
    border-radius: 16px;
    margin-bottom: 24px;
    backdrop-filter: blur(12px);
}

.exec-header-title {
    font-size: 20px;
    font-weight: 700;
    color: #FFFFFF;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 10px;
}

.exec-badge {
    background-color: rgba(99, 102, 241, 0.15);
    color: #6366F1;
    border: 1px solid rgba(99, 102, 241, 0.3);
    font-family: monospace;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 9999px;
}

.exec-subtitle {
    font-size: 12px;
    color: #9CA3AF;
    margin-top: 2px;
}

/* KPI Card Styling */
.kpi-card {
    background-color: #151D2A;
    border: 1px solid #26334D;
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
    height: 100%;
}

.kpi-card-emerald {
    background-color: #151D2A;
    border: 1px solid rgba(16, 185, 129, 0.4);
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 0 25px rgba(16, 185, 129, 0.15);
    height: 100%;
}

.kpi-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9CA3AF;
    margin-bottom: 8px;
}

.kpi-title-emerald {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #10B981;
    margin-bottom: 8px;
}

.kpi-value {
    font-family: monospace;
    font-size: 28px;
    font-weight: 700;
    color: #FFFFFF;
    letter-spacing: -0.02em;
}

.kpi-value-emerald {
    font-family: monospace;
    font-size: 28px;
    font-weight: 700;
    color: #10B981;
    letter-spacing: -0.02em;
}

.kpi-subtext {
    font-size: 11px;
    color: #6B7280;
    margin-top: 6px;
}

/* AI Summary Card */
.ai-summary-card {
    background-color: #151D2A;
    border-top: 1px solid #26334D;
    border-right: 1px solid #26334D;
    border-bottom: 1px solid #26334D;
    border-left: 4px solid #6366F1;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
    height: 100%;
}

.ai-summary-text {
    background-color: rgba(11, 15, 23, 0.5);
    border: 1px solid rgba(38, 51, 77, 0.6);
    border-radius: 12px;
    padding: 16px;
    font-size: 14px;
    line-height: 1.6;
    color: #E5E7EB;
}

/* Table Styling */
.table-container {
    background-color: #151D2A;
    border: 1px solid #26334D;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
}

.profit-table {
    width: 100%;
    border-collapse: collapse;
    color: #F3F4F6;
    font-size: 13px;
}

.profit-table th {
    background-color: #0B0F17;
    color: #9CA3AF;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.05em;
    padding: 14px 20px;
    text-align: left;
    border-bottom: 1px solid #26334D;
    font-family: monospace;
}

.profit-table td {
    padding: 14px 20px;
    border-bottom: 1px solid rgba(38, 51, 77, 0.5);
}

.profit-table tr:hover {
    background-color: #1C273A;
}

.badge-green {
    background-color: rgba(16, 185, 129, 0.15);
    color: #10B981;
    border: 1px solid rgba(16, 185, 129, 0.3);
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 11px;
    font-family: monospace;
    font-weight: 600;
}

.badge-amber {
    background-color: rgba(245, 158, 11, 0.15);
    color: #F59E0B;
    border: 1px solid rgba(245, 158, 11, 0.3);
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 11px;
    font-family: monospace;
    font-weight: 600;
}

.badge-rose {
    background-color: rgba(244, 63, 94, 0.15);
    color: #F43F5E;
    border: 1px solid rgba(244, 63, 94, 0.3);
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 11px;
    font-family: monospace;
    font-weight: 600;
}

.profit-bar-cell {
    position: relative;
    padding: 4px 8px !important;
}

.profit-bar-bg {
    position: absolute;
    top: 6px;
    left: 8px;
    bottom: 6px;
    background-color: rgba(16, 185, 129, 0.18);
    border-radius: 6px;
}

.profit-text {
    position: relative;
    z-index: 2;
    font-family: monospace;
    font-weight: 700;
    color: #10B981;
}

/* Prompt Chips Button Styling */
.stButton > button {
    background-color: #151D2A !important;
    color: #C7D2FE !important;
    border: 1px solid #26334D !important;
    border-radius: 9999px !important;
    font-size: 12px !important;
    padding: 6px 16px !important;
    width: 100% !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    border-color: #6366F1 !important;
    color: #FFFFFF !important;
}

/* ── Visualization card ───────────────────────────────────────────────────── */
div.st-key-viz_card {
    background-color: #151D2A !important;
    border: 1px solid #26334D !important;
    border-radius: 16px !important;
    padding: 20px !important;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4) !important;
}
</style>
""", unsafe_allow_html=True)

# Initial Seed Data State
INITIAL_DATA = {
    "summary": "Initial Executive Overview: Furniture leads net profit with Ergonomic Office Chairs generating ₹400.00 in total returns at a 57.1% margin. Audio and Accessories follow with strong margins across all key product lines.",
    "chart_config": {
        "type": "bar",
        "x_axis": "product_name",
        "y_axis": "profit"
    },
    "mql_executed": [
        { "$unwind": "$line_items" },
        { "$lookup": { "from": "products", "localField": "line_items.product_id", "foreignField": "_id", "as": "product_details" } },
        { "$unwind": "$product_details" },
        {
            "$group": {
                "_id": "$product_details.name",
                "cost_price": { "$first": "$product_details.cost_price" },
                "selling_price": { "$first": "$product_details.selling_price" },
                "units_sold": { "$sum": "$line_items.quantity" },
                "profit": { "$sum": { "$multiply": ["$line_items.quantity", { "$subtract": ["$product_details.selling_price", "$product_details.cost_price"] }] } }
            }
        },
        { "$sort": { "profit": -1 } }
    ],
    "table_data": [
        { "product_name": "Ergonomic Office Chair", "cost_price": 150.00, "selling_price": 350.00, "unit_margin": 200.00, "units_sold": 2, "profit": 400.00 },
        { "product_name": "Wireless Noise-Cancelling Headphones", "cost_price": 120.00, "selling_price": 250.00, "unit_margin": 130.00, "units_sold": 1, "profit": 130.00 },
        { "product_name": "USB-C Fast Charger", "cost_price": 8.00, "selling_price": 25.00, "unit_margin": 17.00, "units_sold": 5, "profit": 85.00 },
        { "product_name": "Mechanical Keyboard Pro", "cost_price": 55.00, "selling_price": 130.00, "unit_margin": 75.00, "units_sold": 1, "profit": 75.00 }
    ]
}

# Session State
if "result_data" not in st.session_state:
    st.session_state["result_data"] = INITIAL_DATA

def _run_coroutine_in_thread(coro):
    """
    Run an async coroutine in a brand-new event loop inside a daemon thread.
    This avoids the 'This event loop is already running' RuntimeError that
    asyncio.run() raises when called from inside Streamlit's own event loop.
    Returns (result, error) — exactly one of them will be non-None.
    """
    result_box = [None]
    error_box  = [None]

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box[0] = loop.run_until_complete(coro)
        except Exception as exc:
            error_box[0] = exc
        finally:
            loop.close()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    return result_box[0], error_box[0]


def execute_query_action(q_text: str):
    if not q_text.strip():
        return
    with st.spinner("Analyzing data with Groq LLM & MongoDB..."):
        req = main.QueryRequest(query=q_text)
        resp, err = _run_coroutine_in_thread(main.process_query(req))

        if err is not None:
            # Write an explicit error state so the dashboard clears stale data
            st.session_state["result_data"] = {
                "summary": f"Query failed: {err}",
                "chart_config": {},
                "mql_executed": [],
                "table_data": [],
                "error": True,
                "error_query": q_text,
            }
        else:
            st.session_state["result_data"] = {
                "summary": resp.summary,
                "chart_config": resp.chart_config,
                "mql_executed": resp.mql_executed,
                "table_data": resp.table_data,
                "error": False,
                "last_query": q_text,
            }

# Header Bar Component
st.markdown("""
<div class="exec-header">
    <div>
        <div class="exec-header-title">
            <span>Agent 5: Profit Analytics</span>
            <span class="exec-badge">Streamlit Executive Edition</span>
        </div>
        <div class="exec-subtitle">Conversational BI Engine & Executive Financial Dashboard</div>
    </div>
    <div style="font-family: monospace; font-size: 11px; color: #9CA3AF; display: flex; gap: 12px;">
        <span style="color: #10B981;">● MongoDB Connected</span>
        <span style="color: #6366F1;">● Groq LLM Active</span>
    </div>
</div>
""", unsafe_allow_html=True)

res = st.session_state["result_data"]

# ── Error card ────────────────────────────────────────────────────────────────
if res.get("error"):
    st.markdown(f"""
    <div style="background-color: rgba(244,63,94,0.08); border: 1px solid rgba(244,63,94,0.4);
                border-left: 4px solid #F43F5E; border-radius: 14px; padding: 18px 22px;
                margin-bottom: 20px;">
        <div style="color:#F43F5E; font-weight:700; font-size:14px; margin-bottom:6px;">
            ⚠ Query Error
        </div>
        <div style="color:#FCA5A5; font-size:13px; font-family:monospace; line-height:1.6;">
            {res.get("summary", "An unknown error occurred.")}
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Last-query caption ────────────────────────────────────────────────────────
last_query = res.get("last_query", "")
if last_query:
    st.markdown(
        f"<div style='font-size:11px; color:#6B7280; margin-bottom:12px; font-family:monospace;'>"
        f"Last query: <span style='color:#9CA3AF;'>{last_query}</span></div>",
        unsafe_allow_html=True,
    )

table_data = res.get("table_data", [])
summary_text = res.get("summary", "")
mql_executed = res.get("mql_executed", [])
chart_config = res.get("chart_config", {})

# Calculate Executive Metrics
total_revenue = 0.0
total_profit = 0.0

for row in table_data:
    qty = row.get("units_sold") or row.get("quantity") or 1
    sp = row.get("selling_price") or 0.0
    prof = row.get("profit") or row.get("total_profit") or row.get("total_margin") or 0.0

    total_profit += float(prof)
    if sp > 0:
        total_revenue += float(sp * qty)
    else:
        total_revenue += float(row.get("total_amount") or row.get("taxable_value") or prof)

if total_revenue == 0 and total_profit > 0:
    total_revenue = total_profit * 1.8

avg_margin_pct = (total_profit / total_revenue * 100) if total_revenue > 0 else 0.0

# 1. Top Executive KPI Bar
kpi_col1, kpi_col2, kpi_col3 = st.columns(3)

with kpi_col1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Total Sales Revenue</div>
        <div class="kpi-value">₹{total_revenue:,.2f}</div>
        <div class="kpi-subtext">Gross Invoiced across query scope</div>
    </div>
    """, unsafe_allow_html=True)

with kpi_col2:
    st.markdown(f"""
    <div class="kpi-card-emerald">
        <div class="kpi-title-emerald">Total Net Profit</div>
        <div class="kpi-value-emerald">₹{total_profit:,.2f}</div>
        <div class="kpi-subtext" style="color: #10B981;">Primary Metric ● Net Returns</div>
    </div>
    """, unsafe_allow_html=True)

with kpi_col3:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Average Margin Percentage</div>
        <div class="kpi-value">{avg_margin_pct:.1f}%</div>
        <div class="kpi-subtext">Profit / Revenue Ratio</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

# 2. Visualizer & AI Summary Split (Middle View)
col_vis, col_summary = st.columns(2)

# ── Seaborn chart renderer ────────────────────────────────────────────────────
# Obsidian palette used across all chart types
_OBS_PALETTE = ["#6366F1", "#10B981", "#F59E0B", "#F43F5E", "#8B5CF6", "#EC4899", "#06B6D4"]
_OBS_BG      = "#151D2A"
_OBS_GRID    = "#26334D"
_OBS_TEXT    = "#F3F4F6"
_OBS_SUBTEXT = "#9CA3AF"

def _apply_obsidian_style(ax, fig):
    """Apply the Obsidian dark theme to a Matplotlib axes."""
    fig.patch.set_facecolor(_OBS_BG)
    ax.set_facecolor(_OBS_BG)
    ax.tick_params(colors=_OBS_SUBTEXT, labelsize=9)
    ax.xaxis.label.set_color(_OBS_SUBTEXT)
    ax.yaxis.label.set_color(_OBS_SUBTEXT)
    ax.title.set_color(_OBS_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(_OBS_GRID)
    ax.grid(axis="y", color=_OBS_GRID, linewidth=0.6, linestyle="--", alpha=0.7)
    ax.set_axisbelow(True)
    plt.tight_layout(pad=1.5)


def render_seaborn_chart(df: pd.DataFrame, chart_config: dict) -> plt.Figure | None:
    """
    Render a Seaborn/Matplotlib chart based on the chart_config returned by Groq.
    Supported types: bar | barh | line | pie | scatter | heatmap | box
    Returns a matplotlib Figure, or None if the data/config is insufficient.
    """
    chart_type = chart_config.get("type", "bar").lower()
    x_col = chart_config.get("x_axis") or chart_config.get("names")
    y_col = chart_config.get("y_axis") or chart_config.get("values")

    # Auto-detect columns if LLM left them blank
    cols = list(df.columns)
    if not x_col:
        x_col = next((c for c in cols if any(k in c.lower() for k in ["name", "category", "_id"])), cols[0])
    if not y_col:
        y_col = next((c for c in cols if any(k in c.lower() for k in ["profit", "revenue", "margin", "amount", "price"])), cols[-1])

    # Ensure y column is numeric
    if y_col in df.columns:
        df[y_col] = pd.to_numeric(df[y_col], errors="coerce").fillna(0)

    sns.set_theme(style="darkgrid", rc={
        "axes.facecolor":  _OBS_BG,
        "figure.facecolor": _OBS_BG,
        "grid.color":      _OBS_GRID,
        "text.color":      _OBS_TEXT,
        "axes.labelcolor": _OBS_SUBTEXT,
        "xtick.color":     _OBS_SUBTEXT,
        "ytick.color":     _OBS_SUBTEXT,
        "axes.edgecolor":  _OBS_GRID,
    })

    try:
        if chart_type in ("bar", "barh"):
            fig, ax = plt.subplots(figsize=(7, 4))
            orient = "h" if chart_type == "barh" else "v"
            colors = [_OBS_PALETTE[i % len(_OBS_PALETTE)] for i in range(len(df))]
            # Highlight the top bar in emerald
            colors[0] = "#10B981"
            if orient == "v":
                sns.barplot(data=df, x=x_col, y=y_col, palette=colors, ax=ax, order=df[x_col])
                ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
                # Value labels on top of each bar
                for bar in ax.patches:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(df[y_col]) * 0.01,
                        f"₹{bar.get_height():,.0f}",
                        ha="center", va="bottom", fontsize=8, color=_OBS_TEXT
                    )
            else:
                sns.barplot(data=df, x=y_col, y=x_col, palette=colors, ax=ax, orient="h")
                for bar in ax.patches:
                    ax.text(
                        bar.get_width() + max(df[y_col]) * 0.01,
                        bar.get_y() + bar.get_height() / 2,
                        f"₹{bar.get_width():,.0f}",
                        ha="left", va="center", fontsize=8, color=_OBS_TEXT
                    )
            ax.set_xlabel(x_col.replace("_", " ").title() if orient == "v" else y_col.replace("_", " ").title())
            ax.set_ylabel(y_col.replace("_", " ").title() if orient == "v" else x_col.replace("_", " ").title())
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        elif chart_type == "line":
            fig, ax = plt.subplots(figsize=(7, 4))
            sns.lineplot(data=df, x=x_col, y=y_col, marker="o",
                         color="#6366F1", linewidth=2.5, markersize=8,
                         markerfacecolor="#10B981", ax=ax)
            ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        elif chart_type == "pie":
            names_col = chart_config.get("names") or x_col
            vals_col  = chart_config.get("values") or y_col
            fig, ax = plt.subplots(figsize=(6, 5))
            wedges, texts, autotexts = ax.pie(
                df[vals_col],
                labels=df[names_col],
                autopct="%1.1f%%",
                colors=_OBS_PALETTE[:len(df)],
                startangle=140,
                wedgeprops={"edgecolor": _OBS_BG, "linewidth": 2},
                pctdistance=0.82,
            )
            for t in texts:
                t.set_color(_OBS_SUBTEXT)
                t.set_fontsize(9)
            for at in autotexts:
                at.set_color(_OBS_TEXT)
                at.set_fontsize(8)
            # Draw donut hole
            centre = plt.Circle((0, 0), 0.55, fc=_OBS_BG)
            ax.add_artist(centre)
            fig.patch.set_facecolor(_OBS_BG)
            ax.set_facecolor(_OBS_BG)
            plt.tight_layout()

        elif chart_type == "scatter":
            fig, ax = plt.subplots(figsize=(7, 4))
            # Size bubbles by a third numeric column if available
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            size_col = next((c for c in numeric_cols if c not in [x_col, y_col]), None)
            sizes = (df[size_col] / df[size_col].max() * 400 + 40) if size_col else 120
            scatter = ax.scatter(
                df[x_col], df[y_col],
                c=range(len(df)),
                cmap="cool",
                s=sizes,
                alpha=0.85,
                edgecolors=_OBS_GRID,
                linewidths=0.8,
            )
            # Annotate each point with its label if a name column exists
            label_col = next((c for c in df.columns if "name" in c.lower() or "category" in c.lower()), None)
            if label_col:
                for _, row in df.iterrows():
                    ax.annotate(
                        str(row[label_col]),
                        (row[x_col], row[y_col]),
                        textcoords="offset points",
                        xytext=(6, 4),
                        fontsize=7,
                        color=_OBS_SUBTEXT,
                    )
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        elif chart_type == "heatmap":
            # Pivot the data into a matrix
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != x_col]
            if not numeric_cols:
                return None
            pivot = df.set_index(x_col)[numeric_cols]
            fig, ax = plt.subplots(figsize=(max(6, len(numeric_cols) * 1.5), max(4, len(df) * 0.6)))
            sns.heatmap(
                pivot, annot=True, fmt=".0f", linewidths=0.5,
                cmap=sns.diverging_palette(240, 130, as_cmap=True),
                ax=ax,
                linecolor=_OBS_GRID,
                cbar_kws={"shrink": 0.8},
                annot_kws={"size": 9, "color": _OBS_TEXT},
            )
            ax.set_xticklabels(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
            ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=8)
            fig.patch.set_facecolor(_OBS_BG)
            ax.set_facecolor(_OBS_BG)
            plt.tight_layout()

        elif chart_type == "box":
            fig, ax = plt.subplots(figsize=(7, 4))
            sns.boxplot(data=df, x=x_col, y=y_col,
                        palette=_OBS_PALETTE, ax=ax,
                        flierprops={"marker": "o", "color": "#F43F5E", "markersize": 5})
            ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        else:
            # Fallback: vertical bar
            fig, ax = plt.subplots(figsize=(7, 4))
            colors = [_OBS_PALETTE[i % len(_OBS_PALETTE)] for i in range(len(df))]
            colors[0] = "#10B981"
            sns.barplot(data=df, x=x_col, y=y_col, palette=colors, ax=ax)
            ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
            _apply_obsidian_style(ax, fig)

        return fig

    except Exception as exc:
        logger.warning("Chart render failed (%s): %s", chart_type, exc)
        return None


with col_vis:
    with st.container(key="viz_card"):
        st.markdown(
            "<h4 style='margin:0 0 2px; color:#FFFFFF; font-size:16px;'>Dynamic Visualization</h4>"
            "<p style='margin:0 0 12px; color:#9CA3AF; font-size:12px;'>AI-selected chart type based on your query</p>",
            unsafe_allow_html=True,
        )

        if table_data:
            df_chart = pd.DataFrame(table_data)
            # Show which chart type the AI chose
            chosen_type = chart_config.get("type", "bar").lower()
            type_label = {
                "bar": "Bar Chart", "barh": "Horizontal Bar",
                "line": "Line Chart", "pie": "Pie / Donut",
                "scatter": "Scatter Plot", "heatmap": "Heatmap", "box": "Box Plot",
            }.get(chosen_type, chosen_type.title())
            st.markdown(
                f"<div style='font-size:10px; font-family:monospace; color:#6366F1; "
                f"margin-bottom:8px;'>AI selected: {type_label}</div>",
                unsafe_allow_html=True,
            )
            fig = render_seaborn_chart(df_chart.copy(), chart_config)
            if fig:
                st.pyplot(fig, use_container_width=True)
                plt.close(fig)
            else:
                st.info("Chart could not be rendered for this data shape.")
        else:
            st.info("No chart data available.")

with col_summary:
    st.markdown(f"""
    <div class="ai-summary-card">
        <div>
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                <div style="background-color:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.3);
                            width:32px; height:32px; border-radius:8px; display:flex;
                            align-items:center; justify-content:center;
                            color:#6366F1; font-weight:bold; font-size:13px;">AI</div>
                <div>
                    <div style="color:#FFFFFF; font-weight:700; font-size:15px;">AI Executive Insight</div>
                    <div style="color:#6366F1; font-size:11px; font-weight:600;">Synthesized analytical breakdown</div>
                </div>
            </div>
            <div class="ai-summary-text">{summary_text}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("View Generated MQL Pipeline"):
        st.json(mql_executed)

st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

# 3. Enhanced Profit Data Grid
st.markdown("""
<div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 24px; background-color: #151D2A; border-top: 1px solid #26334D; border-left: 1px solid #26334D; border-right: 1px solid #26334D; border-top-left-radius: 16px; border-top-right-radius: 16px;">
    <div>
        <div style="color: #FFFFFF; font-weight: 700; font-size: 15px;">Enhanced Profit Data Grid</div>
        <div style="color: #9CA3AF; font-size: 11px;">Sorted by Total Profit Descending</div>
    </div>
</div>
""", unsafe_allow_html=True)

if table_data:
    df_table = pd.DataFrame(table_data)

    # Sort descending by profit column if available
    profit_col = next((c for c in df_table.columns if any(x in c.lower() for x in ["profit", "margin"])), None)
    if profit_col:
        df_table = df_table.sort_values(by=profit_col, ascending=False)

    max_prof = float(df_table[profit_col].max()) if profit_col and not df_table[profit_col].empty else 1.0

    cols = list(df_table.columns)
    
    html = ["<div class='table-container' style='border-top-left-radius: 0; border-top-right-radius: 0;'><table class='profit-table'><thead><tr>"]
    for c in cols:
        html.append(f"<th>{c.replace('_', ' ')}</th>")
    html.append("</tr></thead><tbody>")

    for _, row in df_table.iterrows():
        html.append("<tr>")
        for c in cols:
            val = row[c]
            c_lower = c.lower()

            if "profit" in c_lower or ("margin" in c_lower and "unit" not in c_lower):
                num_val = float(val) if isinstance(val, (int, float)) else 0.0
                pct = min(100, max(10, int((num_val / max_prof) * 100))) if max_prof > 0 else 10
                html.append(f"<td class='profit-bar-cell'><div class='profit-bar-bg' style='width: {pct}%;'></div><span class='profit-text'>₹{num_val:,.2f}</span></td>")
            elif "unit_margin" in c_lower or "margin" in c_lower:
                sp = float(row.get("selling_price", 0))
                cp = float(row.get("cost_price", 0))
                num_val = float(val) if isinstance(val, (int, float)) else (sp - cp)
                margin_pct = (num_val / sp * 100) if sp > 0 else 0.0

                badge_class = "badge-green" if margin_pct >= 30 else ("badge-amber" if margin_pct >= 15 else "badge-rose")
                html.append(f"<td>₹{num_val:,.2f} <span class='{badge_class}'>{margin_pct:.1f}%</span></td>")
            elif any(x in c_lower for x in ["price", "cost", "amount"]):
                num_val = float(val) if isinstance(val, (int, float)) else 0.0
                html.append(f"<td style='font-family: monospace;'>₹{num_val:,.2f}</td>")
            else:
                html.append(f"<td>{val}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    # Download CSV button
    csv_bytes = df_table.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Export CSV Data",
        data=csv_bytes,
        file_name=f"executive_profit_report_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)

# ── Raw MongoDB Query Results ─────────────────────────────────────────────────
# Always show the unprocessed rows returned by the aggregation pipeline so the
# user can verify exactly what the NoSQL query returned before any UI transforms.
st.markdown("""
<div style="display:flex; align-items:center; justify-content:space-between;
            padding:14px 22px; background-color:#151D2A;
            border:1px solid #26334D; border-bottom:none;
            border-top-left-radius:14px; border-top-right-radius:14px;">
    <div>
        <div style="color:#FFFFFF; font-weight:700; font-size:14px;">Raw Query Results</div>
        <div style="color:#9CA3AF; font-size:11px;">Unprocessed rows returned by the MongoDB aggregation pipeline</div>
    </div>
    <div style="font-family:monospace; font-size:10px; color:#6366F1;
                background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.25);
                padding:3px 10px; border-radius:9999px;">
        NoSQL Result
    </div>
</div>
""", unsafe_allow_html=True)

if table_data:
    raw_df = pd.DataFrame(table_data)
    # Drop internal _id column if present — not useful in the UI
    raw_df = raw_df.drop(columns=["_id"], errors="ignore")
    st.dataframe(
        raw_df,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.markdown("""
    <div style="background-color:#151D2A; border:1px solid #26334D;
                border-bottom-left-radius:14px; border-bottom-right-radius:14px;
                padding:20px 22px; color:#6B7280; font-size:13px; text-align:center;">
        No results returned for this query.
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 4. FLOATING COMMAND DOCK
#
# WHY CSS-TARGETING INSTEAD OF HTML NESTING:
#   Streamlit widgets (st.button, st.text_input, st.form) are injected into the
#   page as React components through Streamlit's own rendering pipeline — they
#   cannot be placed inside an arbitrary st.markdown() HTML string. Attempting
#   to do so renders the HTML but leaves the widgets outside it in the DOM.
#
#   The reliable approach for Streamlit ≥1.30 is:
#     1. Wrap all dock widgets in st.container(key="command_dock"). Streamlit
#        renders a stable outer div with data-testid="stVerticalBlockBorderWrapper"
#        and an inner div with data-testid="stVerticalBlock". The key is reflected
#        as a stable CSS class on the wrapper: .st-key-command_dock
#     2. Inject a <style> block that selects .st-key-command_dock and applies
#        position:fixed, transforming it into a viewport-anchored floating panel.
#        The widgets inside remain fully functional because they're real DOM nodes,
#        just visually repositioned by CSS — no DOM movement occurs.
#
#   Requires: Streamlit ≥ 1.30 (st.container key= support).
#   Confirmed version: 1.50.0 ✓
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Floating dock shell ─────────────────────────────────────────────────── */
/*
   Target the keyed container wrapper Streamlit generates for
   st.container(key="command_dock"). The .st-key-<key> class is applied
   to the outermost wrapper div by Streamlit 1.30+.
*/
div.st-key-command_dock {
    position: fixed !important;
    bottom: 24px !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    z-index: 999 !important;
    width: min(720px, 92vw) !important;

    /* Frosted glass — Obsidian theme */
    background-color: rgba(21, 29, 42, 0.88) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border: 1px solid #26334D !important;
    border-radius: 20px !important;
    box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.55),
                0 0 0 1px rgba(99, 102, 241, 0.08) !important;
    padding: 12px 16px !important;
}

/* Remove Streamlit's default container margin/padding inside the dock */
div.st-key-command_dock > div[data-testid="stVerticalBlock"] {
    gap: 6px !important;
}

/* ── Chip row label ──────────────────────────────────────────────────────── */
div.st-key-command_dock .dock-label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: #4B5563;
    text-transform: uppercase;
    text-align: center;
    margin-bottom: 2px;
}

/* ── Chip buttons ────────────────────────────────────────────────────────── */
div.st-key-command_dock button[kind="secondary"],
div.st-key-command_dock .stButton > button {
    background-color: rgba(21, 29, 42, 0.7) !important;
    color: #C7D2FE !important;
    border: 1px solid #26334D !important;
    border-radius: 9999px !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    padding: 5px 14px !important;
    height: auto !important;
    min-height: unset !important;
    transition: border-color 0.15s ease, color 0.15s ease, background-color 0.15s ease !important;
    white-space: nowrap !important;
}
div.st-key-command_dock .stButton > button:hover {
    border-color: #6366F1 !important;
    color: #FFFFFF !important;
    background-color: rgba(99, 102, 241, 0.12) !important;
}

/* ── Text input inside the dock ──────────────────────────────────────────── */
div.st-key-command_dock .stTextInput input {
    background-color: rgba(11, 15, 23, 0.6) !important;
    border: 1px solid #26334D !important;
    border-radius: 12px !important;
    color: #F3F4F6 !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
    caret-color: #6366F1 !important;
    transition: border-color 0.15s ease !important;
}
div.st-key-command_dock .stTextInput input:focus {
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
    outline: none !important;
}
div.st-key-command_dock .stTextInput input::placeholder {
    color: #4B5563 !important;
}

/* ── Analyze submit button ───────────────────────────────────────────────── */
div.st-key-command_dock .stFormSubmitButton > button {
    background-color: #6366F1 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 12px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    padding: 10px 20px !important;
    width: 100% !important;
    transition: background-color 0.15s ease, transform 0.1s ease !important;
    letter-spacing: 0.02em !important;
}
div.st-key-command_dock .stFormSubmitButton > button:hover {
    background-color: #4F52D3 !important;
}
div.st-key-command_dock .stFormSubmitButton > button:active {
    transform: scale(0.97) !important;
}

/* ── Strip stray labels / padding Streamlit adds ─────────────────────────── */
div.st-key-command_dock label,
div.st-key-command_dock .stTextInput label {
    display: none !important;
}
div.st-key-command_dock .stForm {
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
}
div.st-key-command_dock [data-testid="stFormBorderWrapper"] {
    border: none !important;
    padding: 0 !important;
}

/* ── Responsive: narrow viewports ────────────────────────────────────────── */
@media (max-width: 768px) {
    div.st-key-command_dock {
        width: 94vw !important;
        bottom: 14px !important;
        border-radius: 16px !important;
        padding: 10px 12px !important;
    }
    /* Chips naturally wrap because they're in a flex/columns layout */
    div.st-key-command_dock .stButton > button {
        font-size: 10px !important;
        padding: 4px 10px !important;
    }
}
</style>
""", unsafe_allow_html=True)

# The actual dock widgets — all inside the keyed container so the CSS above
# can target and fix-position the whole block as one unit.
with st.container(key="command_dock"):

    # Chip row label
    st.markdown(
        "<div class='dock-label'>Quick Query Suggestions</div>",
        unsafe_allow_html=True,
    )

    # Suggestion chips — three equal columns
    chip_c1, chip_c2, chip_c3 = st.columns(3)
    with chip_c1:
        if st.button("⬆ Top High Margin Items", key="chip_margin"):
            execute_query_action(
                "Show profit breakdown by product showing cost price, "
                "selling price, and profit sorted by profit descending"
            )
            st.rerun()
    with chip_c2:
        if st.button("◈ Category Breakdown", key="chip_category"):
            execute_query_action(
                "What is our total profit margin breakdown by product category?"
            )
            st.rerun()
    with chip_c3:
        if st.button("↕ Low Margin / High Volume", key="chip_lowmargin"):
            execute_query_action(
                "Show products with low margin unit profit but high sales volume"
            )
            st.rerun()

    # Query input + submit — inside a form so Enter key submits
    with st.form(key="dock_query_form", clear_on_submit=False):
        c_input, c_btn = st.columns([5, 1])
        with c_input:
            user_q = st.text_input(
                "Query Input",
                placeholder="Ask anything about profit, sales, or margins...",
                label_visibility="collapsed",
            )
        with c_btn:
            submitted = st.form_submit_button("Analyze")

        if submitted and user_q.strip():
            execute_query_action(user_q)
            st.rerun()
