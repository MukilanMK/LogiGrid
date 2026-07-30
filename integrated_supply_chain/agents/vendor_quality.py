"""
agents/vendor_quality.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 5 — Vendor Quality Scoring Agent

Core logic (preserved from original agent5/scoring_engine.py + db.py):
  • classify_feedback()          — Groq LLM classification
  • compute_score_delta()        — deterministic PENALTY_TABLE × SOURCE_WEIGHTS
  • update_supplier_score()      — clamp to [0,100], set compliance_flag at <30
  • process_feedback()           — full pipeline for a single feedback row
  • reprocess_all_feedback()     — repair fallback-poisoned historical rows
  • resolve_supplier_from_invoice() — PO-chain supplier resolution

Integration:
  • ingest_audit_discrepancies() — auto-called by Supervisor from Agent 4
  • register_new_po()            — called by Supervisor from Agent 3
  • Emits QualityScoredPayload   → Supervisor after every score update
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.config import settings
from core.db import col
from core.llm_client import get_groq_client
from orchestrator.data_contracts import (
    AgentID,
    AuditCompletedPayload,
    FeedbackCategory,
    FeedbackSeverity,
    POIssuedPayload,
    QualityScoredPayload,
    WorkflowStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS  (preserved exactly from original scoring_engine.py)
# ─────────────────────────────────────────────────────────────────────────────

COMPLIANCE_THRESHOLD = 30.0

VALID_CATEGORIES = {"MFG_DEFECT", "LOGISTICS_DAMAGE", "USER_ERROR", "POSITIVE", "OTHER"}
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "NONE"}

PENALTY_TABLE: Dict[str, Dict[str, float]] = {
    "MFG_DEFECT": {
        "HIGH":   8.0,
        "MEDIUM": 5.0,
        "LOW":    2.0,
        "NONE":   0.0,
    },
    "LOGISTICS_DAMAGE": {
        "HIGH":   4.0,
        "MEDIUM": 2.0,
        "LOW":    1.0,
        "NONE":   0.0,
    },
    "USER_ERROR": {
        "HIGH":   0.0,
        "MEDIUM": 0.0,
        "LOW":    0.0,
        "NONE":   0.0,
    },
    "POSITIVE": {
        "HIGH":   -2.0,
        "MEDIUM": -2.0,
        "LOW":    -2.0,
        "NONE":   -2.0,
    },
    "OTHER": {
        "HIGH":   0.0,
        "MEDIUM": 0.0,
        "LOW":    0.0,
        "NONE":   0.0,
    },
}

SOURCE_WEIGHTS: Dict[str, float] = {
    "SELLER":   1.2,
    "CUSTOMER": 1.0,
}

_CLASSIFICATION_SYSTEM_PROMPT = """
You are the classification component of a vendor quality scoring system.
Your ONLY job is to read raw feedback text and return structured classification labels.
You NEVER compute numeric scores.

TASK
Classify the feedback into exactly one category:
  - MFG_DEFECT        Product itself is faulty (manufacturing defect, broken on arrival)
  - LOGISTICS_DAMAGE  Damaged during shipping/handling
  - USER_ERROR        Customer/user misuse or operator mistake
  - POSITIVE          Positive feedback, praise, or satisfaction
  - OTHER             Anything that does not fit the above

Assign one severity level:
  - HIGH    Serious defect, safety risk, or major operational impact
  - MEDIUM  Moderate issue affecting usability or quality
  - LOW     Minor cosmetic or inconvenience issue
  - NONE    No severity (use with POSITIVE or benign OTHER)

OUTPUT FORMAT — return ONLY valid JSON, no markdown, no explanation:
{"category": "...", "severity": "..."}

RULES
- If ambiguous, prefer the LESS severe and LESS supplier-attributable category.
- POSITIVE feedback must always have severity NONE.
- USER_ERROR always gets zero score delta regardless of severity.
- Do not output anything except the JSON object.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_all_suppliers() -> List[Dict[str, Any]]:
    return list(col("suppliers").find({}, {"_id": 0}).sort("supplier_name", 1))


def get_supplier_by_id(supplier_id: str) -> Optional[Dict[str, Any]]:
    return col("suppliers").find_one({"supplier_id": supplier_id}, {"_id": 0})


