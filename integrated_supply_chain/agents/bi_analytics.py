"""
agents/bi_analytics.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 6 — Profit Analytics & Conversational BI Engine

Core logic (preserved from original agent6/backend/main.py):
  • generate_mql()            — NL → MongoDB aggregation pipeline (Pass 1)
  • execute_mql()             — read-only stage enforcement + Motor execution
  • generate_insights()       — AI summary + chart_config selection (Pass 2)
  • fetch_product_catalog()   — live catalog injection for fuzzy matching
  • Seaborn chart renderer     — bar/barh/line/pie/scatter/heatmap/box
  • convert_regex_literals()  — JS-style /pattern/flags → valid JSON
  • convert_date_strings()    — ISO-8601 strings → native datetime

Integration:
  • process_query() wraps the two-pass pipeline and routes BIQueryPayload
    through the Supervisor for system context enrichment.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns
from bson import ObjectId
from dateutil import parser as dateutil_parser
from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from core.db import get_fresh_async_db
from core.llm_client import get_groq_client
from orchestrator.data_contracts import (
    AgentID,
    BIQueryPayload,
    WorkflowStatus,
)

matplotlib.use("Agg")
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

logger = logging.getLogger("agent6.bi")

# ─────────────────────────────────────────────────────────────────────────────
# READ-ONLY STAGE ALLOW-LIST  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_STAGES = {
    "$match", "$unwind", "$lookup", "$group", "$project",
    "$sort", "$limit", "$skip", "$addFields", "$set",
    "$replaceRoot", "$replaceWith",
}

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}:\d{2}(\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?)?$"
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

def convert_date_strings(obj: Any) -> Any:
    if isinstance(obj, list):
        return [convert_date_strings(i) for i in obj]
    if isinstance(obj, dict):
        return {k: convert_date_strings(v) for k, v in obj.items()}
    if isinstance(obj, str) and _ISO_DATE_RE.match(obj):
        try:
            dt = dateutil_parser.parse(obj)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, OverflowError):
            pass
    return obj


def convert_regex_literals(text: str) -> str:
    """Convert JS-style /pattern/flags → {"$regex":..., "$options":...}."""
    regex_literal_re = re.compile(r'(?<![:\w])/([^/\n]+)/([gimsuy]*)')
    def replacer(m: re.Match) -> str:
        pattern = m.group(1).replace('"', '\\"')
        flags   = m.group(2)
        if flags:
            return f'{{"$regex": "{pattern}", "$options": "{flags}"}}'
        return f'{{"$regex": "{pattern}"}}'
    return regex_literal_re.sub(replacer, text)


def clean_json_response(response_text: str) -> str:
    """Strip markdown fences and prose; also converts JS regex literals."""
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    text  = match.group(1).strip() if match else response_text.strip()
    bracket_indices = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if bracket_indices:
        first_bracket = min(bracket_indices)
        last_bracket  = max(text.rfind("}"), text.rfind("]"))
        if last_bracket > first_bracket:
            text = text[first_bracket : last_bracket + 1]
    return convert_regex_literals(text)


def serialize_bson(obj: Any) -> Any:
    if isinstance(obj, list):
        return [serialize_bson(i) for i in obj]
    if isinstance(obj, dict):
        return {k: serialize_bson(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# CATALOG FETCH  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_product_catalog() -> List[Dict[str, Any]]:
    """Fetch product catalog using a fresh Motor client bound to the current loop."""
    client, db = get_fresh_async_db()
    try:
        cursor = db.products.find(
            {}, {"_id": 0, "product_id": 1, "name": 1, "category": 1,
                 "cost_price": 1, "selling_price": 1}
        )
        docs = await cursor.to_list(length=200)
        return serialize_bson(docs)
    finally:
        client.close()


def build_catalog_block(products: List[Dict[str, Any]]) -> str:
    if not products:
        return "No product data available."
    by_category: Dict[str, list] = {}
    for p in products:
        by_category.setdefault(p.get("category", "Unknown"), []).append(p)
    lines = ["LIVE PRODUCT CATALOG (sourced directly from MongoDB):"]
    for cat, items in sorted(by_category.items()):
        lines.append(f"\n  Category: {cat}")
        for item in items:
            lines.append(
                f"    - {item['name']} | "
                f"cost_price=₹{item.get('cost_price', 0):.2f} | "
                f"selling_price=₹{item.get('selling_price', 0):.2f} | "
                f"product_id={item.get('product_id','')}"
            )
    lines.append(
        "\nCategory-matching rule: if the user's query mentions a product or category "
        "loosely, map it to the closest matching category or product name from the catalog "
        "above and use that exact value in any $match stage."
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MQL GENERATION  (preserved from original — full few-shot prompt)
# ─────────────────────────────────────────────────────────────────────────────

def generate_mql(query: str, catalog_block: str) -> List[Dict[str, Any]]:
    client = get_groq_client()
    prompt = f"""You are an expert MongoDB aggregation pipeline engineer.

