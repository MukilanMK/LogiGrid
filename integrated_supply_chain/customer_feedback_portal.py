"""
customer_feedback_portal.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Standalone Customer Feedback Portal

Run independently:
    streamlit run customer_feedback_portal.py --server.port 8502

Redesigned flow:
  1. Enter invoice number → look up sales_invoices (same project DB)
  2. Display all products on that invoice — customer SELECTS one
  3. Product name matched to products collection → supplier_id fetched
     (products table must carry a supplier_id field)
  4. Feedback text sent to Groq LLM for classification
  5. process_feedback() updates trust score immediately
  Supplier details are NEVER shown to the customer.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import os, sys, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

st.set_page_config(page_title="Customer Feedback Portal", page_icon="💬", layout="centered")

st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"]{background:#090D16;color:#E2E8F0;font-family:'Inter',sans-serif}
[data-testid="stSidebar"]{display:none}
h1{color:#F8FAFC!important;font-size:1.55rem!important;font-weight:700!important}
hr{border-color:#1E293B!important}
[data-testid="metric-container"]{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:14px 18px!important}
[data-testid="stMetricLabel"]{color:#64748B!important;font-size:.75rem!important;text-transform:uppercase}
[data-testid="stMetricValue"]{color:#F8FAFC!important;font-size:1.35rem!important;font-weight:700!important}
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea{
    background:#0F172A!important;color:#E2E8F0!important;
    border:1px solid #334155!important;border-radius:6px!important}
label,[data-testid="stWidgetLabel"]{color:#94A3B8!important;font-size:.8rem!important;
    text-transform:uppercase!important;letter-spacing:.04em!important}
[data-testid="baseButton-primary"]{background:linear-gradient(135deg,#6366F1,#4F46E5)!important;
    color:#fff!important;border:none!important;border-radius:6px!important;font-weight:600!important}
.stSuccess{background:rgba(16,185,129,.12)!important;border-left:3px solid #10B981!important;color:#6EE7B7!important}
.stError  {background:rgba(244,63,94,.12)!important;border-left:3px solid #F43F5E!important;color:#FDA4AF!important}
.stWarning{background:rgba(245,158,11,.12)!important;border-left:3px solid #F59E0B!important;color:#FCD34D!important}
.stInfo   {background:rgba(99,102,241,.12)!important;border-left:3px solid #6366F1!important;color:#A5B4FC!important}
.result-card{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:20px 24px;margin-top:16px}
.prod-row{background:#0F172A;border:1px solid #1E293B;border-radius:8px;padding:10px 16px;margin-bottom:6px}
</style>""", unsafe_allow_html=True)

# ─── DB guard ─────────────────────────────────────────────────────────────────
from core.db import ping, col
if not ping():
    st.error("Cannot connect to the database. Please try again later.")
    st.stop()

from agents.vendor_quality import process_feedback, resolve_supplier_from_invoice

# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:28px 0 8px">
  <div style="font-size:2.4rem">💬</div>
  <h1 style="margin:6px 0 4px">Customer Feedback Portal</h1>
  <p style="color:#475569;font-size:.9rem;margin:0">
    Share your experience with a recent purchase.
    Your feedback helps us maintain quality and serve you better.
  </p>
