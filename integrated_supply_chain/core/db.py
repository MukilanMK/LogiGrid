"""
core/db.py
Singleton MongoDB connection — both synchronous (PyMongo) and asynchronous
(Motor) clients are provided.  All agents and the Supervisor import from here.

Collections in supply_chain_ecosystem:
  products            – product catalogue
  inventory           – stock levels
  suppliers           – supplier master + trust scores
  purchase_orders     – RFQ / PO records
  sales_invoices      – sales / billing records
  quality_complaints  – vendor feedback + AI classification
  auditing            – invoice audit results
  calendar_context    – events driving demand spikes
  system_logs         – Supervisor audit trail  ← NEW
"""

from __future__ import annotations

from typing import Optional

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from core.config import settings

# ─── Synchronous client (PyMongo) ─────────────────────────────────────────────

_sync_client: Optional[MongoClient] = None
_sync_db: Optional[Database] = None


def get_sync_db() -> Database:
    """Return a cached synchronous PyMongo database handle."""
    global _sync_client, _sync_db
    if _sync_db is None:
        _sync_client = MongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=5000,
        )
        _sync_db = _sync_client[settings.db_name]
        _ensure_indexes(_sync_db)
    return _sync_db


def _ensure_indexes(db: Database) -> None:
    """Create all indexes idempotently on first connection."""
    # products
    db.products.create_index("product_id", unique=True)

    # inventory
    db.inventory.create_index("product_id")

    # suppliers
    db.suppliers.create_index("supplier_id", unique=True)
    db.suppliers.create_index("contact_email")
    # categories_supplied is an array; a multikey index covers $in queries
    db.suppliers.create_index("categories_supplied")

    # purchase_orders
    db.purchase_orders.create_index("po_id", unique=True)
    db.purchase_orders.create_index([("product_id", ASCENDING), ("order_date", DESCENDING)])
    db.purchase_orders.create_index("supplier_id")

    # sales_invoices
    db.sales_invoices.create_index("invoice_id", unique=True, sparse=True)
    db.sales_invoices.create_index("timestamp")

    # quality_complaints
    db.quality_complaints.create_index("feedback_id", unique=True)
    db.quality_complaints.create_index("supplier_id")

    # auditing
    db.auditing.create_index("invoice_number", unique=True)

    # calendar_context
    db.calendar_context.create_index("event_name")

    # system_logs — the Supervisor's audit trail
    db.system_logs.create_index("log_id", unique=True)
    db.system_logs.create_index("workflow_id")
    db.system_logs.create_index([("timestamp", DESCENDING)])
    db.system_logs.create_index("source_agent")
    db.system_logs.create_index("target_agent")


# ─── Async client (Motor) ─────────────────────────────────────────────────────
# NOTE: Motor clients bind to the event loop that is running when they are
# first used.  Because bi_analytics.py runs each query in a fresh daemon-thread
# event loop (via _run_coroutine_in_thread), we must NOT cache a Motor client
# at module level — the cached client's loop would be closed after the first
# thread exits, causing "Event loop is closed" on every subsequent call.
#
# Instead, call get_fresh_async_db() inside the async coroutine; it creates a
# new client bound to the current (fresh) loop and closes it when done.

def get_fresh_async_db() -> tuple[AsyncIOMotorClient, AsyncIOMotorDatabase]:
    """
    Create a brand-new Motor client + database handle each time.
    The caller is responsible for calling client.close() when finished.
    Use this inside async coroutines that run in per-query daemon threads.
    """
    client = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
    )
    return client, client[settings.db_name]


# ─── Convenience collection accessors ─────────────────────────────────────────

def col(name: str) -> Collection:
    """Return a synchronous collection from the unified database."""
    return get_sync_db()[name]


# ─── Health check ─────────────────────────────────────────────────────────────

def ping() -> bool:
    """Return True if MongoDB is reachable via the sync client."""
    try:
        get_sync_db().command("ping")
        return True
    except Exception:
        return False