{catalog_block}

ACTUAL DATABASE SCHEMA (supply_chain_ecosystem):

  sales_invoices collection:
    _id         : ObjectId
    invoice_id  : string  (e.g. "INV-0000")
    timestamp   : ISODate
    total_amount: float
    line_items  : array of {{
        product_id : string  (e.g. "PROD-001")  ← joins to products.product_id
        quantity   : int
        unit_price : float   ← this is the selling price per unit
    }}

  products collection:
    _id          : ObjectId  (DO NOT use for joins)
    product_id   : string    (e.g. "PROD-001")  ← THE join key
    name         : string
    category     : string
    cost_price   : float
    selling_price: float
    hsn_code     : string

CRITICAL JOIN RULE:
  sales_invoices.line_items[].product_id  →  products.product_id
  The $lookup MUST use localField="line_items.product_id" and foreignField="product_id".
  NEVER join on products._id — it is an ObjectId and will NEVER match.

PROFIT CALCULATION:
  profit per line = quantity × (unit_price - cost_price)
  Use "$line_items.unit_price" as the selling price (it IS the price sold at).
  Use "$product_details.cost_price" for the cost.

REQUIRED PIPELINE STRUCTURE for any query needing product details:
  1. {{ "$unwind": "$line_items" }}
  2. {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id",
                      "foreignField": "product_id", "as": "product_details" }} }}
  3. {{ "$unwind": "$product_details" }}
  4. $group / $project using:
       - "$product_details.name"     for product_name
       - "$product_details.category" for category
       - "$product_details.cost_price" for cost_price
       - "$line_items.unit_price"    for selling_price / unit_price
       - "$line_items.quantity"      for quantity
       - profit = quantity × (unit_price − cost_price)

Date rule: timestamp is a native MongoDB Date. Filter dates as ISO 8601 strings
  like "2026-07-01T00:00:00Z" — they will be converted before execution.

Output field names to use: product_name, category, cost_price, selling_price,
  units_sold, profit, total_profit, total_revenue. Sort by primary metric descending.

=== FEW-SHOT EXAMPLES ===

Q: "profit by product"
[
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id",
                  "foreignField": "product_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details.product_id",
      "product_name":  {{ "$first": "$product_details.name" }},
      "category":      {{ "$first": "$product_details.category" }},
      "cost_price":    {{ "$first": "$product_details.cost_price" }},
      "selling_price": {{ "$avg":  "$line_items.unit_price" }},
      "units_sold":    {{ "$sum":  "$line_items.quantity" }},
      "profit": {{ "$sum": {{ "$multiply": [
          "$line_items.quantity",
          {{ "$subtract": ["$line_items.unit_price", "$product_details.cost_price"] }}
      ]}} }}
  }} }},
  {{ "$sort": {{ "profit": -1 }} }}
]

