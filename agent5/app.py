"""
app.py
Streamlit entrypoint for Agent 3: Vendor Quality Scoring & Complaint Agent.

Pages (via sidebar):
  1. Seller Feedback Form
  2. Customer Feedback Form
  3. Supplier Dashboard
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import db
import scoring_engine

# ─── page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Agent 3 — Vendor Quality Scoring",
    page_icon=None,
    layout="wide",
)

# ─── global CSS / theme ───────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── base ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #090D16;
    color: #E2E8F0;
    font-family: 'Inter', sans-serif;
}
[data-testid="stSidebar"] {
    background-color: #0F172A;
    border-right: 1px solid #1E293B;
}
[data-testid="stSidebar"] * { color: #CBD5E1 !important; }

/* ── sidebar nav radio ── */
[data-testid="stSidebar"] .stRadio label {
    display: block;
    padding: 10px 14px;
    border-radius: 6px;
    margin-bottom: 4px;
    cursor: pointer;
    font-size: 0.92rem;
    color: #94A3B8 !important;
    transition: background 0.15s;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: #1E293B;
    color: #E2E8F0 !important;
}

/* ── headings ── */
h1 { color: #F8FAFC !important; font-size: 1.75rem !important; font-weight: 700 !important; }
h2 { color: #CBD5E1 !important; font-size: 1.2rem  !important; font-weight: 600 !important; }
h3 { color: #94A3B8 !important; }

/* ── divider ── */
hr { border-color: #1E293B !important; }

/* ── inputs ── */
input, textarea, select,
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea {
    background-color: #0F172A !important;
    color: #E2E8F0 !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
}
input:focus, textarea:focus {
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 2px rgba(99,102,241,0.25) !important;
}

/* ── labels ── */
label, .stTextInput label, .stTextArea label,
.stSelectbox label, [data-testid="stWidgetLabel"] {
    color: #94A3B8 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}

/* ── primary button ── */
[data-testid="baseButton-primary"],
button[kind="primary"] {
    background: linear-gradient(135deg, #6366F1, #4F46E5) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    transition: opacity 0.15s !important;
}
[data-testid="baseButton-primary"]:hover { opacity: 0.88 !important; }

/* ── secondary button ── */
button[kind="secondary"] {
    background: #1E293B !important;
    color: #CBD5E1 !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
}

/* ── dataframe / table ── */
[data-testid="stDataFrame"] {
    border: 1px solid #1E293B;
    border-radius: 8px;
    overflow: hidden;
}
[data-testid="stDataFrame"] th {
    background-color: #0F172A !important;
    color: #6366F1 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}
[data-testid="stDataFrame"] td { color: #CBD5E1 !important; }
[data-testid="stDataFrame"] tr:hover td { background: #1E293B !important; }

/* ── metric cards ── */
[data-testid="metric-container"] {
    background: #0F172A;
    border: 1px solid #1E293B;
    border-radius: 10px;
    padding: 16px 20px !important;
}
[data-testid="stMetricLabel"]  { color: #64748B !important; font-size: 0.78rem !important; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"]  { color: #F8FAFC !important; font-size: 1.55rem !important; font-weight: 700 !important; }
[data-testid="stMetricDelta"]  { font-size: 0.85rem !important; }

/* ── alerts ── */
[data-testid="stAlert"][data-baseweb="notification"] { border-radius: 8px !important; }
.stSuccess { background: rgba(16,185,129,0.12) !important; border-left: 3px solid #10B981 !important; color: #6EE7B7 !important; }
.stError   { background: rgba(244,63,94,0.12)  !important; border-left: 3px solid #F43F5E !important; color: #FDA4AF !important; }
.stWarning { background: rgba(245,158,11,0.12) !important; border-left: 3px solid #F59E0B !important; color: #FCD34D !important; }
.stInfo    { background: rgba(99,102,241,0.12) !important; border-left: 3px solid #6366F1 !important; color: #A5B4FC !important; }

/* ── spinner ── */
[data-testid="stSpinner"] { color: #6366F1 !important; }

/* ── line chart ── */
[data-testid="stVegaLiteChart"] { border-radius: 8px; overflow: hidden; }

/* ── caption ── */
.stCaption, [data-testid="stCaptionContainer"] { color: #475569 !important; }

/* ── form border ── */
[data-testid="stForm"] {
    background: #0F172A;
    border: 1px solid #1E293B;
    border-radius: 10px;
    padding: 24px !important;
}

/* ── selectbox dropdown ── */
[data-baseweb="popover"] { background: #0F172A !important; border: 1px solid #334155 !important; }
[data-baseweb="menu"] li { color: #CBD5E1 !important; }
[data-baseweb="menu"] li:hover { background: #1E293B !important; }
</style>
""", unsafe_allow_html=True)

