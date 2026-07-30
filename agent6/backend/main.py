import os
import re
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from bson import ObjectId
from dateutil import parser as dateutil_parser
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from groq import Groq

# Load .env from the backend directory regardless of where the process is started
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("agent5.main")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "mongodb://localhost:27017/")
DB_NAME = "profit_analytics"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
GROQ_MODEL = "llama-3.3-70b-versatile"


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    mql_executed: list[dict]
    table_data: list[dict]
    chart_config: dict
    summary: str


# Read-only aggregation stage allow-list — unchanged
ALLOWED_STAGES = {
    "$match", "$unwind", "$lookup", "$group", "$project",
    "$sort", "$limit", "$skip", "$addFields", "$set",
    "$replaceRoot", "$replaceWith",
}

# ISO-8601 detection regex
_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}:\d{2}(\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?)?$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def convert_date_strings(obj):
    """Recursively convert ISO-8601 strings to timezone-aware datetime objects."""
    if isinstance(obj, list):
        return [convert_date_strings(item) for item in obj]
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
    """
    Convert JavaScript-style regex literals that the LLM sometimes emits
    into valid JSON $regex/$options objects that json.loads() can handle.

    Example transformation:
      /audio|accessories/i
      → {"$regex": "audio|accessories", "$options": "i"}

    This must run on the raw string BEFORE json.loads() is called, because
    /pattern/flags is not valid JSON syntax.
    """
    # Matches: /pattern/flags  where flags is optional letters (i, m, s, x ...)
    # Negative lookbehind for : to avoid matching URL protocols like http://
    regex_literal_re = re.compile(r'(?<![:\w])/([^/\n]+)/([gimsuy]*)')

    def replacer(m: re.Match) -> str:
        pattern = m.group(1).replace('"', '\\"')   # escape any quotes in pattern
        flags    = m.group(2)
        if flags:
            return f'{{"$regex": "{pattern}", "$options": "{flags}"}}'
        return f'{{"$regex": "{pattern}"}}'

    return regex_literal_re.sub(replacer, text)


def clean_json_response(response_text: str) -> str:
    """Strip markdown fences and surrounding prose from LLM output.
    Also converts JS-style /regex/flags literals to valid JSON objects."""
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    text = match.group(1).strip() if match else response_text.strip()
    bracket_indices = [i for i in (text.find('{'), text.find('[')) if i != -1]
    if bracket_indices:
        first_bracket = min(bracket_indices)
        last_bracket = max(text.rfind('}'), text.rfind(']'))
        if last_bracket > first_bracket:
            text = text[first_bracket:last_bracket + 1]
    # Convert any JS-style /pattern/flags regex literals to valid JSON objects
    text = convert_regex_literals(text)
    return text