Q: "revenue and profit by category"
[
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id",
                  "foreignField": "product_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details.category",
      "category":      {{ "$first": "$product_details.category" }},
      "total_revenue": {{ "$sum": {{ "$multiply": ["$line_items.quantity", "$line_items.unit_price"] }} }},
      "total_profit":  {{ "$sum": {{ "$multiply": [
          "$line_items.quantity",
          {{ "$subtract": ["$line_items.unit_price", "$product_details.cost_price"] }}
      ]}} }}
  }} }},
  {{ "$sort": {{ "total_profit": -1 }} }}
]

Q: "top 5 products by units sold"
[
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id",
                  "foreignField": "product_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details.product_id",
      "product_name": {{ "$first": "$product_details.name" }},
      "category":     {{ "$first": "$product_details.category" }},
      "units_sold":   {{ "$sum": "$line_items.quantity" }}
  }} }},
  {{ "$sort": {{ "units_sold": -1 }} }},
  {{ "$limit": 5 }}
]

=== END EXAMPLES ===

User Query: "{query}"

Output ONLY a valid JSON array — no explanation, no markdown, no extra text."""

    response = client.chat.completions.create(
        model    = settings.groq_model,
        messages = [{"role": "user", "content": prompt}],
        temperature = 0,
    )
    raw_text = response.choices[0].message.content
    cleaned  = clean_json_response(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse MQL from LLM: {exc}\nRaw: {raw_text}")


async def execute_mql(pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute aggregation with read-only stage enforcement."""
    for stage in pipeline:
        keys = list(stage.keys())
        if keys and keys[0] not in ALLOWED_STAGES:
            raise ValueError(f"Disallowed aggregation stage: {keys[0]}")

    client, db = get_fresh_async_db()
    try:
        cursor = db.sales_invoices.aggregate(pipeline)
        result = await cursor.to_list(length=100)
        return serialize_bson(result)
    finally:
        client.close()


# ─────────────────────────────────────────────────────────────────────────────
# INSIGHTS GENERATION  (preserved from original — expanded chart types)
# ─────────────────────────────────────────────────────────────────────────────

