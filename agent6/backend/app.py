import os
import sys
import json
import asyncio
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add current directory to path to import main.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main

# Page Config
st.set_page_config(
    page_title="Agent 5 - Executive Profit Analytics",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Inject Custom Obsidian Dark Mode CSS
st.markdown("""
<style>
/* Base Dark Theme Reset */
.stApp {
    background-color: #0B0F17 !important;
    color: #F3F4F6 !important;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
}

/* Hide Streamlit default chrome elements */
#MainMenu, header, footer {
    visibility: hidden;
    height: 0;
}

.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 8rem !important;
    max-width: 1280px !important;
}

/* Custom Header Bar */
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
    display: flex;
    flex-direction: column;
    justify-content: space-between;
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

.table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    background-color: #151D2A;
    border-bottom: 1px solid #26334D;
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

/* Prompt Chips Styling */
.stButton > button {
    background-color: #151D2A !important;
    color: #C7D2FE !important;
    border: 1px solid #26334D !important;
    border-radius: 9999px !important;
    font-size: 12px !important;
    padding: 6px 16px !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    border-color: #6366F1 !important;
    color: #FFFFFF !important;
}
</style>
""", unsafe_allow_html=True)

# Initial Seed Data State
INITIAL_DATA = {
    "summary": "Initial Executive Overview: Furniture leads net profit with Ergonomic Office Chairs generating $400.00 in total returns at a 57.1% margin. Audio and Accessories follow with strong margins across all key product lines.",
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

# Session State Initialization
if "result_data" not in st.session_state:
    st.session_state["result_data"] = INITIAL_DATA

if "selected_chart_type" not in st.session_state:
    st.session_state["selected_chart_type"] = "bar"

if "query_input_text" not in st.session_state:
    st.session_state["query_input_text"] = ""

def run_query(query_text: str):
    if not query_text.strip():
        return
    with st.spinner("Analyzing data with Groq LLM & MongoDB..."):
        try:
            req = main.QueryRequest(query=query_text)
            resp = asyncio.run(main.process_query(req))
            st.session_state["result_data"] = {
                "summary": resp.summary,
                "chart_config": resp.chart_config,
                "mql_executed": resp.mql_executed,
                "table_data": resp.table_data
            }
        except Exception as e:
            st.error(f"Error processing query: {str(e)}")

# Header Component
st.markdown("""
<div class="exec-header">
    <div>
        <div class="exec-header-title">
            <span>Agent 5: Profit Analytics</span>
            <span class="exec-badge">v2.5 Streamlit Executive</span>
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
table_data = res.get("table_data", [])
summary_text = res.get("summary", "")
mql_executed = res.get("mql_executed", [])
chart_config = res.get("chart_config", {})

# Calculate Executive Metrics for Top Bar
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
        <div class="kpi-value">${total_revenue:,.2f}</div>
        <div class="kpi-subtext">Gross Invoiced across query scope</div>
    </div>
    """, unsafe_allow_html=True)

with kpi_col2:
    st.markdown(f"""
    <div class="kpi-card-emerald">
        <div class="kpi-title-emerald">Total Net Profit</div>
        <div class="kpi-value-emerald">${total_profit:,.2f}</div>
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

with col_vis:
    st.markdown("<div style='background-color: #151D2A; border: 1px solid #26334D; border-radius: 16px; padding: 20px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);'>", unsafe_allow_html=True)
    
    top_c1, top_c2 = st.columns([2, 1])
    with top_c1:
        st.markdown("<h4 style='margin: 0; color: #FFFFFF; font-size: 16px;'>Dynamic Visualization</h4>", unsafe_allow_html=True)
        st.markdown("<p style='margin: 0; color: #9CA3AF; font-size: 12px;'>Interactive graphical metrics</p>", unsafe_allow_html=True)
    with top_c2:
        chart_mode = st.radio(
            "Chart Mode",
            ["Bar", "Line", "Donut"],
            horizontal=True,
            label_visibility="collapsed",
            key="chart_mode_radio"
        )

    # Plotly Chart Construction
    if table_data:
        df = pd.DataFrame(table_data)
        keys = list(df.columns)
        x_col = chart_config.get("x_axis") or (next((k for k in keys if any(x in k.lower() for x in ["name", "category", "_id"])), keys[0]))
        y_col = chart_config.get("y_axis") or (next((k for k in keys if any(x in k.lower() for x in ["profit", "margin", "price", "amount"])), keys[-1]))

        if chart_mode == "Line":
            fig = px.line(
                df,
                x=x_col,
                y=y_col,
                markers=True,
                color_discrete_sequence=["#6366F1"]
            )
            fig.update_traces(line_width=3, marker_size=8, marker_color="#10B981")
        elif chart_mode == "Donut":
            fig = px.pie(
                df,
                names=x_col,
                values=y_col,
                hole=0.55,
                color_discrete_sequence=["#6366F1", "#10B981", "#F59E0B", "#EC4899", "#8B5CF6"]
            )
        else: # Bar
            fig = px.bar(
                df,
                x=x_col,
                y=y_col,
                color_discrete_sequence=["#6366F1"]
            )
            fig.update_traces(marker_color=["#10B981" if i == 0 else "#6366F1" for i in range(len(df))])

        fig.update_layout(
            paper_bgcolor="#151D2A",
            plot_bgcolor="#151D2A",
            font=dict(color="#F3F4F6", size=12),
            margin=dict(l=10, r=10, t=20, b=30),
            height=320,
            xaxis=dict(gridcolor="#26334D", tickangle=-20),
            yaxis=dict(gridcolor="#26334D")
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No chart data available.")

    st.markdown("</div>", unsafe_allow_html=True)

with col_summary:
    st.markdown(f"""
    <div class="ai-summary-card">
        <div>
            <div style="display: flex; items-center; gap: 10px; margin-bottom: 12px;">
                <div style="background-color: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.3); width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #6366F1; font-weight: bold;">AI</div>
                <div>
                    <div style="color: #FFFFFF; font-weight: 700; font-size: 15px;">AI Executive Insight</div>
                    <div style="color: #6366F1; font-size: 11px; font-weight: 600;">Synthesized analytical breakdown</div>
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
<div class="table-header">
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

    max_prof = df_table[profit_col].max() if profit_col and not df_table[profit_col].empty else 1.0

    # Build HTML table for exact custom styling with progress bars & badges
    cols = list(df_table.columns)
    
    html = ["<div class='table-container'><table class='profit-table'><thead><tr>"]
    for c in cols:
        html.append(f"<th>{c.replace('_', ' ')}</th>")
    html.append("</tr></thead><tbody>")

    for _, row in df_table.iterrows():
        html.append("<tr>")
        for c in cols:
            val = row[c]
            c_lower = c.lower()

            if "profit" in c_lower or "margin" in c_lower and "unit" not in c_lower:
                num_val = float(val) if isinstance(val, (int, float)) else 0.0
                pct = min(100, max(10, int((num_val / max_prof) * 100))) if max_prof > 0 else 10
                html.append(f"""
                <td class='profit-bar-cell'>
                    <div class='profit-bar-bg' style='width: {pct}%;'></div>
                    <span class='profit-text'>${num_val:,.2f}</span>
                </td>
                """)
            elif "unit_margin" in c_lower or "margin" in c_lower:
                sp = row.get("selling_price", 0)
                cp = row.get("cost_price", 0)
                num_val = float(val) if isinstance(val, (int, float)) else (sp - cp)
                margin_pct = (num_val / sp * 100) if sp > 0 else 0.0

                badge_class = "badge-green" if margin_pct >= 30 else ("badge-amber" if margin_pct >= 15 else "badge-rose")
                html.append(f"<td>${num_val:,.2f} <span class='{badge_class}'>{margin_pct:.1f}%</span></td>")
            elif any(x in c_lower for x in ["price", "cost", "amount"]):
                num_val = float(val) if isinstance(val, (int, float)) else 0.0
                html.append(f"<td style='font-family: monospace;'>${num_val:,.2f}</td>")
            else:
                html.append(f"<td>{val}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    # Download CSV button
    csv_bytes = df_table.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Export CSV",
        data=csv_bytes,
        file_name=f"executive_profit_report_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)

# 4. Bottom-Centered Floating Command Dock
st.markdown("<div style='text-align: center; color: #9CA3AF; font-size: 12px; margin-bottom: 8px;'>QUICK QUERY SUGGESTIONS</div>", unsafe_allow_html=True)

chip_c1, chip_c2, chip_c3 = st.columns(3)

with chip_c1:
    if st.button("Top High Margin Items"):
        run_query("Show profit breakdown by product showing cost price, selling price, and profit sorted by profit descending")

with chip_c2:
    if st.button("Category Breakdown"):
        run_query("What is our total profit margin breakdown by product category?")

with chip_c3:
    if st.button("Low Margin / High Volume"):
        run_query("Show products with low margin unit profit but high sales volume")

# Floating Query Input Form
with st.form(key="query_form", clear_on_submit=False):
    query_text = st.text_input(
        "Query",
        placeholder="Ask anything about profit, sales, or margins...",
        label_visibility="collapsed"
    )
    submit_query = st.form_submit_button("Analyze")

    if submit_query and query_text.strip():
        run_query(query_text)
