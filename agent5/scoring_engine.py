"""
scoring_engine.py
LLM-backed feedback classification (Groq API) + deterministic scoring formula.

Public API
----------
classify_feedback(raw_feedback, source_type)      -> dict
compute_score_delta(category, severity, source_type) -> float
update_supplier_score(supplier_id, delta)          -> dict
process_feedback(feedback_row)                     -> dict
reprocess_all_feedback(supplier_id)                -> dict
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

from groq import Groq

import db

# ─── constants ────────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

COMPLIANCE_THRESHOLD = 30.0   # trust_score below this → compliance_flag = True

VALID_CATEGORIES = {"MFG_DEFECT", "LOGISTICS_DAMAGE", "USER_ERROR", "POSITIVE", "OTHER"}
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "NONE"}

# Penalty table: category → severity → base points
# Positive value = penalty (score drops); negative value = bonus (score rises).
PENALTY_TABLE: dict[str, dict[str, float]] = {
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

SOURCE_WEIGHTS = {
    "SELLER":   1.2,
    "CUSTOMER": 1.0,
}

# ─── Groq client (lazy) ───────────────────────────────────────────────────────

_groq_client: Optional[Groq] = None


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file or environment."
            )
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


# ─── classification ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are the classification component of a vendor quality scoring system.

Your ONLY job is to read raw feedback text and return structured classification labels.
You NEVER compute numeric scores — that is done by deterministic code after you respond.

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


def classify_feedback(raw_feedback: str, source_type: str) -> dict:
    """
    Call the Groq LLM to classify raw feedback text.

    Returns dict with keys: category (str), severity (str).
    Falls back to {"category": "OTHER", "severity": "LOW"} on any failure.
    """
    fallback = {"category": "OTHER", "severity": "LOW"}

    if not raw_feedback or not raw_feedback.strip():
        return fallback

    user_message = (
        f"source_type: {source_type}\n\n"
        f"raw_feedback:\n\"\"\"\n{raw_feedback.strip()}\n\"\"\""
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=128,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )

        raw_content = response.choices[0].message.content or ""
        clean       = re.sub(r"```(?:json)?|```", "", raw_content).strip()
        parsed      = json.loads(clean)

        category = str(parsed.get("category", "OTHER")).upper()
        severity = str(parsed.get("severity", "LOW")).upper()

        if category not in VALID_CATEGORIES:
            print(f"[scoring_engine] Unknown category '{category}' — defaulting to OTHER")
            category = "OTHER"

        if severity not in VALID_SEVERITIES:
            print(f"[scoring_engine] Unknown severity '{severity}' — defaulting to LOW")
            severity = "LOW"

        if category == "POSITIVE":
            severity = "NONE"

        return {"category": category, "severity": severity}

    except json.JSONDecodeError as exc:
        print(f"[scoring_engine] JSON parse error: {exc}. Falling back to OTHER/LOW.")
        return fallback

    except Exception as exc:
        print(f"[scoring_engine] Groq API error: {exc}. Falling back to OTHER/LOW.")
        return fallback


# ─── scoring ──────────────────────────────────────────────────────────────────

def compute_score_delta(category: str, severity: str, source_type: str) -> float:
    """
    Deterministic score delta.
    Positive = penalty (score decreases). Negative = bonus (score increases).
    """
    category    = category.upper()
    severity    = severity.upper()
    source_type = source_type.upper()

    base   = PENALTY_TABLE.get(category, PENALTY_TABLE["OTHER"]).get(severity, 0.0)
    weight = SOURCE_WEIGHTS.get(source_type, 1.0)
    return round(base * weight, 4)


def update_supplier_score(supplier_id: str, delta: float) -> dict:
    """
    Fetch supplier, apply delta (new = current - delta), clamp to [0,100], persist.
    Returns updated supplier dict.
    """
    supplier = db.get_supplier_by_id(supplier_id)
    if not supplier:
        raise ValueError(f"Supplier '{supplier_id}' not found in database.")

    current_score   = float(supplier.get("trust_score", 100.0))
    new_score       = round(max(0.0, min(100.0, current_score - delta)), 4)
    compliance_flag = new_score < COMPLIANCE_THRESHOLD

    db.update_supplier_score(supplier_id, new_score, compliance_flag)

    return {**supplier, "trust_score": new_score, "compliance_flag": compliance_flag}


# ─── main pipeline ────────────────────────────────────────────────────────────

def process_feedback(feedback_row: dict) -> dict:
    """
    Full pipeline for a single new feedback submission:
      1. Classify via LLM
      2. Compute deterministic score delta
      3. Update supplier trust score in DB
      4. Persist completed feedback row
      5. Return updated supplier record

    feedback_row must contain:
      feedback_id, source_type, supplier_id, raw_feedback,
      invoice_id (nullable), product_id (nullable), additional_details, created_at
    """
    raw_feedback = feedback_row.get("raw_feedback", "")
    source_type  = feedback_row.get("source_type", "CUSTOMER")

    # 1. Classify
    classification = classify_feedback(raw_feedback, source_type)
    ai_category    = classification["category"]
    ai_severity    = classification["severity"]

    # 2. Delta
    delta = compute_score_delta(ai_category, ai_severity, source_type)

    # 3. Update supplier score
    supplier_id      = feedback_row["supplier_id"]
    updated_supplier = update_supplier_score(supplier_id, delta)

    # 4. Persist feedback with AI fields filled in
    complete_row = {
        **feedback_row,
        "ai_category": ai_category,
        "ai_severity": ai_severity,
        "score_delta": delta,
        "created_at":  feedback_row.get("created_at", datetime.now(timezone.utc)),
    }
    db.insert_feedback(complete_row)

    # 5. Return
    return {
        **updated_supplier,
        "ai_category": ai_category,
        "ai_severity": ai_severity,
        "score_delta": delta,
    }


# ─── reprocessor (repairs fallback-poisoned historical rows) ──────────────────

def reprocess_all_feedback(supplier_id: str | None = None) -> dict:
    """
    Re-classify every feedback row whose ai_category is 'OTHER' AND score_delta is 0 —
    the exact fingerprint left behind when process_feedback fell back due to a dead model.

    After reclassifying, replay ALL rows for that supplier to recompute the correct
    cumulative trust score starting from 100 (the standard seed baseline).

    supplier_id: if given, only process that one supplier; otherwise all suppliers.
    Returns a summary dict with per-supplier results.
    """
    suppliers = (
        [db.get_supplier_by_id(supplier_id)] if supplier_id
        else db.get_all_suppliers()
    )
    suppliers = [s for s in suppliers if s]

    total_reclassified = 0
    results            = []

    for supplier in suppliers:
        sid  = supplier["supplier_id"]
        rows = db.get_all_feedback_ids_for_supplier(sid)

        reclassified = 0
        for row in rows:
            # Fingerprint of a fallback: OTHER category + zero delta + non-empty text
            if not (
                row.get("ai_category") == "OTHER"
                and row.get("score_delta", 0.0) == 0.0
                and row.get("raw_feedback", "").strip()
            ):
                continue

            src            = row.get("source_type", "CUSTOMER")
            classification = classify_feedback(row["raw_feedback"], src)
            new_cat        = classification["category"]
            new_sev        = classification["severity"]
            new_delta      = compute_score_delta(new_cat, new_sev, src)

            db.update_feedback_classification(row["feedback_id"], new_cat, new_sev, new_delta)
            reclassified += 1

        # Recompute cumulative score only if something changed
        if reclassified > 0:
            new_score       = db.recompute_supplier_score_from_feedback(sid, seed_score=100.0)
            compliance_flag = new_score < COMPLIANCE_THRESHOLD
            db.update_supplier_score(sid, new_score, compliance_flag)
        else:
            new_score       = supplier["trust_score"]
            compliance_flag = supplier["compliance_flag"]

        total_reclassified += reclassified
        results.append({
            "supplier_id":     sid,
            "supplier_name":   supplier["supplier_name"],
            "reclassified":    reclassified,
            "new_score":       new_score,
            "compliance_flag": compliance_flag,
        })

    return {"total_reclassified": total_reclassified, "suppliers": results}
