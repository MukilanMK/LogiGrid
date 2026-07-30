"""
db.py
MongoDB connection, collection accessors, and all query/write functions
for Agent 3: Vendor Quality Scoring & Complaint Agent.

Collections:
  - suppliers
  - products
  - sales_invoices
  - sales_line_items
  - purchase_orders
  - supplier_feedback
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from pymongo import MongoClient, DESCENDING, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

# ─── connection ───────────────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGO_DB",  "agent3_vendor_quality")

_client: Optional[MongoClient] = None
_db:     Optional[Database]    = None


def get_db() -> Database:
    """Return a cached MongoDB database handle."""
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _db     = _client[DB_NAME]
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db: Database) -> None:
    """Create indexes on first connection (idempotent)."""
    db.suppliers.create_index("supplier_id", unique=True)
    db.products.create_index("product_id",   unique=True)
    db.sales_invoices.create_index("invoice_id", unique=True)
    db.sales_line_items.create_index("line_item_id", unique=True)
    db.sales_line_items.create_index("invoice_id")
    db.sales_line_items.create_index("product_id")
    db.purchase_orders.create_index("po_id", unique=True)
    db.purchase_orders.create_index([("product_id", ASCENDING), ("order_date", DESCENDING)])
    db.supplier_feedback.create_index("feedback_id", unique=True)
    db.supplier_feedback.create_index("supplier_id")
    db.supplier_feedback.create_index("invoice_id")


# ─── collection helpers ───────────────────────────────────────────────────────

def col(name: str) -> Collection:
    return get_db()[name]


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPLIERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_suppliers() -> list[dict]:
    """Return all suppliers sorted by name."""
    return list(col("suppliers").find({}, {"_id": 0}).sort("supplier_name", ASCENDING))


def get_supplier_by_id(supplier_id: str) -> Optional[dict]:
    return col("suppliers").find_one({"supplier_id": supplier_id}, {"_id": 0})


def get_supplier_by_name(supplier_name: str) -> Optional[dict]:
    return col("suppliers").find_one({"supplier_name": supplier_name}, {"_id": 0})


def update_supplier_score(supplier_id: str, new_score: float, compliance_flag: bool) -> None:
    """Overwrite trust_score and compliance_flag for a supplier."""
    col("suppliers").update_one(
        {"supplier_id": supplier_id},
        {"$set": {"trust_score": round(new_score, 4), "compliance_flag": compliance_flag}},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_products() -> list[dict]:
    return list(col("products").find({}, {"_id": 0}).sort("name", ASCENDING))


def get_product_by_id(product_id: str) -> Optional[dict]:
    return col("products").find_one({"product_id": product_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════════════════
# SALES INVOICES
# ═══════════════════════════════════════════════════════════════════════════════

def get_invoice_by_number(invoice_id: str) -> Optional[dict]:
    return col("sales_invoices").find_one({"invoice_id": invoice_id}, {"_id": 0})


def get_all_invoices() -> list[dict]:
    return list(col("sales_invoices").find({}, {"_id": 0}).sort("timestamp", DESCENDING))


# ═══════════════════════════════════════════════════════════════════════════════
# SALES LINE ITEMS
# ═══════════════════════════════════════════════════════════════════════════════

def get_line_items_for_invoice(invoice_id: str) -> list[dict]:
    return list(col("sales_line_items").find({"invoice_id": invoice_id}, {"_id": 0}))


def get_products_for_invoice(invoice_id: str) -> list[str]:
    """Return distinct product_ids on a given invoice."""
    items = get_line_items_for_invoice(invoice_id)
    return list({item["product_id"] for item in items})


# ═══════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_supplier_from_invoice(invoice_id: str) -> Optional[str]:
    """
    Customer-feedback supplier resolution:
      invoice_id → sales_line_items → product_ids
               → most recent PO (order_date <= invoice.timestamp)
               → supplier_id

    Returns the first resolvable supplier_id, or None.
    """
    invoice = get_invoice_by_number(invoice_id)
    if not invoice:
        return None

    invoice_ts = invoice["timestamp"]
    product_ids = get_products_for_invoice(invoice_id)
    if not product_ids:
        return None

    for product_id in product_ids:
        po = col("purchase_orders").find_one(
            {"product_id": product_id, "order_date": {"$lte": invoice_ts}},
            {"_id": 0},
            sort=[("order_date", DESCENDING)],
        )
        if po:
            return po["supplier_id"]

    return None


def get_po_by_product(product_id: str) -> list[dict]:
    return list(col("purchase_orders").find({"product_id": product_id}, {"_id": 0})
                .sort("order_date", DESCENDING))


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPLIER FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════════

def insert_feedback(feedback: dict) -> str:
    """
    Insert a supplier_feedback document.
    Expects all fields except _id; feedback_id must already be set.
    Returns the inserted feedback_id.
    """
    col("supplier_feedback").insert_one({**feedback})
    return feedback["feedback_id"]


def get_feedback_for_supplier(supplier_id: str) -> list[dict]:
    """Return all feedback rows for a supplier, newest first."""
    return list(
        col("supplier_feedback")
        .find({"supplier_id": supplier_id}, {"_id": 0})
        .sort("created_at", DESCENDING)
    )


def get_all_feedback() -> list[dict]:
    return list(col("supplier_feedback").find({}, {"_id": 0}).sort("created_at", DESCENDING))


def feedback_id_exists(feedback_id: str) -> bool:
    return col("supplier_feedback").count_documents({"feedback_id": feedback_id}) > 0


def update_feedback_classification(
    feedback_id: str,
    ai_category: str,
    ai_severity: str,
    score_delta: float,
) -> None:
    """Overwrite the ai_category, ai_severity, and score_delta on an existing feedback row."""
    col("supplier_feedback").update_one(
        {"feedback_id": feedback_id},
        {"$set": {
            "ai_category": ai_category,
            "ai_severity": ai_severity,
            "score_delta":  score_delta,
        }},
    )


def get_all_feedback_ids_for_supplier(supplier_id: str) -> list[dict]:
    """Return minimal projection of all feedback rows for a supplier, oldest first."""
    return list(
        col("supplier_feedback")
        .find(
            {"supplier_id": supplier_id},
            {"_id": 0, "feedback_id": 1, "source_type": 1,
             "raw_feedback": 1, "ai_category": 1, "ai_severity": 1, "score_delta": 1},
        )
        .sort("created_at", ASCENDING)
    )


def recompute_supplier_score_from_feedback(supplier_id: str, seed_score: float = 100.0) -> float:
    """
    Replay all feedback rows for a supplier (oldest first) starting from seed_score
    and return the correct final trust_score.  Does NOT write to DB — caller must persist.
    """
    rows = list(
        col("supplier_feedback")
        .find({"supplier_id": supplier_id}, {"_id": 0, "score_delta": 1})
        .sort("created_at", ASCENDING)
    )
    score = seed_score
    for row in rows:
        delta = row.get("score_delta", 0.0)
        score = max(0.0, min(100.0, score - delta))
    return round(score, 4)


# ═══════════════════════════════════════════════════════════════════════════════
# TRUST SCORE HISTORY  (derived from supplier_feedback for charting)
# ═══════════════════════════════════════════════════════════════════════════════

def get_score_history(supplier_id: str) -> list[dict]:
    """
    Build a running trust-score timeline from feedback rows.
    Returns list of {"created_at": datetime, "trust_score": float}.

    Strategy: rewind from the current live score by subtracting all deltas
    in reverse, then replay forward to get accurate per-event snapshots.
    """
    supplier = get_supplier_by_id(supplier_id)
    if not supplier:
        return []

    rows = list(
        col("supplier_feedback")
        .find({"supplier_id": supplier_id}, {"_id": 0, "created_at": 1, "score_delta": 1})
        .sort("created_at", ASCENDING)
    )

    if not rows:
        return [{"created_at": datetime.now(timezone.utc), "trust_score": supplier["trust_score"]}]

    # Rewind: starting_score = current - sum(all deltas), clamped to [0,100].
    # Note: score_delta is positive for penalties, negative for bonuses.
    # The live score was built by: score = score - delta for each row.
    # So: starting = live_score + sum(deltas), then clamped.
    total_delta = sum(r.get("score_delta", 0.0) for r in rows)
    starting_score = max(0.0, min(100.0, supplier["trust_score"] + total_delta))

    history = []
    running = starting_score
    for row in rows:
        delta   = row.get("score_delta", 0.0)
        running = max(0.0, min(100.0, running - delta))   # apply penalty forward
        history.append({"created_at": row["created_at"], "trust_score": round(running, 4)})

    return history


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════════════════

def generate_id(prefix: str) -> str:
    """Generate a short unique ID with a given prefix."""
    return f"{prefix}-{str(ObjectId())[-6:].upper()}"


def ping() -> bool:
    """Return True if MongoDB is reachable."""
    try:
        get_db().command("ping")
        return True
    except Exception:
        return False