</div>
<hr/>""", unsafe_allow_html=True)

# ─── Session state defaults ───────────────────────────────────────────────────
for _k, _v in {
    "submitted_result": None,
    "invoice_doc":      None,
    "invoice_products": [],
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Invoice lookup
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("### Step 1 — Enter Your Invoice Number")
st.caption("Enter the invoice number printed on your receipt or order confirmation email.")

invoice_input = st.text_input(
    "Invoice Number", placeholder="e.g. INV-2026-001", key="cf_invoice"
)

if invoice_input.strip():
    invoice_doc = col("sales_invoices").find_one(
        {"invoice_id": invoice_input.strip()}, {"_id": 0}
    )
    if not invoice_doc:
        st.error(
            f"Invoice **{invoice_input.strip()}** was not found. "
            "Please double-check the number on your receipt."
        )
        st.session_state["invoice_doc"]      = None
        st.session_state["invoice_products"] = []
    else:
        date_str = str(invoice_doc.get("timestamp", ""))[:10]
        amount   = invoice_doc.get("total_amount", 0.0)
        st.success(f"✅ Invoice found — Date: **{date_str}** | Total: **₹{amount:,.2f}**")

        # ── Fetch all products on this invoice from the products collection ────
        line_items  = invoice_doc.get("line_items", [])
        product_ids = [li.get("product_id") for li in line_items if li.get("product_id")]
        products_db: List[Dict[str, Any]] = []

        if product_ids:
            products_db = list(col("products").find(
                {"product_id": {"$in": product_ids}},
                {"_id": 0, "product_id": 1, "name": 1, "category": 1, "supplier_id": 1}
            ))
            # Attach quantity from line_items to each product
            qty_map = {li["product_id"]: li.get("quantity", 0) for li in line_items}
            for p in products_db:
                p["quantity"] = qty_map.get(p["product_id"], 0)

        st.session_state["invoice_doc"]      = invoice_doc
        st.session_state["invoice_products"] = products_db

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Product selection (only shown after invoice is found)
# ═══════════════════════════════════════════════════════════════════════════════
selected_product:     Optional[Dict[str, Any]] = None
selected_supplier_id: Optional[str]            = None

_inv_doc      = st.session_state.get("invoice_doc")
_inv_products = st.session_state.get("invoice_products") or []

if _inv_doc:
    st.markdown("### Step 2 — Select the Product Your Feedback is About")

    if not _inv_products:
        st.warning(
            "No products were found in the database for this invoice's line items. "
            "You can still submit general feedback below."
        )
    else:
        # Show all products on the invoice as a table so the customer can see what they ordered
        import pandas as pd
        df_display = pd.DataFrame([{
            "Product Name": p["name"],
            "Category":     p.get("category", ""),
            "Qty Ordered":  p.get("quantity", ""),
        } for p in _inv_products])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Dropdown — product names only (IDs and supplier_id stay hidden)
        product_label_map: Dict[str, str] = {
            p["product_id"]: f"{p['name']}  ({p.get('category', '')})"
            for p in _inv_products
        }
        product_label_map["__ALL__"] = "🔹 General feedback — not specific to one product"

        selected_pid = st.selectbox(
            "Which product are you giving feedback on?",
            list(product_label_map.keys()),
            format_func=lambda x: product_label_map[x],
            key="cf_product_select",
        )

        if selected_pid == "__ALL__":
            # Fallback: resolve supplier from PO chain
            selected_supplier_id = resolve_supplier_from_invoice(invoice_input.strip())
            if selected_supplier_id:
                st.info("🔹 General order feedback — supplier resolved automatically.")
            else:
                st.info("🔹 General order feedback — our team will review and link this.")
        else:
            # Match selected product_id → get supplier_id from products table
            selected_product = next(
                (p for p in _inv_products if p["product_id"] == selected_pid), None
            )
            if selected_product:
                selected_supplier_id = selected_product.get("supplier_id")

                # Show product card (no supplier info exposed)
                st.markdown(
                    f"<div class='prod-row'>"
                    f"<span style='font-weight:600;color:#E2E8F0'>📦 {selected_product['name']}</span>"
                    f"<span style='font-size:.78rem;color:#475569;margin-left:10px'>"
                    f"{selected_product.get('category','')} &nbsp;·&nbsp; "
                    f"Qty: {selected_product.get('quantity',0)}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )

                if not selected_supplier_id:
                    st.warning(
                        f"⚠️ **{selected_product['name']}** does not have a `supplier_id` in the "
                        "products table. Please add one so feedback can be linked to the supplier. "
                        "Your feedback will still be saved."
                    )

    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Feedback form
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("### Step 3 — Describe Your Experience")

CATEGORY_OPTIONS = {
    "Product Quality Issue":  "I received a defective, broken, or faulty product.",
    "Delivery / Packaging":   "The item arrived damaged or the packaging was poor.",
    "Great Experience":       "Everything was perfect — good quality and on time.",
    "Wrong Item Received":    "I received something different from what I ordered.",
    "Other":                  "Something else I'd like to share.",
}

feedback_type = st.selectbox(
    "What best describes your experience?",
    list(CATEGORY_OPTIONS.keys()), key="cf_type",
)
st.caption(CATEGORY_OPTIONS[feedback_type])

feedback_text = st.text_area(
    "Describe your experience",
    height=140,
    placeholder="Tell us exactly what happened. Be as specific as possible.",
    key="cf_text",
)
additional = st.text_area(
    "Additional details (optional)",
    height=80,
    placeholder="Batch code, order reference, photo description, etc.",
    key="cf_extra",
)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Submit
# ═══════════════════════════════════════════════════════════════════════════════
can_submit = bool(_inv_doc and feedback_text.strip())

submit_btn = st.button(
    "📤 Submit Feedback",
    type="primary",
    use_container_width=True,
    disabled=not can_submit,
)

if submit_btn and can_submit:
    enriched_feedback = f"[{feedback_type}] {feedback_text.strip()}"
    product_id   = selected_product["product_id"]   if selected_product else None
    product_name = selected_product["name"]          if selected_product else None

    with st.spinner("Analysing your feedback and updating supplier quality score…"):

        if not selected_supplier_id:
            # Save without scoring — no supplier linkage
            record = {
                "feedback_id":        f"FB-{uuid.uuid4().hex[:8].upper()}",
                "source_type":        "CUSTOMER",
                "supplier_id":        "UNKNOWN",
                "invoice_id":         invoice_input.strip(),
                "product_id":         product_id,
                "product_name":       product_name,
                "raw_feedback":       enriched_feedback,
                "additional_details": additional.strip(),
                "ai_category":        "OTHER",
                "ai_severity":        "LOW",
                "score_delta":        0.0,
                "created_at":         datetime.now(timezone.utc),
                "portal":             "customer_feedback_portal",
                "note":               "Supplier could not be resolved.",
            }
            col("quality_complaints").insert_one(record)
            st.session_state["submitted_result"] = {
                "ai_category": "OTHER", "ai_severity": "LOW",
                "score_delta": 0.0, "trust_score": None,
                "compliance_flag": False, "product_name": product_name,
                "unresolved_supplier": True,
            }
        else:
            # Full pipeline: Groq classify → delta → trust score update
            feedback_row = {
                "feedback_id":        f"FB-{uuid.uuid4().hex[:8].upper()}",
                "source_type":        "CUSTOMER",
                "supplier_id":        selected_supplier_id,
                "invoice_id":         invoice_input.strip(),
                "product_id":         product_id,
                "product_name":       product_name,
                "raw_feedback":       enriched_feedback,
                "additional_details": additional.strip(),
                "created_at":         datetime.now(timezone.utc),
                "portal":             "customer_feedback_portal",
            }
            try:
                result = process_feedback(feedback_row)
                result["product_name"]        = product_name
                result["unresolved_supplier"] = False
                st.session_state["submitted_result"] = result
            except Exception as exc:
                st.error(f"Submission failed: {exc}")
                st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# RESULT DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state["submitted_result"]:
    res         = st.session_state["submitted_result"]
    ai_cat      = res.get("ai_category", "OTHER")
    ai_sev      = res.get("ai_severity", "LOW")
    prod_name   = res.get("product_name")
    trust_score = res.get("trust_score")
    score_delta = res.get("score_delta", 0.0)

    FRIENDLY = {
        "MFG_DEFECT":       "Product Quality Issue",
        "LOGISTICS_DAMAGE": "Delivery / Packaging Issue",
        "USER_ERROR":       "Usage Clarification",
        "POSITIVE":         "Positive Feedback",
        "OTHER":            "General Feedback",
    }
    friendly_cat = FRIENDLY.get(ai_cat, "General Feedback")

    st.markdown(
        "<div class='result-card'>"
        "<div style='color:#10B981;font-size:1.05rem;font-weight:700;margin-bottom:14px'>"
        "✅ Thank you — your feedback has been recorded.</div>",
        unsafe_allow_html=True,
    )

    if prod_name:
        st.markdown(
            f"<div style='background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.3);"
            f"border-radius:8px;padding:10px 16px;color:#A5B4FC;font-size:.9rem;margin-bottom:14px'>"
            f"📦 <strong>Product:</strong> {prod_name}</div>",
            unsafe_allow_html=True,
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Category",  friendly_cat)
    c2.metric("Severity",  ai_sev if ai_sev != "NONE" else "—")
    if trust_score is not None:
        c3.metric("Supplier Quality Score", f"{trust_score:.1f}/100")
    else:
        c3.metric("Score Impact", "—")

    if res.get("compliance_flag"):
        st.warning(
            "⚠️ This issue has been escalated to our quality team for immediate review. "
            "We will follow up with you."
        )
    elif res.get("unresolved_supplier"):
        st.info("Your feedback has been saved. Our team will review and link it to the correct supplier.")
    else:
        if score_delta > 0:
            impact = f"The supplier's trust score was reduced by **{score_delta:.2f}** points."
        elif score_delta < 0:
            impact = f"The supplier's trust score was increased by **{abs(score_delta):.2f}** points."
        else:
            impact = "No change to the supplier's trust score."
        st.info(f"Your feedback has been processed and the supplier quality score updated. {impact}")

    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Submit another feedback", key="cf_reset"):
        for k in ["submitted_result", "invoice_doc", "invoice_products"]:
            st.session_state[k] = None
        st.rerun()

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("""
<hr/>
<div style='text-align:center;color:#334155;font-size:.78rem;padding:8px 0 20px'>
  Your feedback is confidential and used solely for supplier quality improvement.
</div>""", unsafe_allow_html=True)
