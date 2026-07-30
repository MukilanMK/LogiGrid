"""
orchestrator/logger.py
System-wide audit logger.

All writes go to the `system_logs` MongoDB collection (unified DB).
The module also configures Python's stdlib logging so every component
sends structured INFO/ERROR lines to stdout automatically.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.db import col
from orchestrator.data_contracts import (
    AgentPayload,
    SystemLogEntry,
    WorkflowStatus,
)

# ─── stdlib logging setup ────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger("supervisor")


# ─── BSON-safe serialiser ─────────────────────────────────────────────────────

def _make_serialisable(obj: Any) -> Any:
    """Recursively convert non-JSON-safe types so the payload can be stored."""
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serialisable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):          # Pydantic model
        return _make_serialisable(obj.model_dump())
    if hasattr(obj, "__str__"):
        try:
            json.dumps(obj)                 # already serialisable
            return obj
        except TypeError:
            return str(obj)
    return str(obj)


# ─── Public API ───────────────────────────────────────────────────────────────

def log_event(
    payload: AgentPayload,
    status: WorkflowStatus,
    error: Optional[str] = None,
) -> SystemLogEntry:
    """
    Persist one audit record to `system_logs` and emit a structured
    stdlib log line.  Returns the SystemLogEntry for caller inspection.

    Called by the Supervisor on every payload it receives and routes.
    """
    entry = SystemLogEntry(
        workflow_id  = payload.workflow_id,
        source_agent = payload.source_agent.value,
        target_agent = payload.target_agent.value,
        payload_type = type(payload).__name__,
        payload      = _make_serialisable(payload.model_dump()),
        status       = status,
        error        = error,
    )

    doc = entry.model_dump()
    doc["timestamp"] = datetime.now(timezone.utc)   # native BSON Date

    try:
        col("system_logs").insert_one(doc)
    except Exception as exc:
        # Never let a logging failure crash the pipeline
        logger.error("system_logs insert failed: %s", exc)

    level = logging.ERROR if error else logging.INFO
    logger.log(
        level,
        "[%s] %s → %s | workflow=%s | status=%s%s",
        entry.payload_type,
        entry.source_agent,
        entry.target_agent,
        entry.workflow_id,
        status.value,
        f" | error={error}" if error else "",
    )

    return entry


def log_raw(
    workflow_id:  str,
    source_agent: str,
    target_agent: str,
    payload_type: str,
    payload:      Dict[str, Any],
    status:       WorkflowStatus,
    error:        Optional[str] = None,
) -> SystemLogEntry:
    """
    Lower-level variant for cases where a full AgentPayload object is not
    available (e.g. internal Supervisor state transitions).
    """
    entry = SystemLogEntry(
        workflow_id  = workflow_id,
        source_agent = source_agent,
        target_agent = target_agent,
        payload_type = payload_type,
        payload      = _make_serialisable(payload),
        status       = status,
        error        = error,
    )

    doc = entry.model_dump()
    doc["timestamp"] = datetime.now(timezone.utc)

    try:
        col("system_logs").insert_one(doc)
    except Exception as exc:
        logger.error("system_logs insert failed: %s", exc)

    level = logging.ERROR if error else logging.INFO
    logger.log(
        level,
        "[%s] %s → %s | workflow=%s | status=%s%s",
        payload_type,
        source_agent,
        target_agent,
        workflow_id,
        status.value,
        f" | error={error}" if error else "",
    )

    return entry


def get_recent_logs(limit: int = 100) -> list[Dict[str, Any]]:
    """
    Fetch the most recent system_log entries (newest first).
    Returns plain dicts with ObjectId/_id stripped.
    """
    try:
        docs = list(
            col("system_logs")
            .find({}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        # Convert datetime back to ISO string for JSON serialisation
        for doc in docs:
            if isinstance(doc.get("timestamp"), datetime):
                doc["timestamp"] = doc["timestamp"].isoformat()
        return docs
    except Exception as exc:
        logger.error("get_recent_logs failed: %s", exc)
        return []


def get_logs_for_workflow(workflow_id: str) -> list[Dict[str, Any]]:
    """Return all log entries for a specific workflow run, oldest first."""
    try:
        docs = list(
            col("system_logs")
            .find({"workflow_id": workflow_id}, {"_id": 0})
            .sort("timestamp", 1)
        )
        for doc in docs:
            if isinstance(doc.get("timestamp"), datetime):
                doc["timestamp"] = doc["timestamp"].isoformat()
        return docs
    except Exception as exc:
        logger.error("get_logs_for_workflow failed: %s", exc)
        return []


def get_system_health() -> Dict[str, Any]:
    """
    Aggregate a quick health snapshot from system_logs.
    Returns counts by status and the last 5 errors.
    """
    try:
        db_col = col("system_logs")
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        status_counts = {
            doc["_id"]: doc["count"]
            for doc in db_col.aggregate(pipeline)
        }
        recent_errors = list(
            db_col.find(
                {"error": {"$ne": None}},
                {"_id": 0, "log_id": 1, "source_agent": 1, "payload_type": 1,
                 "error": 1, "timestamp": 1},
            )
            .sort("timestamp", -1)
            .limit(5)
        )
        for doc in recent_errors:
            if isinstance(doc.get("timestamp"), datetime):
                doc["timestamp"] = doc["timestamp"].isoformat()

        return {
            "status_counts": status_counts,
            "recent_errors":  recent_errors,
            "total_events":   sum(status_counts.values()),
        }
    except Exception as exc:
        logger.error("get_system_health failed: %s", exc)
        return {"status_counts": {}, "recent_errors": [], "total_events": 0}