def serialize_bson(obj):
    """Recursively convert BSON types to JSON-serializable Python types."""
    if isinstance(obj, list):
        return [serialize_bson(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: serialize_bson(v) for k, v in obj.items()}
    elif isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# [FEATURE 1] Fetch live product catalog from MongoDB.
# This is injected into the generate_mql prompt so Groq can:
#   - match vague category/product references ("earphones" → "Audio")
#   - use exact cost_price and selling_price values already in the DB
#   - understand what products exist before writing a $match or $lookup
# ---------------------------------------------------------------------------
async def fetch_product_catalog() -> list[dict]:
    """Return all products with name, category, cost_price, selling_price."""
    client = AsyncIOMotorClient(DATABASE_URL)
    db = client[DB_NAME]
    try:
        cursor = db.products.find(
            {},
            {"_id": 1, "name": 1, "category": 1, "cost_price": 1, "selling_price": 1}
        )
        docs = await cursor.to_list(length=200)
        return serialize_bson(docs)
    finally:
        client.close()


def build_catalog_block(products: list[dict]) -> str:
    """
    Build a compact plain-text product catalog block for the prompt.
    Includes category grouping so the LLM can map fuzzy user terms
    (e.g. "headphones" → Audio, "chair" → Furniture) to exact DB values.
    """
    if not products:
        return "No product data available."

    # Group by category for easy visual scanning by the LLM
    by_category: dict[str, list] = {}
    for p in products:
        cat = p.get("category", "Unknown")
        by_category.setdefault(cat, []).append(p)

    lines = ["LIVE PRODUCT CATALOG (sourced directly from MongoDB):"]
    for cat, items in sorted(by_category.items()):
        lines.append(f"\n  Category: {cat}")
        for item in items:
            lines.append(
                f"    - {item['name']} | "
                f"cost_price=₹{item['cost_price']:.2f} | "
                f"selling_price=₹{item['selling_price']:.2f} | "
                f"_id={item['_id']}"
            )
    lines.append(
        "\nCategory-matching rule: if the user's query mentions a product or category "
        "loosely (e.g. 'earphones', 'keyboard', 'office', 'chargers'), map it to the "
        "closest matching category or product name from the catalog above and use that "
        "exact value in any $match stage."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MQL generation
# ---------------------------------------------------------------------------

def generate_mql(query: str, catalog_block: str) -> list[dict]:
    """
    Pass 1 — Convert a natural language query to a MongoDB aggregation pipeline.
    The live product catalog is injected so the LLM can resolve fuzzy references.
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY is not configured.")

    prompt = f"""You are an expert MongoDB aggregation pipeline engineer.

{catalog_block}

Database schemas:
  sales_invoices: _id (string), timestamp (native MongoDB Date),
    customer_gstin (string|null), taxable_value (float), total_amount (float),
    line_items: array of {{ product_id (→ products._id), quantity (int), unit_margin (float) }}

  products: _id (string), name (string), category (string),
    cost_price (float), selling_price (float), hsn_code (string), tax_rate (float)

Relationship: sales_invoices.line_items[].product_id references products._id.
Any query needing product name, category, cost_price, or selling_price MUST use:
  1. {{ "$unwind": "$line_items" }}
  2. {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id", "foreignField": "_id", "as": "product_details" }} }}
  3. {{ "$unwind": "$product_details" }}
  then $group / $project using "$product_details.<field>"

Date rule: timestamp is a native MongoDB Date. Output date values as ISO 8601 strings
  like "2026-07-25T00:00:00Z" — they will be converted to BSON Date before execution.
  Never use $dateFromString or $toDate.

Filtering rule: when the user mentions a product or category loosely, look up the
  EXACT name/category string from the catalog above and use it with $match + $in.
  NEVER use JavaScript regex literals like /pattern/i — they are not valid JSON.
  If you need case-insensitive matching use: {{"$regex": "pattern", "$options": "i"}}
  But prefer exact $in matches using the catalog values whenever possible.

Output field naming:
  product_name, category, cost_price, selling_price, units_sold,
  profit / total_profit  (= quantity × (selling_price − cost_price)),
  total_revenue          (= quantity × selling_price)
  Sort by primary metric descending.

=== FEW-SHOT EXAMPLES ===

Q: "profit by product"
[
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id", "foreignField": "_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details._id",
      "product_name": {{ "$first": "$product_details.name" }},
      "cost_price":   {{ "$first": "$product_details.cost_price" }},
      "selling_price":{{ "$first": "$product_details.selling_price" }},
      "units_sold":   {{ "$sum": "$line_items.quantity" }},
      "profit": {{ "$sum": {{ "$multiply": ["$line_items.quantity", {{ "$subtract": ["$product_details.selling_price", "$product_details.cost_price"] }}] }} }}
  }} }},
  {{ "$sort": {{ "profit": -1 }} }}
]

Q: "revenue and profit by category"
[
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id", "foreignField": "_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details.category",
      "category":      {{ "$first": "$product_details.category" }},
      "total_revenue": {{ "$sum": {{ "$multiply": ["$line_items.quantity", "$product_details.selling_price"] }} }},
      "total_profit":  {{ "$sum": {{ "$multiply": ["$line_items.quantity", {{ "$subtract": ["$product_details.selling_price", "$product_details.cost_price"] }}] }} }}
  }} }},
  {{ "$sort": {{ "total_profit": -1 }} }}
]

Q: "sales after 2026-07-25"
[
  {{ "$match": {{ "timestamp": {{ "$gt": "2026-07-25T00:00:00Z" }} }} }},
  {{ "$unwind": "$line_items" }},
  {{ "$lookup": {{ "from": "products", "localField": "line_items.product_id", "foreignField": "_id", "as": "product_details" }} }},
  {{ "$unwind": "$product_details" }},
  {{ "$group": {{
      "_id": "$product_details._id",
      "product_name": {{ "$first": "$product_details.name" }},
      "units_sold":   {{ "$sum": "$line_items.quantity" }},
      "profit": {{ "$sum": {{ "$multiply": ["$line_items.quantity", {{ "$subtract": ["$product_details.selling_price", "$product_details.cost_price"] }}] }} }}
  }} }},
  {{ "$sort": {{ "profit": -1 }} }}
]

=== END EXAMPLES ===

User Query: "{query}"