def generate_insights(query: str, data: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Pass 2 — AI summary + chart_config (type: bar|barh|line|pie|scatter|heatmap|box)."""
    client = get_groq_client()
    prompt = f"""You are a BI insights generator and data visualization expert.

Given the user's query and the MongoDB result data, produce:
1. A concise 1-2 sentence analytical summary of the key finding.
2. A chart_config object choosing the BEST chart type for the data.

Chart type selection rules:
  - "bar"     → comparing discrete categories by a single metric
  - "barh"    → same as bar but horizontal; use when category names are long
  - "line"    → trends over time or ordered sequences
  - "pie"     → part-of-whole composition with ≤6 categories
  - "scatter" → relationship between two numeric variables
  - "heatmap" → correlation matrix or cross-tab of two categorical dimensions
  - "box"     → distribution / spread of a numeric variable across categories

x_axis and y_axis must be exact field names from the result data.
For pie charts, use "names" instead of x_axis and "values" instead of y_axis.

User Query: "{query}"
Data Result: {json.dumps(data)}

Output ONLY this exact JSON format (no markdown, no extra text):
{{
  "summary": "...",
  "chart_config": {{
    "type": "bar",
    "x_axis": "field_name",
    "y_axis": "field_name"
  }}
}}"""

    response = client.chat.completions.create(
        model    = settings.groq_model,
        messages = [{"role": "user", "content": prompt}],
        temperature = 0,
    )
    raw_text = response.choices[0].message.content
    cleaned  = clean_json_response(raw_text)
    try:
        parsed = json.loads(cleaned)
        return parsed.get("summary", ""), parsed.get("chart_config", {})
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse insights: {exc}\nRaw: {raw_text}")


# ─────────────────────────────────────────────────────────────────────────────
# SEABORN CHART RENDERER  (preserved from original streamlit_app.py)
# ─────────────────────────────────────────────────────────────────────────────

_OBS_PALETTE = ["#6366F1", "#10B981", "#F59E0B", "#F43F5E", "#8B5CF6", "#EC4899", "#06B6D4"]
_OBS_BG      = "#151D2A"
_OBS_GRID    = "#26334D"
_OBS_TEXT    = "#F3F4F6"
_OBS_SUBTEXT = "#9CA3AF"


def _apply_obsidian_style(ax: Any, fig: Any) -> None:
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


def render_seaborn_chart(
    df: pd.DataFrame,
    chart_config: Dict[str, Any],
) -> Optional[Any]:
    """Render a Seaborn chart. Returns a matplotlib Figure or None."""
    chart_type = chart_config.get("type", "bar").lower()
    x_col = chart_config.get("x_axis") or chart_config.get("names")
    y_col = chart_config.get("y_axis") or chart_config.get("values")

    cols = list(df.columns)
    if not x_col:
        x_col = next((c for c in cols if any(k in c.lower() for k in ["name", "category", "_id"])), cols[0])
    if not y_col:
        y_col = next((c for c in cols if any(k in c.lower() for k in ["profit", "revenue", "margin", "amount", "price"])), cols[-1])

    if y_col in df.columns:
        df[y_col] = pd.to_numeric(df[y_col], errors="coerce").fillna(0)

    sns.set_theme(style="darkgrid", rc={
        "axes.facecolor": _OBS_BG,
        "figure.facecolor": _OBS_BG,
        "grid.color": _OBS_GRID,
        "text.color": _OBS_TEXT,
        "axes.labelcolor": _OBS_SUBTEXT,
        "xtick.color": _OBS_SUBTEXT,
        "ytick.color": _OBS_SUBTEXT,
        "axes.edgecolor": _OBS_GRID,
    })

    try:
        if chart_type in ("bar", "barh"):
            fig, ax = plt.subplots(figsize=(7, 4))
            colors = [_OBS_PALETTE[i % len(_OBS_PALETTE)] for i in range(len(df))]
            colors[0] = "#10B981"
            if chart_type == "bar":
                df["_hue"] = range(len(df))
                sns.barplot(data=df, x=x_col, y=y_col, hue="_hue", palette=colors, ax=ax, legend=False)
                df.drop(columns=["_hue"], inplace=True, errors="ignore")
                ax.set_xticks(range(len(df)))
                ax.set_xticklabels([str(v) for v in df[x_col]], rotation=20, ha="right", fontsize=8)
                for bar in ax.patches:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(df[y_col]) * 0.01,
                        f"₹{bar.get_height():,.0f}",
                        ha="center", va="bottom", fontsize=8, color=_OBS_TEXT,
                    )
            else:
                df["_hue"] = range(len(df))
                sns.barplot(data=df, x=y_col, y=x_col, hue="_hue", palette=colors, ax=ax, orient="h", legend=False)
                df.drop(columns=["_hue"], inplace=True, errors="ignore")
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
                df[vals_col], labels=df[names_col], autopct="%1.1f%%",
                colors=_OBS_PALETTE[:len(df)], startangle=140,
                wedgeprops={"edgecolor": _OBS_BG, "linewidth": 2}, pctdistance=0.82,
            )
            for t in texts:
                t.set_color(_OBS_SUBTEXT); t.set_fontsize(9)
            for at in autotexts:
                at.set_color(_OBS_TEXT); at.set_fontsize(8)
            ax.add_artist(plt.Circle((0, 0), 0.55, fc=_OBS_BG))
            fig.patch.set_facecolor(_OBS_BG)
            plt.tight_layout()

        elif chart_type == "scatter":
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.scatter(df[x_col], df[y_col], c=range(len(df)), cmap="cool",
                       s=120, alpha=0.85, edgecolors=_OBS_GRID, linewidths=0.8)
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        elif chart_type == "heatmap":
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != x_col]
            if not numeric_cols:
                return None
            pivot = df.set_index(x_col)[numeric_cols]
            fig, ax = plt.subplots(figsize=(max(6, len(numeric_cols) * 1.5), max(4, len(df) * 0.6)))
            sns.heatmap(pivot, annot=True, fmt=".0f", linewidths=0.5,
                        cmap=sns.diverging_palette(240, 130, as_cmap=True), ax=ax,
                        linecolor=_OBS_GRID, annot_kws={"size": 9, "color": _OBS_TEXT})
            fig.patch.set_facecolor(_OBS_BG)
            plt.tight_layout()

        elif chart_type == "box":
            fig, ax = plt.subplots(figsize=(7, 4))
            sns.boxplot(data=df, x=x_col, y=y_col, palette=_OBS_PALETTE, ax=ax)
            ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
            _apply_obsidian_style(ax, fig)

        else:
            fig, ax = plt.subplots(figsize=(7, 4))
            colors = [_OBS_PALETTE[i % len(_OBS_PALETTE)] for i in range(len(df))]
            colors[0] = "#10B981"
            df["_hue"] = range(len(df))
            sns.barplot(data=df, x=x_col, y=y_col, hue="_hue", palette=colors, ax=ax, legend=False)
            df.drop(columns=["_hue"], inplace=True, errors="ignore")
            ax.set_xticks(range(len(df)))
            ax.set_xticklabels([str(v) for v in df[x_col]], rotation=20, ha="right", fontsize=8)
            _apply_obsidian_style(ax, fig)

        return fig

    except Exception as exc:
        logger.warning("Chart render failed (%s): %s", chart_type, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ASYNC RUNNER HELPER  (same threading trick from original streamlit_app.py)
# ─────────────────────────────────────────────────────────────────────────────

def _run_coroutine_in_thread(coro: Any) -> Tuple[Any, Optional[Exception]]:
    result_box: List[Any] = [None]
    error_box:  List[Optional[Exception]] = [None]

    def target() -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 6 SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class BIAnalyticsService:
    """Service class registered with the Supervisor."""

    async def _process_query_async(self, query: str) -> Dict[str, Any]:
        try:
            products      = await fetch_product_catalog()
            catalog_block = build_catalog_block(products)
        except Exception as exc:
            logger.warning("Catalog fetch failed: %s", exc)
            catalog_block = "Product catalog unavailable."

        pipeline = generate_mql(query, catalog_block)
        pipeline = convert_date_strings(pipeline)
        table_data = await execute_mql(pipeline)

        serialisable_pipeline = json.loads(json.dumps(pipeline, default=str))

        if not table_data:
            return {
                "mql_executed": serialisable_pipeline,
                "table_data":   [],
                "chart_config": {},
                "summary": (
                    "No matching records found. Try broader criteria or check "
                    "the exact product/category name."
                ),
            }

        summary, chart_config = generate_insights(query, table_data)
        return {
            "mql_executed": serialisable_pipeline,
            "table_data":   table_data,
            "chart_config": chart_config,
            "summary":      summary,
        }

    def process_query(self, query: str, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronous wrapper for the two-pass pipeline.
        Routes BIQueryPayload through Supervisor for enrichment.
        """
        from orchestrator.supervisor import get_supervisor
        import uuid

        wf_id  = workflow_id or f"WF-BI-{uuid.uuid4().hex[:8].upper()}"
        result, err = _run_coroutine_in_thread(self._process_query_async(query))

        if err is not None:
            raise err

        payload = BIQueryPayload(
            workflow_id   = wf_id,
            nl_query      = query,
            mql_pipeline  = result.get("mql_executed", []),
            result_rows   = result.get("table_data", []),
            chart_config  = result.get("chart_config", {}),
            ai_summary    = result.get("summary", ""),
            status        = WorkflowStatus.SUCCESS,
        )

        try:
            enriched = get_supervisor().route(payload)
            result["supervisor_context"] = enriched.metadata.get("supervisor_health", {})
        except Exception as exc:
            logger.warning("Supervisor enrichment failed: %s", exc)

        return result


def register_with_supervisor() -> BIAnalyticsService:
    from orchestrator.supervisor import get_supervisor
    service = BIAnalyticsService()
    get_supervisor().register_agent(AgentID.BI_ANALYTICS, service)
    return service