# ─── DB connectivity check ────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def check_db() -> bool:
    return db.ping()

if not check_db():
    st.error(
        "Cannot connect to MongoDB. "
        "Make sure MongoDB is running and MONGO_URI is correct in your .env file."
    )
    st.stop()

# ─── sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    "<div style='padding:16px 0 4px 4px'>"
    "<span style='font-size:1.1rem;font-weight:700;color:#F8FAFC;letter-spacing:0.02em'>Agent 3</span>"
    "<br><span style='font-size:0.78rem;color:#475569'>Vendor Quality Scoring</span>"
    "</div>",
    unsafe_allow_html=True,
)
st.sidebar.divider()

PAGE = st.sidebar.radio(
    "Navigate to",
    ["Seller Feedback", "Customer Feedback", "Supplier Dashboard"],
    label_visibility="collapsed",
)

st.sidebar.divider()
st.sidebar.markdown(
    "<div style='font-size:0.72rem;color:#334155;padding:4px'>Powered by Groq + MongoDB</div>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _badge(text: str, bg: str, fg: str) -> str:
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 10px;"
        f"border-radius:12px;font-size:0.78rem;font-weight:600;"
        f"letter-spacing:0.04em'>{text}</span>"
    )

def severity_badge(severity: str) -> str:
    MAP = {
        "HIGH":   ("#F43F5E", "#FFF1F2"),
        "MEDIUM": ("#F59E0B", "#FFFBEB"),
        "LOW":    ("#6366F1", "#EEF2FF"),
        "NONE":   ("#334155", "#CBD5E1"),
    }
    bg, fg = MAP.get(severity, ("#334155", "#CBD5E1"))
    return _badge(severity, bg, fg)

def category_label(category: str) -> str:
    labels = {
        "MFG_DEFECT":       "Manufacturing Defect",
        "LOGISTICS_DAMAGE": "Logistics Damage",
        "USER_ERROR":       "User Error",
        "POSITIVE":         "Positive",
        "OTHER":            "Other",
    }
    return labels.get(category, category)

def category_badge(category: str) -> str:
    MAP = {
        "MFG_DEFECT":       ("#F43F5E", "#FFF1F2"),
        "LOGISTICS_DAMAGE": ("#F59E0B", "#FFFBEB"),
        "USER_ERROR":       ("#6366F1", "#EEF2FF"),
        "POSITIVE":         ("#10B981", "#ECFDF5"),
        "OTHER":            ("#334155", "#CBD5E1"),
    }
    bg, fg = MAP.get(category, ("#334155", "#CBD5E1"))
    return _badge(category_label(category), bg, fg)

def trust_score_indicator(score: float) -> str:
    """Return a coloured inline score pill."""
    if score >= 70:
        colour = "#10B981"
    elif score >= 40:
        colour = "#F59E0B"
    else:
        colour = "#F43F5E"
    return (
        f"<span style='color:{colour};font-weight:700;font-size:1.1rem'>"
        f"{score:.1f}</span>"
        f"<span style='color:#475569;font-size:0.8rem'> / 100</span>"
    )