def update_supplier_score_db(
    supplier_id: str,
    new_score:   float,
    compliance_flag: bool,
) -> None:
    col("suppliers").update_one(
        {"supplier_id": supplier_id},
        {"$set": {"trust_score": round(new_score, 4), "compliance_flag": compliance_flag}},
    )


def resolve_supplier_from_invoice(invoice_id: str) -> Optional[str]:
    """
    Resolve supplier_id from the PO chain:
    invoice → line items → products → most recent PO → supplier.
    """
    invoice = col("sales_invoices").find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not invoice:
        return None

    invoice_ts  = invoice.get("timestamp")
    line_items  = invoice.get("line_items", [])
    product_ids = list({str(li.get("product_id")) for li in line_items})

    for product_id in product_ids:
        query = {"product_id": product_id}
        if invoice_ts:
            query["order_date"] = {"$lte": invoice_ts}
        po = col("purchase_orders").find_one(
            query,
            {"_id": 0},
            sort=[("order_date", -1)],
        )
        if po:
            return po.get("supplier_id")
    return None


def get_score_history(supplier_id: str) -> List[Dict[str, Any]]:
    """Replay feedback deltas oldest-first to build a running score timeline."""
    supplier = get_supplier_by_id(supplier_id)
    if not supplier:
        return []

    rows = list(
        col("quality_complaints")
        .find({"supplier_id": supplier_id}, {"_id": 0, "created_at": 1, "score_delta": 1})
        .sort("created_at", 1)
    )
    if not rows:
        return [{"created_at": datetime.now(timezone.utc), "trust_score": supplier["trust_score"]}]

    total_delta    = sum(r.get("score_delta", 0.0) for r in rows)
    starting_score = max(0.0, min(100.0, supplier["trust_score"] + total_delta))

    history = []
    running = starting_score
    for row in rows:
        delta   = row.get("score_delta", 0.0)
        running = max(0.0, min(100.0, running - delta))
        history.append({
            "created_at":  row["created_at"],
            "trust_score": round(running, 4),
        })
    return history


# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

