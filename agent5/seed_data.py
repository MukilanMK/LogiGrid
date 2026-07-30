"""
seed_data.py
Populate MongoDB with sample suppliers, products, invoices, line items,
purchase orders, and a handful of historical feedback entries.

Run once:
    python seed_data.py

Re-running is safe — existing documents are replaced via upsert.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient, ReplaceOne
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGO_DB",  "agent3_vendor_quality")


def utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# ─── seed data ────────────────────────────────────────────────────────────────

SUPPLIERS = [
    {
        "supplier_id":    "SUP-001",
        "supplier_name":  "Apex Electronics Ltd.",
        "gstin":          "27AAPCA1234C1Z5",
        "contact_email":  "procurement@apex-elec.com",
        "trust_score":    85.0,
        "compliance_flag": False,
    },
    {
        "supplier_id":    "SUP-002",
        "supplier_name":  "BrightGear Components",
        "gstin":          "29BBBPB5678D2Z1",
        "contact_email":  "quality@brightgear.in",
        "trust_score":    72.0,
        "compliance_flag": False,
    },
    {
        "supplier_id":    "SUP-003",
        "supplier_name":  "CoreTech Supplies Pvt Ltd",
        "gstin":          "07CCCCB9012E3Z4",
        "contact_email":  "orders@coretech.co.in",
        "trust_score":    55.0,
        "compliance_flag": False,
    },
    {
        "supplier_id":    "SUP-004",
        "supplier_name":  "Delta Hardware House",
        "gstin":          "19DDDDC3456F4Z9",
        "contact_email":  "sales@deltahardware.com",
        "trust_score":    28.0,
        "compliance_flag": True,   # below threshold (30)
    },
    {
        "supplier_id":    "SUP-005",
        "supplier_name":  "EcoPackage Solutions",
        "gstin":          "33EEEEE7890G5Z2",
        "contact_email":  "info@ecopackage.in",
        "trust_score":    95.0,
        "compliance_flag": False,
    },
]

PRODUCTS = [
    {"product_id": "PROD-001", "name": "Industrial LED Bulb 20W",   "category": "Lighting"},
    {"product_id": "PROD-002", "name": "HDMI Cable 2m",             "category": "Cables"},
    {"product_id": "PROD-003", "name": "Circuit Breaker 32A",       "category": "Electrical"},
    {"product_id": "PROD-004", "name": "Steel Bolt M10 x 50mm",     "category": "Fasteners"},
    {"product_id": "PROD-005", "name": "Corrugated Shipping Box L", "category": "Packaging"},
    {"product_id": "PROD-006", "name": "Thermal Paste 10g",         "category": "Consumables"},
]

SALES_INVOICES = [
    {"invoice_id": "INV-2026-001", "timestamp": utc(2026, 1, 10), "customer_gstin": "06AAAAA1111A1Z1"},
    {"invoice_id": "INV-2026-002", "timestamp": utc(2026, 2, 14), "customer_gstin": "27BBBBB2222B2Z2"},
    {"invoice_id": "INV-2026-003", "timestamp": utc(2026, 3, 5),  "customer_gstin": "29CCCCC3333C3Z3"},
    {"invoice_id": "INV-2026-004", "timestamp": utc(2026, 4, 20), "customer_gstin": "07DDDDD4444D4Z4"},
    {"invoice_id": "INV-2026-005", "timestamp": utc(2026, 5, 18), "customer_gstin": "19EEEEE5555E5Z5"},
    {"invoice_id": "INV-2026-006", "timestamp": utc(2026, 6, 1),  "customer_gstin": "33FFFFF6666F6Z6"},
]

SALES_LINE_ITEMS = [
    {"line_item_id": "LI-001", "invoice_id": "INV-2026-001", "product_id": "PROD-001", "quantity": 50},
    {"line_item_id": "LI-002", "invoice_id": "INV-2026-001", "product_id": "PROD-002", "quantity": 10},
    {"line_item_id": "LI-003", "invoice_id": "INV-2026-002", "product_id": "PROD-003", "quantity": 5},
    {"line_item_id": "LI-004", "invoice_id": "INV-2026-002", "product_id": "PROD-004", "quantity": 200},
    {"line_item_id": "LI-005", "invoice_id": "INV-2026-003", "product_id": "PROD-001", "quantity": 30},
    {"line_item_id": "LI-006", "invoice_id": "INV-2026-003", "product_id": "PROD-005", "quantity": 100},
    {"line_item_id": "LI-007", "invoice_id": "INV-2026-004", "product_id": "PROD-002", "quantity": 20},
    {"line_item_id": "LI-008", "invoice_id": "INV-2026-004", "product_id": "PROD-006", "quantity": 15},
    {"line_item_id": "LI-009", "invoice_id": "INV-2026-005", "product_id": "PROD-003", "quantity": 8},
    {"line_item_id": "LI-010", "invoice_id": "INV-2026-005", "product_id": "PROD-004", "quantity": 500},
    {"line_item_id": "LI-011", "invoice_id": "INV-2026-006", "product_id": "PROD-005", "quantity": 60},
    {"line_item_id": "LI-012", "invoice_id": "INV-2026-006", "product_id": "PROD-006", "quantity": 25},
]

PURCHASE_ORDERS = [
    # PROD-001 (LEDs) → SUP-001
    {"po_id": "PO-001", "supplier_id": "SUP-001", "product_id": "PROD-001",
     "order_date": utc(2025, 12, 1), "rfq_status": "FULFILLED"},
    {"po_id": "PO-002", "supplier_id": "SUP-001", "product_id": "PROD-001",
     "order_date": utc(2026, 2, 20), "rfq_status": "FULFILLED"},

    # PROD-002 (HDMI Cables) → SUP-002
    {"po_id": "PO-003", "supplier_id": "SUP-002", "product_id": "PROD-002",
     "order_date": utc(2025, 11, 15), "rfq_status": "FULFILLED"},
    {"po_id": "PO-004", "supplier_id": "SUP-002", "product_id": "PROD-002",
     "order_date": utc(2026, 3, 10), "rfq_status": "FULFILLED"},

    # PROD-003 (Circuit Breakers) → SUP-003
    {"po_id": "PO-005", "supplier_id": "SUP-003", "product_id": "PROD-003",
     "order_date": utc(2026, 1, 5), "rfq_status": "FULFILLED"},

    # PROD-004 (Steel Bolts) → SUP-004
    {"po_id": "PO-006", "supplier_id": "SUP-004", "product_id": "PROD-004",
     "order_date": utc(2025, 12, 20), "rfq_status": "FULFILLED"},

    # PROD-005 (Boxes) → SUP-005
    {"po_id": "PO-007", "supplier_id": "SUP-005", "product_id": "PROD-005",
     "order_date": utc(2026, 2, 1), "rfq_status": "FULFILLED"},

    # PROD-006 (Thermal Paste) → SUP-003
    {"po_id": "PO-008", "supplier_id": "SUP-003", "product_id": "PROD-006",
     "order_date": utc(2026, 1, 18), "rfq_status": "OPEN"},
]

SUPPLIER_FEEDBACK = [
    # SUP-001 — one positive, one manufacturing defect
    {
        "feedback_id":       "FB-001",
        "source_type":       "SELLER",
        "supplier_id":       "SUP-001",
        "invoice_id":        None,
        "product_id":        "PROD-001",
        "raw_feedback":      "Excellent batch quality, all LEDs passed QC without any returns.",
        "additional_details": "",
        "ai_category":       "POSITIVE",
        "ai_severity":       "NONE",
        "score_delta":       -2.4,   # +2 × 1.2 seller weight = gain
        "created_at":        utc(2026, 1, 15),
    },
    {
        "feedback_id":       "FB-002",
        "source_type":       "CUSTOMER",
        "supplier_id":       "SUP-001",
        "invoice_id":        "INV-2026-001",
        "product_id":        "PROD-001",
        "raw_feedback":      "Three LED bulbs stopped working within a week of installation.",
        "additional_details": "Used as per spec, no voltage issues in our facility.",
        "ai_category":       "MFG_DEFECT",
        "ai_severity":       "MEDIUM",
        "score_delta":       5.0,
        "created_at":        utc(2026, 2, 3),
    },

    # SUP-002 — logistics damage, customer feedback
    {
        "feedback_id":       "FB-003",
        "source_type":       "CUSTOMER",
        "supplier_id":       "SUP-002",
        "invoice_id":        "INV-2026-002",
        "product_id":        "PROD-002",
        "raw_feedback":      "HDMI cables arrived in crushed packaging, two cables have bent connectors.",
        "additional_details": "Outer carton had clear impact damage.",
        "ai_category":       "LOGISTICS_DAMAGE",
        "ai_severity":       "MEDIUM",
        "score_delta":       2.0,
        "created_at":        utc(2026, 2, 18),
    },

    # SUP-003 — manufacturing defect high severity
    {
        "feedback_id":       "FB-004",
        "source_type":       "SELLER",
        "supplier_id":       "SUP-003",
        "invoice_id":        None,
        "product_id":        "PROD-003",
        "raw_feedback":      "Circuit breakers are tripping at 20A even though rated for 32A. Serious safety risk.",
        "additional_details": "Tested on calibrated bench. 10/20 units failed.",
        "ai_category":       "MFG_DEFECT",
        "ai_severity":       "HIGH",
        "score_delta":       9.6,   # 8 × 1.2
        "created_at":        utc(2026, 3, 10),
    },

    # SUP-004 — user error, no penalty
    {
        "feedback_id":       "FB-005",
        "source_type":       "CUSTOMER",
        "supplier_id":       "SUP-004",
        "invoice_id":        "INV-2026-002",
        "product_id":        "PROD-004",
        "raw_feedback":      "The bolts don't fit our machine. I think we ordered the wrong thread pitch.",
        "additional_details": "Customer confirmed they selected M10 but needed M12.",
        "ai_category":       "USER_ERROR",
        "ai_severity":       "LOW",
        "score_delta":       0.0,
        "created_at":        utc(2026, 3, 22),
    },

    # SUP-005 — two positives
    {
        "feedback_id":       "FB-006",
        "source_type":       "SELLER",
        "supplier_id":       "SUP-005",
        "invoice_id":        None,
        "product_id":        "PROD-005",
        "raw_feedback":      "Packaging quality is outstanding. Zero damage complaints from customers.",
        "additional_details": "",
        "ai_category":       "POSITIVE",
        "ai_severity":       "NONE",
        "score_delta":       -2.4,
        "created_at":        utc(2026, 4, 5),
    },
]


# ─── upsert helper ────────────────────────────────────────────────────────────

def upsert_collection(db, collection_name: str, docs: list[dict], key_field: str) -> int:
    """Bulk-upsert documents keyed by key_field. Returns count of operations."""
    if not docs:
        return 0
    ops = [
        ReplaceOne({key_field: doc[key_field]}, doc, upsert=True)
        for doc in docs
    ]
    result = db[collection_name].bulk_write(ops)
    return result.upserted_count + result.modified_count


# ─── main ─────────────────────────────────────────────────────────────────────

def seed(verbose: bool = True) -> None:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

    try:
        client.admin.command("ping")
    except Exception as exc:
        print(f"[seed] Cannot connect to MongoDB at {MONGO_URI}: {exc}")
        sys.exit(1)

    db = client[DB_NAME]

    datasets = [
        ("suppliers",        SUPPLIERS,        "supplier_id"),
        ("products",         PRODUCTS,         "product_id"),
        ("sales_invoices",   SALES_INVOICES,   "invoice_id"),
        ("sales_line_items", SALES_LINE_ITEMS, "line_item_id"),
        ("purchase_orders",  PURCHASE_ORDERS,  "po_id"),
        ("supplier_feedback",SUPPLIER_FEEDBACK,"feedback_id"),
    ]

    for collection_name, docs, key in datasets:
        count = upsert_collection(db, collection_name, docs, key)
        if verbose:
            print(f"  [{collection_name}] upserted/modified {count} of {len(docs)} documents")

    if verbose:
        print(f"\nSeed complete — database: '{DB_NAME}' on {MONGO_URI}")


if __name__ == "__main__":
    print(f"Seeding '{DB_NAME}' on {MONGO_URI} …\n")
    seed()