def compliance_badge(flagged: bool) -> str:
    if flagged:
        return _badge("FLAGGED", "#F43F5E", "#FFF1F2")
    return _badge("OK", "#10B981", "#ECFDF5")

def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"<h1 style='margin-bottom:2px'>{title}</h1>"
        f"<p style='color:#475569;margin-top:0;font-size:0.9rem'>{subtitle}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<hr style='border:none;border-top:1px solid #1E293B;margin:12px 0 20px'/>",
        unsafe_allow_html=True,
    )

def show_result_card(updated: dict) -> None:
    """Display classification result + updated trust score."""
    st.markdown(
        "<div style='background:rgba(16,185,129,0.10);border:1px solid #10B981;"
        "border-radius:8px;padding:12px 18px;margin-bottom:16px;"
        "color:#6EE7B7;font-size:0.92rem'>"
        "Feedback submitted and processed successfully."
        "</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        delta = updated["score_delta"]
        delta_color = "#10B981" if delta <= 0 else "#F43F5E"
        delta_sign  = "+" if delta < 0 else "-"
        delta_val   = abs(delta)
        st.markdown(
            f"<div style='background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px'>"
            f"<div style='font-size:0.72rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em'>Updated Trust Score</div>"
            f"<div style='font-size:1.6rem;font-weight:700;color:#F8FAFC;margin:6px 0 4px'>"
            f"{updated['trust_score']:.1f} <span style='font-size:0.9rem;color:#475569'>/ 100</span></div>"
            f"<div style='font-size:0.82rem;color:{delta_color}'>{delta_sign}{delta_val:.2f} pts</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div style='background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px'>"
            f"<div style='font-size:0.72rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em'>AI Category</div>"
            f"<div style='margin-top:10px'>{category_badge(updated['ai_category'])}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div style='background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px'>"
            f"<div style='font-size:0.72rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em'>AI Severity</div>"
            f"<div style='margin-top:10px'>{severity_badge(updated['ai_severity'])}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if updated.get("compliance_flag"):
        name = updated.get("supplier_name", updated.get("supplier_id", ""))
        st.markdown(
            f"<div style='background:rgba(244,63,94,0.10);border:1px solid #F43F5E;"
            f"border-radius:8px;padding:12px 18px;margin-top:12px;color:#FDA4AF;font-size:0.9rem'>"
            f"Supplier <strong>{name}</strong> has been flagged for non-compliance "
            f"(trust score below {scoring_engine.COMPLIANCE_THRESHOLD})."
            f"</div>",
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — SELLER FEEDBACK FORM
# ══════════════════════════════════════════════════════════════════════════════

def page_seller_feedback() -> None:
    page_header(
        "Seller Feedback Form",
        "Submit quality feedback about a supplier directly from the seller's perspective.",
    )

    suppliers = db.get_all_suppliers()
    if not suppliers:
        st.error("No suppliers found in the database. Run `python seed_data.py` first.")
        return

    supplier_names = [s["supplier_name"] for s in suppliers]
    supplier_map   = {s["supplier_name"]: s for s in suppliers}

    with st.form("seller_feedback_form", clear_on_submit=True):
        st.markdown(
            "<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
            "letter-spacing:0.08em;font-weight:600;margin-bottom:16px'>Feedback Details</p>",
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            selected_name = st.selectbox("Supplier", supplier_names)
        with col_b:
            invoice_input = st.text_input("Invoice Number (optional)",
                                          placeholder="e.g. INV-2026-001")

        product_input = st.text_input("Product ID (optional)", placeholder="e.g. PROD-001")

        raw_feedback = st.text_area(
            "Feedback",
            height=140,
            placeholder="Describe the quality issue or positive experience...",
        )

        additional_details = st.text_area(
            "Additional Details (optional)",
            height=80,
            placeholder="Batch numbers, test results, photo references, etc.",
        )

        submitted = st.form_submit_button("Submit Feedback", type="primary", use_container_width=True)

    if submitted:
        if not raw_feedback.strip():
            st.error("Feedback text is required.")
            return

        supplier = supplier_map[selected_name]

        invoice_id = None
        if invoice_input.strip():
            resolved_invoice = db.get_invoice_by_number(invoice_input.strip())
            if resolved_invoice is None:
                st.error(f"Invoice **{invoice_input.strip()}** not found. Check the invoice number.")
                return
            invoice_id = resolved_invoice["invoice_id"]

        product_id = product_input.strip() if product_input.strip() else None
        if product_id:
            if db.get_product_by_id(product_id) is None:
                st.error(f"Product **{product_id}** not found in the database.")
                return

        feedback_row = {
            "feedback_id":        f"FB-{uuid.uuid4().hex[:8].upper()}",
            "source_type":        "SELLER",
            "supplier_id":        supplier["supplier_id"],
            "invoice_id":         invoice_id,
            "product_id":         product_id,
            "raw_feedback":       raw_feedback.strip(),
            "additional_details": additional_details.strip(),
            "created_at":         datetime.now(timezone.utc),
        }

        with st.spinner("Classifying feedback and updating trust score..."):
            try:
                updated = scoring_engine.process_feedback(feedback_row)
                updated["supplier_name"] = supplier["supplier_name"]
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
                return

        show_result_card(updated)

    # ── Reference table ──
    st.markdown(
        "<hr style='border:none;border-top:1px solid #1E293B;margin:28px 0 16px'/>"
        "<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
        "letter-spacing:0.08em;font-weight:600;margin-bottom:12px'>Current Supplier Trust Scores</p>",
        unsafe_allow_html=True,
    )
    suppliers_fresh = db.get_all_suppliers()
    score_df = pd.DataFrame([
        {
            "Supplier":    s["supplier_name"],
            "Trust Score": s["trust_score"],
            "Compliance":  "FLAGGED" if s["compliance_flag"] else "OK",
            "GSTIN":       s["gstin"],
        }
        for s in suppliers_fresh
    ])
    st.dataframe(score_df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — CUSTOMER FEEDBACK FORM
# ══════════════════════════════════════════════════════════════════════════════

def page_customer_feedback() -> None:
    page_header(
        "Customer Feedback Form",
        "Submit feedback about a product received on an invoice. "
        "The system will automatically resolve the responsible supplier.",
    )

    with st.form("customer_feedback_form", clear_on_submit=False):
        st.markdown(
            "<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
            "letter-spacing:0.08em;font-weight:600;margin-bottom:16px'>Invoice & Feedback</p>",
            unsafe_allow_html=True,
        )

        invoice_input = st.text_input("Invoice Number", placeholder="e.g. INV-2026-001")

        raw_feedback = st.text_area(
            "Feedback",
            height=140,
            placeholder="Describe the issue or experience with the product(s) received...",
        )

        additional_details = st.text_area(
            "Additional Details (optional)",
            height=80,
            placeholder="Specific product, photos, batch info, etc.",
        )

        submitted = st.form_submit_button("Submit Feedback", type="primary", use_container_width=True)

    if submitted:
        if not invoice_input.strip():
            st.error("Invoice number is required.")
            return
        if not raw_feedback.strip():
            st.error("Feedback text is required.")
            return

        invoice_id_raw = invoice_input.strip()

        invoice = db.get_invoice_by_number(invoice_id_raw)
        if invoice is None:
            st.error(f"Invoice **{invoice_id_raw}** not found. Please check the invoice number.")
            return

        resolved_supplier_id = db.resolve_supplier_from_invoice(invoice_id_raw)

        if resolved_supplier_id is None:
            st.markdown(
                "<div style='background:rgba(245,158,11,0.10);border:1px solid #F59E0B;"
                "border-radius:8px;padding:12px 18px;color:#FCD34D;font-size:0.9rem;margin-bottom:12px'>"
                "Could not automatically resolve the supplier for this invoice. "
                "No matching purchase order was found. Please select the supplier manually."
                "</div>",
                unsafe_allow_html=True,
            )
            suppliers      = db.get_all_suppliers()
            supplier_names = [s["supplier_name"] for s in suppliers]
            manual_name    = st.selectbox("Select Supplier Manually", supplier_names, key="manual_supplier")
            if not manual_name:
                return
            resolved_supplier = next((s for s in suppliers if s["supplier_name"] == manual_name), None)
            if resolved_supplier is None:
                st.error("Selected supplier not found.")
                return
            resolved_supplier_id = resolved_supplier["supplier_id"]
            st.markdown(
                f"<div style='background:rgba(99,102,241,0.10);border:1px solid #6366F1;"
                f"border-radius:8px;padding:10px 16px;color:#A5B4FC;font-size:0.88rem'>"
                f"Using manually selected supplier: <strong>{manual_name}</strong></div>",
                unsafe_allow_html=True,
            )
        else:
            supplier = db.get_supplier_by_id(resolved_supplier_id)
            sname = supplier["supplier_name"] if supplier else resolved_supplier_id
            st.markdown(
                f"<div style='background:rgba(99,102,241,0.10);border:1px solid #6366F1;"
                f"border-radius:8px;padding:10px 16px;color:#A5B4FC;font-size:0.88rem'>"
                f"Supplier resolved from invoice PO chain: "
                f"<strong>{sname}</strong> ({resolved_supplier_id})</div>",
                unsafe_allow_html=True,
            )

        product_ids = db.get_products_for_invoice(invoice_id_raw)
        product_id  = product_ids[0] if product_ids else None

        feedback_row = {
            "feedback_id":        f"FB-{uuid.uuid4().hex[:8].upper()}",
            "source_type":        "CUSTOMER",
            "supplier_id":        resolved_supplier_id,
            "invoice_id":         invoice_id_raw,
            "product_id":         product_id,
            "raw_feedback":       raw_feedback.strip(),
            "additional_details": additional_details.strip(),
            "created_at":         datetime.now(timezone.utc),
        }

        with st.spinner("Classifying feedback and updating trust score..."):
            try:
                updated = scoring_engine.process_feedback(feedback_row)
                supplier_rec = db.get_supplier_by_id(resolved_supplier_id)
                updated["supplier_name"] = supplier_rec["supplier_name"] if supplier_rec else resolved_supplier_id
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
                return

        show_result_card(updated)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — SUPPLIER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def page_supplier_dashboard() -> None:
    page_header(
        "Supplier Dashboard",
        "Monitor trust scores, compliance status, and feedback history for all suppliers.",
    )

    suppliers = db.get_all_suppliers()
    if not suppliers:
        st.error("No suppliers found. Run `python seed_data.py` to load sample data.")
        return

    # ── Reprocess corrupted fallback entries ─────────────────────────────────
    with st.expander("Fix historical feedback (re-classify any unscored entries)", expanded=False):
        st.markdown(
            "<p style='color:#94A3B8;font-size:0.88rem;margin:0 0 10px'>Re-runs AI classification on any feedback row that was stored as "
            "<code>Other / LOW / 0.00 delta</code> due to a model error, then replays all rows to "
            "recompute the correct trust score for every supplier.</p>",
            unsafe_allow_html=True,
        )
        reprocess_col1, reprocess_col2 = st.columns([1, 3])
        with reprocess_col1:
            do_reprocess = st.button("Reprocess All Feedback", type="primary", use_container_width=True)
        if do_reprocess:
            with st.spinner("Re-classifying and recomputing all supplier scores..."):
                try:
                    summary = scoring_engine.reprocess_all_feedback()
                    n = summary["total_reclassified"]
                    st.markdown(
                        f"<div style='background:rgba(16,185,129,0.10);border:1px solid #10B981;"
                        f"border-radius:8px;padding:12px 18px;color:#6EE7B7;font-size:0.9rem'>"
                        f"Done. Re-classified <strong>{n}</strong> previously unscored "
                        f"feedback entries and recomputed all trust scores."
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    # Show per-supplier summary
                    rp_rows = [
                        {
                            "Supplier":         r["supplier_name"],
                            "Entries Fixed":    r["reclassified"],
                            "New Trust Score":  r["new_score"],
                            "Compliance":       "FLAGGED" if r["compliance_flag"] else "OK",
                        }
                        for r in summary["suppliers"]
                    ]
                    st.dataframe(pd.DataFrame(rp_rows), use_container_width=True, hide_index=True)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Reprocess failed: {exc}")

    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)

    # ── Summary cards ─────────────────────────────────────────────────────────
    st.markdown(
        "<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
        "letter-spacing:0.08em;font-weight:600;margin-bottom:14px'>All Suppliers</p>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(suppliers))
    for col, s in zip(cols, suppliers):
        score = s["trust_score"]
        score_color = "#10B981" if score >= 70 else ("#F59E0B" if score >= 40 else "#F43F5E")
        compliance_html = (
            "<span style='color:#F43F5E;font-size:0.75rem;font-weight:600'>FLAGGED</span>"
            if s["compliance_flag"]
            else "<span style='color:#10B981;font-size:0.75rem;font-weight:600'>OK</span>"
        )
        sname = s["supplier_name"]
        with col:
            st.markdown(
                f"<div style='background:#0F172A;border:1px solid #1E293B;border-radius:10px;"
                f"padding:16px;text-align:center'>"
                f"<div style='font-size:0.75rem;color:#475569;margin-bottom:6px;white-space:nowrap;"
                f"overflow:hidden;text-overflow:ellipsis' title='{sname}'>"
                f"{sname}</div>"
                f"<div style='font-size:1.8rem;font-weight:700;color:{score_color}'>{score:.0f}</div>"
                f"<div style='font-size:0.68rem;color:#334155;margin-bottom:4px'>Trust Score</div>"
                f"{compliance_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin:24px 0'></div>", unsafe_allow_html=True)

    # ── Full table ─────────────────────────────────────────────────────────────
    summary_rows = []
    for s in suppliers:
        score = s["trust_score"]
        summary_rows.append({
            "Supplier":    s["supplier_name"],
            "Trust Score": score,
            "Compliance":  "FLAGGED" if s["compliance_flag"] else "OK",
            "GSTIN":       s["gstin"],
            "Email":       s["contact_email"],
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown(
        "<hr style='border:none;border-top:1px solid #1E293B;margin:28px 0 20px'/>",
        unsafe_allow_html=True,
    )

    # ── Drill-down ─────────────────────────────────────────────────────────────
    st.markdown(
        "<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
        "letter-spacing:0.08em;font-weight:600;margin-bottom:10px'>Drill Down into a Supplier</p>",
        unsafe_allow_html=True,
    )

    supplier_options = {s["supplier_name"]: s["supplier_id"] for s in suppliers}
    selected_name    = st.selectbox("Select Supplier", list(supplier_options.keys()), key="dash_select")

    if not selected_name:
        return

    selected_id = supplier_options[selected_name]
    supplier    = db.get_supplier_by_id(selected_id)
    if not supplier:
        st.error("Supplier not found.")
        return

    # KPI strip
    k1, k2, k3, k4 = st.columns(4)
    score = supplier["trust_score"]
    score_color = "#10B981" if score >= 70 else ("#F59E0B" if score >= 40 else "#F43F5E")
    for col, label, value, vcolor in [
        (k1, "Trust Score", f"{score:.1f} / 100", score_color),
        (k2, "Compliance",  "FLAGGED" if supplier["compliance_flag"] else "OK",
             "#F43F5E" if supplier["compliance_flag"] else "#10B981"),
        (k3, "GSTIN",       supplier["gstin"],        "#CBD5E1"),
        (k4, "Contact",     supplier["contact_email"], "#CBD5E1"),
    ]:
        with col:
            st.markdown(
                f"<div style='background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px'>"
                f"<div style='font-size:0.72rem;color:#64748B;text-transform:uppercase;"
                f"letter-spacing:0.05em;margin-bottom:6px'>{label}</div>"
                f"<div style='font-size:1.05rem;font-weight:700;color:{vcolor}'>{value}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin:20px 0'></div>", unsafe_allow_html=True)

    # ── Trust score chart ─────────────────────────────────────────────────────
    st.markdown(
        f"<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
        f"letter-spacing:0.08em;font-weight:600;margin-bottom:8px'>"
        f"Trust Score History — {selected_name}</p>",
        unsafe_allow_html=True,
    )

    history = db.get_score_history(selected_id)
    if len(history) < 2:
        st.markdown(
            "<div style='background:rgba(99,102,241,0.10);border:1px solid #6366F1;"
            "border-radius:8px;padding:12px 18px;color:#A5B4FC;font-size:0.9rem'>"
            "Not enough feedback entries to plot a trend (need at least 2)."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        chart_df = pd.DataFrame(history)
        chart_df["created_at"] = pd.to_datetime(chart_df["created_at"])
        chart_df = chart_df.set_index("created_at").sort_index()
        chart_df.columns = ["Trust Score"]
        st.line_chart(chart_df, use_container_width=True, color="#6366F1")

    st.markdown(
        "<hr style='border:none;border-top:1px solid #1E293B;margin:24px 0 16px'/>",
        unsafe_allow_html=True,
    )

    # ── Feedback history ──────────────────────────────────────────────────────
    st.markdown(
        f"<p style='font-size:0.78rem;color:#6366F1;text-transform:uppercase;"
        f"letter-spacing:0.08em;font-weight:600;margin-bottom:10px'>"
        f"Feedback History — {selected_name}</p>",
        unsafe_allow_html=True,
    )

    feedback_list = db.get_feedback_for_supplier(selected_id)
    if not feedback_list:
        st.markdown(
            "<div style='background:rgba(99,102,241,0.10);border:1px solid #6366F1;"
            "border-radius:8px;padding:12px 18px;color:#A5B4FC;font-size:0.9rem'>"
            "No feedback recorded yet for this supplier."
            "</div>",
            unsafe_allow_html=True,
        )
        return

    fb_rows = []
    for fb in feedback_list:
        created = fb.get("created_at")
        created_str = created.strftime("%Y-%m-%d %H:%M UTC") if isinstance(created, datetime) else str(created)
        delta     = fb.get("score_delta", 0.0)
        delta_str = f"{-delta:+.2f}" if delta != 0 else "0.00"
        fb_rows.append({
            "Date":      created_str,
            "Source":    fb.get("source_type", ""),
            "Category":  category_label(fb.get("ai_category", "OTHER")),
            "Severity":  fb.get("ai_severity", "LOW"),
            "Score Delta": delta_str,
            "Invoice":   fb.get("invoice_id") or "-",
            "Product":   fb.get("product_id") or "-",
            "Feedback":  (fb.get("raw_feedback") or "")[:120] + (
                          "..." if len(fb.get("raw_feedback") or "") > 120 else ""
                        ),
        })

    st.dataframe(pd.DataFrame(fb_rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

if PAGE == "Seller Feedback":
    page_seller_feedback()
elif PAGE == "Customer Feedback":
    page_customer_feedback()
elif PAGE == "Supplier Dashboard":
    page_supplier_dashboard()