def classify_feedback(raw_feedback: str, source_type: str) -> Dict[str, str]:
    """LLM classification — returns {category, severity}."""
    fallback = {"category": "OTHER", "severity": "LOW"}
    if not raw_feedback or not raw_feedback.strip():
        return fallback

    user_message = (
        f"source_type: {source_type}\n\nraw_feedback:\n\"\"\"\n{raw_feedback.strip()}\n\"\"\""
    )
    try:
        client   = get_groq_client()
        response = client.chat.completions.create(
            model       = settings.groq_model_fast,
            temperature = 0,
            max_tokens  = 128,
            messages    = [
                {"role": "system", "content": _CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )
        raw_content = response.choices[0].message.content or ""
        clean       = re.sub(r"```(?:json)?|```", "", raw_content).strip()
        parsed      = json.loads(clean)

        category = str(parsed.get("category", "OTHER")).upper()
        severity = str(parsed.get("severity", "LOW")).upper()

        if category not in VALID_CATEGORIES:
            category = "OTHER"
        if severity not in VALID_SEVERITIES:
            severity = "LOW"
        if category == "POSITIVE":
            severity = "NONE"

        return {"category": category, "severity": severity}
    except Exception:
        return fallback


def compute_score_delta(
    category:    str,
    severity:    str,
    source_type: str,
) -> float:
    """Deterministic delta. Positive = penalty, Negative = bonus."""
    base   = PENALTY_TABLE.get(category.upper(), PENALTY_TABLE["OTHER"]).get(severity.upper(), 0.0)
    weight = SOURCE_WEIGHTS.get(source_type.upper(), 1.0)
    return round(base * weight, 4)


def update_supplier_score(supplier_id: str, delta: float) -> Dict[str, Any]:
    """Fetch, apply delta, clamp, persist."""
    supplier = get_supplier_by_id(supplier_id)
    if not supplier:
        raise ValueError(f"Supplier '{supplier_id}' not found.")

    current  = float(supplier.get("trust_score", 100.0))
    new_score = round(max(0.0, min(100.0, current - delta)), 4)
    flagged   = new_score < COMPLIANCE_THRESHOLD
    update_supplier_score_db(supplier_id, new_score, flagged)
    return {**supplier, "trust_score": new_score, "compliance_flag": flagged}


def process_feedback(feedback_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Full pipeline for a single new feedback submission.
    Classifies → computes delta → updates supplier score → persists feedback.
    """
    raw_feedback = feedback_row.get("raw_feedback", "")
    source_type  = feedback_row.get("source_type", "CUSTOMER")

    classification = classify_feedback(raw_feedback, source_type)
    ai_category    = classification["category"]
    ai_severity    = classification["severity"]
    delta          = compute_score_delta(ai_category, ai_severity, source_type)

    supplier_id      = feedback_row["supplier_id"]
    updated_supplier = update_supplier_score(supplier_id, delta)

    complete_row = {
        **feedback_row,
        "ai_category": ai_category,
        "ai_severity": ai_severity,
        "score_delta": delta,
        "created_at":  feedback_row.get("created_at", datetime.now(timezone.utc)),
    }
    col("quality_complaints").insert_one({**complete_row})

    return {
        **updated_supplier,
        "ai_category": ai_category,
        "ai_severity": ai_severity,
        "score_delta": delta,
    }


def reprocess_all_feedback(supplier_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Re-classify feedback rows that landed on OTHER/0.0 (fallback fingerprint).
    Replay all deltas to recompute correct cumulative scores.
    """
    suppliers = (
        [get_supplier_by_id(supplier_id)] if supplier_id
        else get_all_suppliers()
    )
    suppliers = [s for s in suppliers if s]

    total_reclassified = 0
    results: List[Dict[str, Any]] = []

    for supplier in suppliers:
        sid  = supplier["supplier_id"]
        rows = list(
            col("quality_complaints")
            .find(
                {"supplier_id": sid},
                {"_id": 0, "feedback_id": 1, "source_type": 1,
                 "raw_feedback": 1, "ai_category": 1, "score_delta": 1},
            )
            .sort("created_at", 1)
        )
        reclassified = 0
        for row in rows:
            if not (
                row.get("ai_category") == "OTHER"
                and row.get("score_delta", 0.0) == 0.0
                and row.get("raw_feedback", "").strip()
            ):
                continue
            src  = row.get("source_type", "CUSTOMER")
            cls  = classify_feedback(row["raw_feedback"], src)
            new_cat   = cls["category"]
            new_sev   = cls["severity"]
            new_delta = compute_score_delta(new_cat, new_sev, src)
            col("quality_complaints").update_one(
                {"feedback_id": row["feedback_id"]},
                {"$set": {"ai_category": new_cat, "ai_severity": new_sev, "score_delta": new_delta}},
            )
            reclassified += 1

        if reclassified > 0:
            all_rows  = list(
                col("quality_complaints")
                .find({"supplier_id": sid}, {"_id": 0, "score_delta": 1})
                .sort("created_at", 1)
            )
            score     = 100.0
            for r in all_rows:
                score = max(0.0, min(100.0, score - r.get("score_delta", 0.0)))
            new_score    = round(score, 4)
            compliance   = new_score < COMPLIANCE_THRESHOLD
            update_supplier_score_db(sid, new_score, compliance)
        else:
            new_score  = supplier["trust_score"]
            compliance = supplier["compliance_flag"]

        total_reclassified += reclassified
        results.append({
            "supplier_id":     sid,
            "supplier_name":   supplier["supplier_name"],
            "reclassified":    reclassified,
            "new_score":       new_score,
            "compliance_flag": compliance,
        })

    return {"total_reclassified": total_reclassified, "suppliers": results}


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 5 SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class VendorQualityService:
    """Service class registered with the Supervisor."""

    def register_new_po(self, payload: POIssuedPayload) -> None:
        """
        Called by Supervisor when a PO is issued (Agent 3 output).
        Ensures the supplier exists in the suppliers collection;
        creates a baseline record if not.
        """
        supplier_id = payload.winner_supplier_id
        existing    = get_supplier_by_id(supplier_id)
        if not existing:
            col("suppliers").update_one(
                {"supplier_id": supplier_id},
                {"$setOnInsert": {
                    "supplier_id":          supplier_id,
                    "supplier_name":        payload.winner_supplier_id,
                    "contact_email":        payload.winner_email,
                    "gstin":                "",
                    "categories_supplied":  [payload.category],
                    "trust_score":          100.0,
                    "compliance_flag":      False,
                }},
                upsert=True,
            )

    def ingest_audit_discrepancies(self, payload: AuditCompletedPayload) -> None:
        """
        Called by Supervisor when an AuditCompletedPayload has discrepancies.
        Auto-creates quality complaints for CRITICAL discrepancies.
        """
        from orchestrator.supervisor import get_supervisor

        supplier_email = payload.invoice_data.supplier_email.lower()
        supplier_doc   = col("suppliers").find_one(
            {"contact_email": {"$regex": supplier_email, "$options": "i"}}, {"_id": 0}
        )
        if not supplier_doc:
            return

        supplier_id = supplier_doc["supplier_id"]

        for disc in payload.discrepancies:
            if disc.severity not in ("CRITICAL", "WARNING"):
                continue
            feedback_row = {
                "feedback_id":        f"FB-AUDIT-{uuid4().hex[:8].upper()}",
                "source_type":        "SELLER",
                "supplier_id":        supplier_id,
                "invoice_id":         payload.invoice_data.invoice_number,
                "product_id":         None,
                "raw_feedback":       disc.description,
                "additional_details": f"Auto-generated from invoice audit. Severity: {disc.severity}",
                "created_at":         datetime.now(timezone.utc),
            }
            result = process_feedback(feedback_row)

            quality_payload = QualityScoredPayload(
                workflow_id     = payload.workflow_id,
                supplier_id     = supplier_id,
                supplier_name   = supplier_doc.get("supplier_name", supplier_id),
                new_trust_score = result["trust_score"],
                compliance_flag = result["compliance_flag"],
                ai_category     = FeedbackCategory(result["ai_category"]),
                ai_severity     = FeedbackSeverity(result["ai_severity"]),
                score_delta     = result["score_delta"],
                feedback_id     = feedback_row["feedback_id"],
                status          = WorkflowStatus.SUCCESS,
            )
            try:
                get_supervisor().route(quality_payload)
            except Exception as exc:
                from orchestrator.logger import logger
                logger.warning("Supervisor routing QualityScoredPayload failed: %s", exc)

    def submit_feedback(
        self,
        source_type:        str,
        supplier_id:        str,
        raw_feedback:       str,
        additional_details: str = "",
        invoice_id:         Optional[str] = None,
        product_id:         Optional[str] = None,
        workflow_id:        Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        UI-triggered feedback submission.
        Returns the scoring result dict and routes QualityScoredPayload to Supervisor.
        """
        from orchestrator.supervisor import get_supervisor
        import uuid

        wf_id = workflow_id or f"WF-VQ-{uuid.uuid4().hex[:8].upper()}"
        feedback_row = {
            "feedback_id":        f"FB-{uuid.uuid4().hex[:8].upper()}",
            "source_type":        source_type,
            "supplier_id":        supplier_id,
            "invoice_id":         invoice_id,
            "product_id":         product_id,
            "raw_feedback":       raw_feedback.strip(),
            "additional_details": additional_details.strip(),
            "created_at":         datetime.now(timezone.utc),
        }
        result = process_feedback(feedback_row)

        supplier_doc = get_supplier_by_id(supplier_id) or {}
        quality_payload = QualityScoredPayload(
            workflow_id     = wf_id,
            supplier_id     = supplier_id,
            supplier_name   = supplier_doc.get("supplier_name", supplier_id),
            new_trust_score = result["trust_score"],
            compliance_flag = result["compliance_flag"],
            ai_category     = FeedbackCategory(result["ai_category"]),
            ai_severity     = FeedbackSeverity(result["ai_severity"]),
            score_delta     = result["score_delta"],
            feedback_id     = feedback_row["feedback_id"],
            status          = WorkflowStatus.SUCCESS,
        )
        try:
            get_supervisor().route(quality_payload)
        except Exception as exc:
            from orchestrator.logger import logger
            logger.warning("Supervisor routing QualityScoredPayload failed: %s", exc)

        result["supplier_name"] = supplier_doc.get("supplier_name", supplier_id)
        return result


def register_with_supervisor() -> VendorQualityService:
    from orchestrator.supervisor import get_supervisor
    service = VendorQualityService()
    get_supervisor().register_agent(AgentID.VENDOR_QUALITY, service)
    return service