Output ONLY a valid JSON array — no explanation, no markdown, no extra text."""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw_text = response.choices[0].message.content
    logger.debug("generate_mql raw output:\n%s", raw_text)

    cleaned = clean_json_response(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse MQL from LLM: {e}\nRaw: {raw_text}")


async def execute_mql(pipeline: list[dict]) -> list[dict]:
    """Execute the pipeline with read-only stage enforcement."""
    for stage in pipeline:
        stage_keys = list(stage.keys())
        if not stage_keys:
            continue
        if stage_keys[0] not in ALLOWED_STAGES:
            raise ValueError(f"Disallowed stage: {stage_keys[0]}")

    client = AsyncIOMotorClient(DATABASE_URL)
    db = client[DB_NAME]
    try:
        cursor = db.sales_invoices.aggregate(pipeline)
        result = await cursor.to_list(length=100)
        return serialize_bson(result)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# [FEATURE 2] Insights generation — AI now selects the chart type from an
# expanded set that maps to Seaborn/Matplotlib styles:
#   bar, barh, line, pie, scatter, heatmap, box
# The choice is driven by the query intent and data shape.
# ---------------------------------------------------------------------------

def generate_insights(query: str, data: list[dict]) -> tuple[str, dict]:
    """
    Pass 2 — Generate an AI summary and chart_config.
    chart_config.type is one of: bar | barh | line | pie | scatter | heatmap | box
    The LLM picks the best type based on the query and data shape.
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY is not configured.")

    prompt = f"""You are a BI insights generator and data visualization expert.

Given the user's query and the MongoDB result data, produce:
1. A concise 1-2 sentence analytical summary of the key finding.
2. A chart_config object choosing the BEST chart type for the data.

Chart type selection rules:
  - "bar"     → comparing discrete categories by a single metric (most common)
  - "barh"    → same as bar but horizontal; use when category names are long
  - "line"    → trends over time or ordered sequences
  - "pie"     → part-of-whole composition with ≤6 categories
  - "scatter" → relationship between two numeric variables (e.g. margin vs volume)
  - "heatmap" → correlation matrix or cross-tab of two categorical dimensions
  - "box"     → distribution / spread of a numeric variable across categories

x_axis and y_axis must be exact field names from the result data.
For pie charts, use "names" instead of x_axis and "values" instead of y_axis.
For scatter, x_axis = first numeric field, y_axis = second numeric field.
For heatmap/box, set x_axis to the category field and y_axis to the value field.

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

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw_text = response.choices[0].message.content
    logger.debug("generate_insights raw output:\n%s", raw_text)

    cleaned = clean_json_response(raw_text)
    try:
        parsed = json.loads(cleaned)
        return parsed.get("summary", ""), parsed.get("chart_config", {})
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse insights: {e}\nRaw: {raw_text}")


# ---------------------------------------------------------------------------
# Route — signature unchanged
# ---------------------------------------------------------------------------

@app.post("/api/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    logger.info("Query received: %r", request.query)

    # Fetch live product catalog for prompt injection
    try:
        products = await fetch_product_catalog()
        catalog_block = build_catalog_block(products)
        logger.debug("Catalog injected:\n%s", catalog_block)
    except Exception as e:
        logger.warning("Could not fetch product catalog: %s", e)
        catalog_block = "Product catalog unavailable — proceed without it."

    # Pass 1 — Generate MQL
    try:
        pipeline = generate_mql(request.query, catalog_block)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error generating MQL: {e}")

    # Convert ISO date strings to datetime objects
    pipeline = convert_date_strings(pipeline)
    logger.debug("Pipeline:\n%s", json.dumps(pipeline, default=str, indent=2))

    # Execute against MongoDB
    try:
        table_data = await execute_mql(pipeline)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database execution error: {e}")

    logger.info("Rows returned: %d", len(table_data))

    # Empty result — not an error
    if not table_data:
        serializable_pipeline = json.loads(json.dumps(pipeline, default=str))
        return QueryResponse(
            mql_executed=serializable_pipeline,
            table_data=[],
            chart_config={},
            summary=(
                "No matching records found. The date range or category may have no "
                "sales in the current dataset — try broader criteria or check the "
                "exact product/category name from the catalog."
            ),
        )

    # Pass 2 — Generate insights + chart type
    try:
        summary, chart_config = generate_insights(request.query, table_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating insights: {e}")

    serializable_pipeline = json.loads(json.dumps(pipeline, default=str))
    return QueryResponse(
        mql_executed=serializable_pipeline,
        table_data=table_data,
        chart_config=chart_config,
        summary=summary,
    )
