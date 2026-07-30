"""
dashboard/app.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unified Streamlit Dashboard — Single-Page Sequential Flow

  Section 0  — Sidebar controls (System Control / BI / About pages)
  Section 1  — Agent 1: Demand forecast + stock details + Proceed button
  Section 2  — Agent 2: Categories × Seller details + Send-All-Mails button
               (user identity form collected once before sending)
  Section 3  — Agent 3: Confirmation results + auto-refresh slider
               + manual refresh + e-invoice email fetch → audit agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io, math, json, uuid, time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

# ─── Streamlit page config ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Integrated Supply Chain Platform",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Global CSS — Obsidian dark theme ────────────────────────────────────────
st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"]{background:#090D16;color:#E2E8F0;font-family:'Inter',sans-serif}
[data-testid="stSidebar"]{background:#0F172A;border-right:1px solid #1E293B}
[data-testid="stSidebar"] *{color:#CBD5E1!important}
h1{color:#F8FAFC!important;font-size:1.6rem!important;font-weight:700!important}
h2{color:#CBD5E1!important;font-size:1.15rem!important;font-weight:600!important}
h3{color:#94A3B8!important}
hr{border-color:#1E293B!important}
[data-testid="metric-container"]{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:14px 18px!important}
[data-testid="stMetricLabel"]{color:#64748B!important;font-size:0.75rem!important;text-transform:uppercase;letter-spacing:0.05em}
[data-testid="stMetricValue"]{color:#F8FAFC!important;font-size:1.45rem!important;font-weight:700!important}
.stDataFrame{border:1px solid #1E293B;border-radius:8px}
.stSuccess{background:rgba(16,185,129,.12)!important;border-left:3px solid #10B981!important;color:#6EE7B7!important}
.stError{background:rgba(244,63,94,.12)!important;border-left:3px solid #F43F5E!important;color:#FDA4AF!important}
.stWarning{background:rgba(245,158,11,.12)!important;border-left:3px solid #F59E0B!important;color:#FCD34D!important}
.stInfo{background:rgba(99,102,241,.12)!important;border-left:3px solid #6366F1!important;color:#A5B4FC!important}
[data-testid="baseButton-primary"]{background:linear-gradient(135deg,#6366F1,#4F46E5)!important;color:#fff!important;border:none!important;border-radius:6px!important;font-weight:600!important}
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea{background:#0F172A!important;color:#E2E8F0!important;border:1px solid #334155!important;border-radius:6px!important}
label,[data-testid="stWidgetLabel"]{color:#94A3B8!important;font-size:.8rem!important;text-transform:uppercase!important;letter-spacing:.04em!important}
.sv-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:.75rem;font-weight:600;letter-spacing:.04em}
.sv-green{background:rgba(16,185,129,.15);color:#10B981;border:1px solid rgba(16,185,129,.3)}
.sv-red{background:rgba(244,63,94,.15);color:#F43F5E;border:1px solid rgba(244,63,94,.3)}
.sv-amber{background:rgba(245,158,11,.15);color:#F59E0B;border:1px solid rgba(245,158,11,.3)}
.sv-indigo{background:rgba(99,102,241,.15);color:#6366F1;border:1px solid rgba(99,102,241,.3)}
.sv-card{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px 20px;margin-bottom:12px}
.agent-header{background:linear-gradient(135deg,#0F172A,#131C2E);border:1px solid #1E293B;
  border-left:4px solid #6366F1;border-radius:12px;padding:18px 24px;margin-bottom:20px}
.step-connector{text-align:center;color:#334155;font-size:1.4rem;margin:8px 0 16px}
</style>""", unsafe_allow_html=True)

# ─── Agent service bootstrap (register once per session) ─────────────────────
@st.cache_resource(show_spinner=False)
def _boot_services():
    from agents.supply_chain    import register_with_supervisor as r1
    from agents.rfq_matcher     import register_with_supervisor as r2
    from agents.quote_evaluator import register_with_supervisor as r3
    from agents.invoice_auditor import register_with_supervisor as r4
    from agents.vendor_quality  import register_with_supervisor as r5
    from agents.bi_analytics    import register_with_supervisor as r6
    from orchestrator.supervisor import get_supervisor
    svc1 = r1(); svc2 = r2(); svc3 = r3()
    svc4 = r4(); svc5 = r5(); svc6 = r6()
    sv   = get_supervisor()
    return sv, svc1, svc2, svc3, svc4, svc5, svc6

sv, svc1, svc2, svc3, svc4, svc5, svc6 = _boot_services()

# ─── DB connectivity guard ────────────────────────────────────────────────────
from core.db import ping
if not ping():
    st.error("Cannot connect to MongoDB. Check MONGO_URI in your .env file.")
    st.stop()

# ─── Shared helpers ───────────────────────────────────────────────────────────
def _badge(text: str, cls: str) -> str:
    return f"<span class='sv-badge {cls}'>{text}</span>"

def _status_badge(status: str) -> str:
    MAP = {"SUCCESS":"sv-green","FAILED":"sv-red","IN_PROGRESS":"sv-indigo",
           "PENDING":"sv-amber","FLAGGED":"sv-amber","PASSED":"sv-green",
           "FLAGGED_WITH_ISSUES":"sv-red","OK":"sv-green"}
    return _badge(status, MAP.get(status, "sv-indigo"))

def _score_colour(score: float) -> str:
    return "#10B981" if score >= 70 else ("#F59E0B" if score >= 40 else "#F43F5E")

def _section(title: str) -> None:
    st.markdown(
        f"<p style='font-size:.76rem;color:#6366F1;text-transform:uppercase;"
        f"letter-spacing:.08em;font-weight:600;margin:18px 0 8px'>{title}</p>",
        unsafe_allow_html=True)

def _card(content_html: str) -> None:
    st.markdown(f"<div class='sv-card'>{content_html}</div>", unsafe_allow_html=True)

def _agent_header(num: str, title: str, subtitle: str, icon: str = "") -> None:
    st.markdown(
        f"<div class='agent-header'>"
        f"<div style='font-size:.7rem;color:#6366F1;text-transform:uppercase;"
        f"letter-spacing:.1em;font-weight:700'>AGENT {num}</div>"
        f"<div style='font-size:1.25rem;font-weight:700;color:#F8FAFC;margin:4px 0 2px'>"
        f"{icon} {title}</div>"
        f"<div style='font-size:.8rem;color:#64748B'>{subtitle}</div>"
        f"</div>", unsafe_allow_html=True)

def _step_arrow() -> None:
    st.markdown("<div class='step-connector'>▼</div>", unsafe_allow_html=True)

# ─── Sidebar navigation ───────────────────────────────────────────────────────
st.sidebar.markdown(
    "<div style='padding:14px 0 6px 4px'>"
    "<span style='font-size:1.1rem;font-weight:700;color:#F8FAFC'>🏭 Supply Chain Hub</span>"
    "<br><span style='font-size:.75rem;color:#475569'>7-Agent Integrated Platform</span>"
    "</div>", unsafe_allow_html=True)
st.sidebar.divider()

PAGES = [
    "🔄 Procurement Pipeline",
    "🎛️ System Control Centre",
    "🧾 Invoice Auditor",
    "⭐ Vendor Quality",
    "📊 BI Analytics",
    "ℹ️ About",
]
active_page = st.sidebar.radio("Navigate", PAGES, label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("Powered by Groq + MongoDB + LangChain")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: SYSTEM CONTROL CENTRE
# ═══════════════════════════════════════════════════════════════════════════════
if active_page == PAGES[1]:
    st.title("🎛️ System Control Centre")
    st.caption("Real-time Supervisor state, workflow engine, and inter-agent message log.")
    from orchestrator.logger import get_recent_logs, get_system_health
    health   = get_system_health()
    s_counts = health.get("status_counts", {})
    wf_all   = sv.get_all_workflows()
    wf_active = sv.get_active_workflows()
    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Total Events",    health.get("total_events", 0))
    k2.metric("Active Workflows", len(wf_active))
    k3.metric("Total Workflows",  len(wf_all))
    k4.metric("Successful",  s_counts.get("SUCCESS", 0))
    k5.metric("Failed / Flagged", s_counts.get("FAILED", 0) + s_counts.get("FLAGGED", 0))
    st.divider()
    _section("Manual Pipeline Trigger")
    with st.form("trigger_form"):
        trigger_note = st.text_input("Trigger Notes", value="Manual dashboard trigger")
        if st.form_submit_button("🚀 Trigger Full Pipeline", type="primary"):
            wf_id = sv.trigger_pipeline(notes=trigger_note)
            st.success(f"Pipeline triggered — workflow_id: **{wf_id}**")
    st.divider()
    _section("Workflow States")
    if wf_all:
        df_wf = pd.DataFrame([
            {"workflow_id": w["workflow_id"], "initiated_by": w["initiated_by"],
             "status": w["status"], "steps": len(w["steps"]),
             "created_at": w["created_at"][:19], "updated_at": w["updated_at"][:19]}
            for w in sorted(wf_all, key=lambda x: x["updated_at"], reverse=True)
        ])
        st.dataframe(df_wf, use_container_width=True, hide_index=True)
    else:
        st.info("No workflows recorded yet.")
    st.divider()
    recent_errors = health.get("recent_errors", [])
    if recent_errors:
        _section("Recent Errors")
        for err in recent_errors:
            st.error(f"**{err.get('source_agent')}** | {err.get('payload_type')} "
                     f"| {err.get('timestamp','')[:19]} — {err.get('error','')}")
    _section("Inter-Agent Message Log (last 150 events)")
    log_limit = st.slider("Entries to show", 10, 150, 50, key="log_slider")
    logs = get_recent_logs(limit=log_limit)
    if logs:
        df_logs = pd.DataFrame([
            {"log_id": l.get("log_id","")[:14], "timestamp": str(l.get("timestamp",""))[:19],
             "workflow_id": l.get("workflow_id","")[:12], "payload_type": l.get("payload_type",""),
             "source": l.get("source_agent",""), "target": l.get("target_agent",""),
             "status": l.get("status",""), "error": (l.get("error") or "")[:60]}
            for l in logs
        ])
        st.dataframe(df_logs, use_container_width=True, hide_index=True)
        if st.checkbox("Show full payload JSON for selected log"):
            log_ids = [l.get("log_id","") for l in logs]
            sel = st.selectbox("Select log_id", log_ids, key="log_sel")
            selected_log = next((l for l in logs if l.get("log_id") == sel), None)
            if selected_log:
                st.json(selected_log.get("payload", {}))
    else:
        st.info("No log entries yet.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: INVOICE AUDITOR (Agent 4)
# ═══════════════════════════════════════════════════════════════════════════════
elif active_page == PAGES[2]:
    st.title("🧾 Agent 4 — Invoice Auditor")
    st.caption(
        "Displays all e-invoices extracted from supplier reply emails and audited by Agent 4. "
        "The chatbot answers questions only about these invoices."
    )
    from core.db import col as db_col
    from agents.invoice_auditor import get_invoice_audit_results, get_audit_chatbot_response

    t4a, t4b = st.tabs(["📋 Audit Results", "💬 Invoice Chatbot"])

    # ── Tab A: Audit results table from invoice_audit_results ────────────────
    with t4a:
        _section("Audited Invoices (from einvoice_store)")

        # Live counts
        total_stored   = db_col("einvoice_store").count_documents({})
        total_audited  = db_col("invoice_audit_results").count_documents({})
        total_pending  = db_col("einvoice_store").count_documents({"audited": False})

        m1, m2, m3 = st.columns(3)
        m1.metric("PDFs in MongoDB",       total_stored)
        m2.metric("Invoices Audited",       total_audited)
        m3.metric("Pending Audit",          total_pending)

        st.divider()

        audit_records = get_invoice_audit_results()
        if not audit_records:
            st.info(
                "No invoices have been audited yet. "
                "Complete the procurement pipeline (Agents 1→2→3) to collect "
                "e-invoices from suppliers, then trigger Agent 4."
            )
        else:
            # Summary table
            rows = []
            for r in audit_records:
                rows.append({
                    "Invoice #":        r.get("invoice_number", "—"),
                    "Supplier":         r.get("supplier_name", "—"),
                    "Email":            r.get("supplier_email", "—"),
                    "Total (₹)":        f"₹{r.get('total_cost', 0):,.2f}",
                    "Items":            len(r.get("items", [])),
                    "Audit Status":     r.get("audit_status", "—"),
                    "Discrepancies":    len(r.get("discrepancies", [])),
                    "Passed Checks":    len(r.get("passed_checks", [])),
                    "Audited At":       str(r.get("audited_at", ""))[:19],
                    "Source File":      r.get("filename", "—"),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.divider()

            # Drill-down per invoice
            _section("Invoice Details")
            inv_numbers = [r.get("invoice_number", "—") for r in audit_records]
            selected_inv = st.selectbox("Select Invoice", inv_numbers, key="a4_inv_select")
            selected_rec = next(
                (r for r in audit_records if r.get("invoice_number") == selected_inv), None
            )
            if selected_rec:
                ic1, ic2, ic3 = st.columns(3)
                ic1.metric("Supplier",    selected_rec.get("supplier_name", "—"))
                ic2.metric("Total Cost",  f"₹{selected_rec.get('total_cost', 0):,.2f}")
                ic3.metric("Status",      selected_rec.get("audit_status", "—"))

                items = selected_rec.get("items", [])
                if items:
                    _section("Line Items")
                    st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)

                disc = selected_rec.get("discrepancies", [])
                chks = selected_rec.get("passed_checks", [])
                dc1, dc2 = st.columns(2)
                with dc1:
                    _section("Discrepancies")
                    if disc:
                        for d in disc:
                            desc = d.get("description", str(d)) if isinstance(d, dict) else str(d)
                            sev  = d.get("severity", "WARNING") if isinstance(d, dict) else "WARNING"
                            if sev == "CRITICAL":
                                st.error(f"🔴 {desc}")
                            else:
                                st.warning(f"🟡 {desc}")
                    else:
                        st.success("No discrepancies found.")
                with dc2:
                    _section("Passed Checks")
                    if chks:
                        for chk in chks:
                            st.success(f"✅ {chk}")
                    else:
                        st.info("No passed checks recorded.")

    # ── Tab B: Chatbot — only answers questions about invoice_audit_results ───
    with t4b:
        _section("Invoice Audit Chatbot")
        st.caption(
            "Ask questions about the audited invoices — invoice numbers, supplier details, "
            "discrepancies, cost mismatches, etc. "
            "This chatbot only has access to audited invoice data, nothing else."
        )

        if "a4_msgs" not in st.session_state:
            st.session_state["a4_msgs"] = []

        # Display conversation history
        for msg in st.session_state["a4_msgs"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_q = st.chat_input(
            "e.g. Which invoices were flagged? Show me all discrepancies for invoice INV-001."
        )
        if user_q:
            st.session_state["a4_msgs"].append({"role": "user", "content": user_q})
            with st.chat_message("user"):
                st.markdown(user_q)
            with st.spinner("Searching audit records…"):
                ans = get_audit_chatbot_response(st.session_state["a4_msgs"])
            st.session_state["a4_msgs"].append({"role": "assistant", "content": ans})
            with st.chat_message("assistant"):
                st.markdown(ans)

        if st.session_state["a4_msgs"]:
            if st.button("🗑️ Clear conversation", key="a4_clear"):
                st.session_state["a4_msgs"] = []
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: VENDOR QUALITY (Agent 5)
# ═══════════════════════════════════════════════════════════════════════════════
elif active_page == PAGES[3]:
    st.title("⭐ Agent 5 — Vendor Quality Scoring")
    st.caption("Submit seller/customer feedback. Groq LLM classifies; deterministic PENALTY_TABLE scores suppliers.")
    from agents.vendor_quality import (get_all_suppliers, get_supplier_by_id,
                                       get_score_history, reprocess_all_feedback,
                                       COMPLIANCE_THRESHOLD)
    t5a, t5b, t5c = st.tabs(["Seller Feedback", "Customer Feedback", "Supplier Dashboard"])
    with t5a:
        _section("Submit Seller Feedback")
        suppliers = get_all_suppliers()
        if not suppliers:
            st.error("No suppliers found. Seed data first.")
        else:
            sup_map  = {s["supplier_name"]: s for s in suppliers}
            with st.form("a5_seller_form", clear_on_submit=True):
                sel_name  = st.selectbox("Supplier", list(sup_map.keys()), key="a5s_sup")
                inv_in    = st.text_input("Invoice # (optional)", key="a5s_inv")
                prod_in   = st.text_input("Product ID (optional)", key="a5s_prod")
                feedback  = st.text_area("Feedback", height=120, key="a5s_fb")
                extra     = st.text_area("Additional Details (optional)", height=80, key="a5s_ext")
                submitted = st.form_submit_button("Submit Feedback", type="primary", use_container_width=True)
            if submitted:
                if not feedback.strip():
                    st.error("Feedback text is required.")
                else:
                    sup = sup_map[sel_name]
                    with st.spinner("Classifying & scoring…"):
                        result = svc5.submit_feedback(
                            source_type="SELLER", supplier_id=sup["supplier_id"],
                            raw_feedback=feedback, additional_details=extra,
                            invoice_id=inv_in.strip() or None,
                            product_id=prod_in.strip() or None,
                        )
                    c1,c2,c3 = st.columns(3)
                    c1.metric("Updated Trust Score", f"{result['trust_score']:.1f} / 100")
                    c2.metric("AI Category",  result["ai_category"])
                    c3.metric("Score Delta",  f"{result['score_delta']:+.2f}")
                    if result["compliance_flag"]:
                        st.error(f"⚠️ Supplier flagged (score < {COMPLIANCE_THRESHOLD})")
                    else:
                        st.success("Feedback processed.")
    with t5b:
        _section("Submit Customer Feedback")
        with st.form("a5_cust_form", clear_on_submit=False):
            inv_num  = st.text_input("Invoice Number", placeholder="INV-2026-001", key="a5c_inv")
            feedback = st.text_area("Feedback", height=120, key="a5c_fb")
            extra    = st.text_area("Additional Details (optional)", height=80, key="a5c_ext")
            csub     = st.form_submit_button("Submit Feedback", type="primary", use_container_width=True)
        if csub:
            if not inv_num.strip() or not feedback.strip():
                st.error("Invoice number and feedback are required.")
            else:
                from agents.vendor_quality import resolve_supplier_from_invoice
                sup_id = resolve_supplier_from_invoice(inv_num.strip())
                if not sup_id:
                    st.warning("Could not auto-resolve supplier from invoice. Check PO chain.")
                else:
                    sup_doc = get_supplier_by_id(sup_id) or {}
                    st.info(f"Resolved supplier: **{sup_doc.get('supplier_name', sup_id)}** ({sup_id})")
                    with st.spinner("Classifying & scoring…"):
                        result = svc5.submit_feedback(
                            source_type="CUSTOMER", supplier_id=sup_id,
                            raw_feedback=feedback, additional_details=extra,
                            invoice_id=inv_num.strip(),
                        )
                    c1,c2,c3 = st.columns(3)
                    c1.metric("Updated Trust Score", f"{result['trust_score']:.1f} / 100")
                    c2.metric("AI Category",  result["ai_category"])
                    c3.metric("Score Delta",  f"{result['score_delta']:+.2f}")
    with t5c:
        _section("All Suppliers")
        suppliers_fresh = get_all_suppliers()
        if not suppliers_fresh:
            st.info("No suppliers found.")
        else:
            cols = st.columns(min(len(suppliers_fresh), 5))
            for col, s in zip(cols, suppliers_fresh):
                sc  = s["trust_score"]; clr = _score_colour(sc)
                with col:
                    st.markdown(
                        f"<div class='sv-card' style='text-align:center'>"
                        f"<div style='font-size:.75rem;color:#475569'>{s['supplier_name']}</div>"
                        f"<div style='font-size:1.7rem;font-weight:700;color:{clr}'>{sc:.0f}</div>"
                        f"<div style='font-size:.65rem;color:#334155'>Trust Score</div>"
                        f"{'<span class=\"sv-badge sv-red\">FLAGGED</span>' if s['compliance_flag'] else '<span class=\"sv-badge sv-green\">OK</span>'}"
                        f"</div>", unsafe_allow_html=True)
            st.divider()
            sel_sup = st.selectbox("Select Supplier", [s["supplier_name"] for s in suppliers_fresh], key="a5_drill")
            drill   = next(s for s in suppliers_fresh if s["supplier_name"] == sel_sup)
            k1,k2,k3,k4 = st.columns(4)
            k1.metric("Trust Score",  f"{drill['trust_score']:.1f}")
            k2.metric("Compliance",   "FLAGGED" if drill["compliance_flag"] else "OK")
            k3.metric("GSTIN",        drill.get("gstin","—"))
            k4.metric("Email",        drill.get("contact_email","—"))
            hist = get_score_history(drill["supplier_id"])
            if len(hist) >= 2:
                chart_df = pd.DataFrame(hist)
                chart_df["created_at"] = pd.to_datetime(chart_df["created_at"])
                chart_df = chart_df.set_index("created_at").sort_index()
                chart_df.columns = ["Trust Score"]
                st.line_chart(chart_df, use_container_width=True, color="#6366F1")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: BI ANALYTICS (Agent 6)
# ═══════════════════════════════════════════════════════════════════════════════
elif active_page == PAGES[4]:
    st.title("📊 Agent 6 — Profit Analytics & Conversational BI")
    st.caption(
        "Type any question in plain English → Groq generates a MongoDB aggregation pipeline "
        "→ live data fetched from DB → AI picks the best chart type → rendered instantly."
    )

    from core.db import col as _bi_col

    # ── Session state — no hardcoded data ────────────────────────────────────
    if "bi_result" not in st.session_state:
        st.session_state["bi_result"] = None   # None = not yet queried
    if "bi_loading" not in st.session_state:
        st.session_state["bi_loading"] = False

    def _run_bi_query(q: str) -> None:
        st.session_state["bi_loading"] = True
        with st.spinner(f"Groq → MQL → MongoDB → Chart…"):
            try:
                res = svc6.process_query(q)
                st.session_state["bi_result"] = res
            except Exception as ex:
                st.session_state["bi_result"] = {"error": str(ex)}
        st.session_state["bi_loading"] = False

    # ── DB health bar ─────────────────────────────────────────────────────────
    try:
        inv_count   = _bi_col("sales_invoices").count_documents({})
        prod_count  = _bi_col("products").count_documents({})
        sup_count   = _bi_col("suppliers").count_documents({})
    except Exception:
        inv_count = prod_count = sup_count = 0

    db1, db2, db3 = st.columns(3)
    db1.metric("Sales Invoices in DB",  inv_count)
    db2.metric("Products in DB",        prod_count)
    db3.metric("Suppliers in DB",       sup_count)

    if inv_count == 0:
        st.warning(
            "⚠️ No sales invoices found in the database. "
            "The BI agent queries `sales_invoices` for profit/revenue data. "
            "Add invoice records to see results."
        )

    st.divider()

    # ── Quick query chips ─────────────────────────────────────────────────────
    _section("Quick Queries — click to run against live DB")
    qc1, qc2, qc3, qc4 = st.columns(4)
    if qc1.button("📈 Profit by Product",      key="bi_q1"):
        _run_bi_query("Show profit breakdown by product sorted by profit descending")
        st.rerun()
    if qc2.button("📊 Revenue by Category",    key="bi_q2"):
        _run_bi_query("Total revenue and profit breakdown by product category")
        st.rerun()
    if qc3.button("🏆 Top 5 by Units Sold",    key="bi_q3"):
        _run_bi_query("Top 5 products by units sold")
        st.rerun()
    if qc4.button("📉 Low Margin Products",    key="bi_q4"):
        _run_bi_query("Products with the lowest profit margin sorted ascending")
        st.rerun()

    # ── Custom query input ────────────────────────────────────────────────────
    with st.form("bi_form", clear_on_submit=False):
        q_in  = st.text_input(
            "Ask anything about your sales, profit, or product performance…",
            placeholder="e.g. Which category made the most profit last month?",
            key="bi_q_input",
        )
        qsub = st.form_submit_button("🔍 Analyse", type="primary", use_container_width=True)
    if qsub and q_in.strip():
        _run_bi_query(q_in.strip())
        st.rerun()

    st.divider()

    # ── Results ───────────────────────────────────────────────────────────────
    res = st.session_state.get("bi_result")

    if res is None:
        # Nothing queried yet
        st.markdown(
            "<div style='text-align:center;padding:40px 0;color:#334155'>"
            "<div style='font-size:2.5rem'>📊</div>"
            "<div style='font-size:1rem;margin-top:8px'>No query run yet.</div>"
            "<div style='font-size:.85rem;margin-top:4px'>Click a Quick Query above or type your own question.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    elif "error" in res:
        st.error(f"Query failed: {res['error']}")
    else:
        table_data  = res.get("table_data",  [])
        summary     = res.get("summary",     "")
        mql         = res.get("mql_executed", [])
        chart_cfg   = res.get("chart_config", {})

        if not table_data:
            st.warning(
                "The query ran successfully but returned no data. "
                "Try a broader question, or check that the relevant collections are populated."
            )
            st.caption("MQL executed:")
            st.json(mql)
        else:
            # ── KPI bar from real data ─────────────────────────────────────
            total_rev    = 0.0
            total_profit = 0.0
            for row in table_data:
                qty   = float(row.get("units_sold", 0) or 0)
                sp    = float(row.get("selling_price", 0) or 0)
                prof  = float(row.get("profit") or row.get("total_profit", 0) or 0)
                rev   = float(row.get("total_revenue", 0) or 0)
                total_profit += prof
                total_rev    += rev if rev else (sp * max(qty, 1))
            if total_rev == 0 and total_profit > 0:
                total_rev = total_profit / 0.3   # rough estimate if revenue not in result
            avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0.0

            m1, m2, m3 = st.columns(3)
            m1.metric("Total Revenue (result)",  f"₹{total_rev:,.2f}")
            m2.metric("Total Profit (result)",   f"₹{total_profit:,.2f}")
            m3.metric("Avg Margin (result)",     f"{avg_margin:.1f}%")

            st.divider()

            # ── Chart + AI insight ─────────────────────────────────────────
            col_vis, col_sum = st.columns([3, 2])

            with col_vis:
                _section(f"Chart — {chart_cfg.get('type', 'bar').title()}")
                from agents.bi_analytics import render_seaborn_chart
                import matplotlib.pyplot as plt
                df_chart = pd.DataFrame(table_data)
                fig = render_seaborn_chart(df_chart.copy(), chart_cfg)
                if fig:
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)
                    st.caption(
                        f"Chart type **{chart_cfg.get('type','bar')}** — "
                        f"x: `{chart_cfg.get('x_axis') or chart_cfg.get('names','')}` "
                        f"y: `{chart_cfg.get('y_axis') or chart_cfg.get('values','')}`"
                    )
                else:
                    st.dataframe(df_chart, use_container_width=True, hide_index=True)

            with col_sum:
                _section("AI Executive Insight")
                st.markdown(
                    f"<div style='background:#151D2A;border-left:4px solid #6366F1;"
                    f"border-radius:12px;padding:20px;height:100%'>"
                    f"<div style='color:#E5E7EB;font-size:.95rem;line-height:1.7'>{summary}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # ── MQL toggle (not nested expander, uses session state) ───────
            mql_key = "show_mql"
            if mql_key not in st.session_state:
                st.session_state[mql_key] = False
            mql_lbl = "▲ Hide Generated MQL" if st.session_state[mql_key] else "▼ View Generated MQL"
            if st.button(mql_lbl, key="mql_toggle"):
                st.session_state[mql_key] = not st.session_state[mql_key]
                st.rerun()
            if st.session_state[mql_key]:
                st.json(mql)

            st.divider()

            # ── Data grid ─────────────────────────────────────────────────
            _section("Data Grid (live from MongoDB)")
            df_tbl = pd.DataFrame(table_data).drop(columns=["_id"], errors="ignore")
            # Sort by best numeric column descending
            num_cols = [c for c in df_tbl.columns if pd.api.types.is_numeric_dtype(df_tbl[c])]
            sort_col = next(
                (c for c in num_cols if any(k in c.lower()
                 for k in ["profit", "revenue", "margin", "amount"])),
                num_cols[0] if num_cols else None,
            )
            if sort_col:
                df_tbl = df_tbl.sort_values(sort_col, ascending=False)
            st.dataframe(df_tbl, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Export CSV",
                df_tbl.to_csv(index=False).encode(),
                f"bi_export_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
            )

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
elif active_page == PAGES[5]:
    st.title("ℹ️ About — Integrated Supply Chain Platform")
    st.markdown("""
## Architecture: Hub-and-Spoke via Supervisor Orchestrator

All agents communicate **exclusively** through the **Supervisor (Agent 7)**.

```
                ┌─────────────────────────────┐
                │   7. SUPERVISOR ORCHESTRATOR │
                └──────────────┬──────────────┘
     ┌─────────┬───────────────┼───────────────┬─────────┐
     ▼         ▼               ▼               ▼         ▼
 Agent 1    Agent 2         Agent 3         Agent 4   Agent 5
 Supply     RFQ             Quote           Invoice   Vendor
 Chain      Matcher         Evaluator       Auditor   Quality
```

## Execution Sequence (Procurement Pipeline page)

| Step | Action |
|------|--------|
| 1 | Agent 1 runs 30-day stock simulation → demand list |
| 2 | Agent 2 groups by category, matches DB sellers, sends all RFQ emails |
| 3 | Agent 3 fetches replies, parses quotes, awards PO, sends confirmation asking for PDF e-invoice |
| 4 | System polls inbox for e-invoice PDFs and auto-routes them to Agent 4 (Invoice Auditor) |
""")
    _section("Runtime Status")
    from core.db import ping as _ping2
    from core.config import settings as _s
    c1,c2,c3 = st.columns(3)
    c1.metric("MongoDB", "✅ Connected" if _ping2() else "❌ Unreachable")
    c2.metric("Groq Model", _s.groq_model)
    c3.metric("DB Name", _s.db_name)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: PROCUREMENT PIPELINE  (main sequential flow)
# ═══════════════════════════════════════════════════════════════════════════════
elif active_page == PAGES[0]:
    st.title("🔄 Procurement Pipeline")
    st.caption(
        "End-to-end automated flow: demand forecasting → supplier RFQ dispatch → "
        "quote evaluation → e-invoice collection → audit."
    )

    # ── Session-state defaults ────────────────────────────────────────────────
    for _k, _v in {
        "agent1_result":      None,
        "a1_proceeded":       False,
        "a2_dispatched":      [],
        "a2_all_sent":        False,
        "a3_results":         {},   # {category: {quotes, ranking, drafts, po}}
        "a3_emails_sent":     False,
        "sender_info":        {},
    }.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    from core.db import col as _db_col

    # ═══════════════════════════════════════════════════════════════════════════
    # ── AGENT 1 ───────────────────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    _agent_header("1", "Supply Chain & Demand Forecasting",
                  "30-day deterministic stock simulation powered by LLM event velocity prediction.", "📦")

    # ── Product catalog ───────────────────────────────────────────────────────
    _section("Product Catalog & Baseline Velocity")
    try:
        products_db = svc1.db.fetch_products()
        if products_db:
            st.dataframe(
                pd.DataFrame(products_db)[
                    ["product_id","name","category","cost_price",
                     "current_stock","days_on_hand","baseline_daily_velocity"]
                ], use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not load products: {e}")

    st.divider()

    # ── Calendar events ───────────────────────────────────────────────────────
    _section("Calendar Events")
    try:
        events_db = svc1.db.fetch_events()
    except Exception:
        events_db = []
    with st.expander("➕ Add New Event"):
        with st.form("add_event_f"):
            en = st.text_input("Event Name", value="Monsoon Festival")
            notes = st.text_area("Notes", value="Increase in electronics demand expected.")
            c1,c2 = st.columns(2)
            today_d = datetime.now()
            sd = c1.date_input("Start Date", value=today_d)
            ed = c2.date_input("End Date",   value=today_d + timedelta(days=3))
            if st.form_submit_button("Save Event"):
                try:
                    eid = svc1.db.insert_event(en, notes, sd.strftime("%Y-%m-%d"), ed.strftime("%Y-%m-%d"))
                    st.success(f"Saved event '{en}' — ID: {eid}")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
    if events_db:
        st.dataframe(pd.DataFrame(events_db)[["_id","event_name","notes","start_date","end_date"]],
                     use_container_width=True, hide_index=True)

    st.divider()

    # ── Run simulation ────────────────────────────────────────────────────────
    if st.button("🚀 Run Agent 1 — 30-day Demand Simulation", type="primary", key="a1_run"):
        with st.spinner("Running 30-day simulation…"):
            try:
                result = svc1.run_pipeline()
                st.session_state["agent1_result"] = result
                st.session_state["a1_proceeded"]  = False
                # clear downstream state
                for _stale in ["a2_dispatched","a2_all_sent","a3_results","a3_emails_sent"]:
                    st.session_state[_stale] = [] if _stale == "a2_dispatched" else (
                        {} if _stale == "a3_results" else False)
                st.success(
                    f"✅ Simulation complete — "
                    f"**{len(result.get('needed_products',[]))} products** need restocking."
                )
            except Exception as ex:
                st.error(f"Simulation failed: {ex}")

    # ── Show results ──────────────────────────────────────────────────────────
    if st.session_state["agent1_result"] is not None:
        res = st.session_state["agent1_result"]
        needed   = res.get("needed_products", [])
        deadstock = res.get("not_selling_products", [])

        st.divider()
        col_a, col_b = st.columns(2)

        with col_a:
            _section("🛒 Products Needing Restock")
            if needed:
                df_n = pd.DataFrame(needed)
                if "name" in df_n.columns and "product_name" not in df_n.columns:
                    df_n = df_n.rename(columns={"name": "product_name"})
                show_cols = [c for c in ["product_id","product_name","category","current_stock",
                                         "projected_30d_demand","reorder_quantity",
                                         "estimated_reorder_cost","stockout_warning_date"]
                             if c in df_n.columns]
                st.dataframe(df_n[show_cols], use_container_width=True, hide_index=True)
                st.metric("Total Procurement Cost", f"₹{df_n['estimated_reorder_cost'].sum():,.2f}")
            else:
                st.success("All products have sufficient stock.")

        with col_b:
            _section("⚠️ Deadstock")
            if deadstock:
                df_d = pd.DataFrame(deadstock)
                if "name" in df_d.columns and "product_name" not in df_d.columns:
                    df_d = df_d.rename(columns={"name": "product_name"})
                st.dataframe(df_d, use_container_width=True, hide_index=True)
                st.metric("Tied-Up Capital", f"₹{df_d['capital_tied_up'].sum():,.2f}")
            else:
                st.success("No deadstock identified.")

        # ── Interactive Demand Calendar ────────────────────────────────────────
        st.divider()
        _section("📅 Interactive 30-Day Demand & Stock Calendar")
        st.caption(
            "Select a product to see its day-by-day demand velocity and remaining stock "
            "visualised on the calendar. 🟢 Healthy  🟡 Low stock  🔴 Stockout"
        )

        product_timelines = res.get("product_timelines", [])
        events_in_window  = res.get("events_in_window", [])

        if product_timelines:
            from streamlit_calendar import calendar as st_calendar

            # ── Product selector buttons ──────────────────────────────────────
            if "cal_selected_prod" not in st.session_state:
                st.session_state["cal_selected_prod"] = product_timelines[0]["product_name"]

            # Wrap buttons in rows of 6
            chunk_size = 6
            for chunk_start in range(0, len(product_timelines), chunk_size):
                chunk = product_timelines[chunk_start : chunk_start + chunk_size]
                btn_cols = st.columns(len(chunk))
                for ci, tl in enumerate(chunk):
                    pname = tl["product_name"]
                    is_active = (pname == st.session_state["cal_selected_prod"])
                    btn_label = f"{'✅ ' if is_active else '📦 '}{pname}"
                    if btn_cols[ci].button(btn_label, key=f"cal_btn_{tl['product_id']}",
                                           use_container_width=True):
                        st.session_state["cal_selected_prod"] = pname
                        st.rerun()

            selected_name = st.session_state["cal_selected_prod"]
            timeline_entry = next(
                (t for t in product_timelines if t["product_name"] == selected_name), None
            )

            if timeline_entry:
                baseline_vel  = timeline_entry.get("baseline_velocity", 0)
                current_stock = timeline_entry.get("current_stock", 0)

                # ── Info bar for selected product ─────────────────────────────
                ic1, ic2, ic3, ic4 = st.columns(4)
                ic1.metric("Selected Product",   selected_name)
                ic2.metric("Current Stock",      current_stock)
                ic3.metric("Baseline Velocity",  f"{baseline_vel}/day")
                # Stockout date
                stockout_day = next(
                    (d["date"] for d in timeline_entry["daily_timeline"] if d["remaining_stock"] <= 0),
                    None
                )
                ic4.metric("Stockout Date", stockout_day if stockout_day else "No stockout")

                # ── Build calendar events ─────────────────────────────────────
                cal_events = []

                # Add calendar_context events (blue markers)
                for ev in events_in_window:
                    cal_events.append({
                        "title":  f"🎉 {ev['event_name']}",
                        "start":  ev["start_date"],
                        "end":    ev["end_date"],
                        "color":  "#3b82f6",
                        "allDay": True,
                        "extendedProps": {"type": "event", "notes": ev.get("notes", "")},
                    })

                # Add daily stock events (coloured by stock level)
                for day_data in timeline_entry["daily_timeline"]:
                    rem   = day_data["remaining_stock"]
                    vel   = day_data["daily_velocity"]
                    ev_tag = day_data["applied_event"]

                    if rem <= 0:
                        color = "#ef4444"   # red — stockout
                        icon  = "🔴"
                    elif rem <= max(5, baseline_vel * 3):
                        color = "#f59e0b"   # amber — low stock
                        icon  = "🟡"
                    else:
                        color = "#22c55e"   # green — healthy
                        icon  = "🟢"

                    # Show event tag if not Normal
                    tag_str = f" [{ev_tag}]" if ev_tag != "Normal" else ""
                    cal_events.append({
                        "title":  f"{icon} Stock:{rem}  Vel:{vel}/d{tag_str}",
                        "start":  day_data["date"],
                        "color":  color,
                        "allDay": True,
                        "extendedProps": {
                            "type":            "stock",
                            "remaining_stock": rem,
                            "daily_velocity":  vel,
                            "applied_event":   ev_tag,
                        },
                    })

                # ── Calendar options ──────────────────────────────────────────
                cal_options = {
                    "initialView":   "dayGridMonth",
                    "editable":      False,
                    "selectable":    True,
                    "height":        480,
                    "contentHeight": 440,
                    "aspectRatio":   2.0,
                    "headerToolbar": {
                        "left":   "prev,next today",
                        "center": "title",
                        "right":  "dayGridMonth,timeGridWeek",
                    },
                    "initialDate": datetime.now().strftime("%Y-%m-%d"),
                    "eventDisplay": "block",
                    "dayMaxEvents": 2,
                    "moreLinkClick": "popover",
                }

                # Render calendar
                cal_state = st_calendar(
                    events=cal_events,
                    options=cal_options,
                    key=f"supply_calendar_{selected_name.replace(' ','_')}",
                )

                # ── Click-to-inspect: show detail for clicked date ────────────
                if cal_state and cal_state.get("eventClick"):
                    clicked = cal_state["eventClick"].get("event", {})
                    ext     = clicked.get("extendedProps", {})
                    if ext.get("type") == "stock":
                        st.markdown(
                            f"<div class='sv-card'>"
                            f"<span style='font-weight:700;color:#E2E8F0'>📅 {clicked.get('start','')[:10]}</span><br/>"
                            f"<span style='color:#94A3B8'>Remaining Stock:</span> "
                            f"<span style='font-weight:700;color:#F8FAFC'>{ext['remaining_stock']}</span> &nbsp;|&nbsp;"
                            f"<span style='color:#94A3B8'>Daily Velocity:</span> "
                            f"<span style='font-weight:700;color:#F8FAFC'>{ext['daily_velocity']}/day</span> &nbsp;|&nbsp;"
                            f"<span style='color:#94A3B8'>Event:</span> "
                            f"<span style='color:#A5B4FC'>{ext['applied_event']}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    elif ext.get("type") == "event":
                        st.info(
                            f"**{clicked.get('title','').replace('🎉 ','')}** — {ext.get('notes','')}"
                        )

                # ── Legend ────────────────────────────────────────────────────
                st.markdown(
                    "<div style='font-size:.75rem;color:#64748B;margin-top:6px'>"
                    "<span style='color:#22c55e'>●</span> Healthy stock &nbsp;&nbsp;"
                    "<span style='color:#f59e0b'>●</span> Low stock &nbsp;&nbsp;"
                    "<span style='color:#ef4444'>●</span> Stockout &nbsp;&nbsp;"
                    "<span style='color:#3b82f6'>●</span> Calendar event"
                    "</div>",
                    unsafe_allow_html=True,
                )

                # ── Daily breakdown table below calendar ──────────────────────
                with st.container():
                    _section("Day-by-Day Detail Table")
                    df_tl = pd.DataFrame(timeline_entry["daily_timeline"])
                    df_tl = df_tl.rename(columns={
                        "date":            "Date",
                        "applied_event":   "Event",
                        "daily_velocity":  "Velocity (units/day)",
                        "remaining_stock": "Remaining Stock",
                    })
                    # Colour-code the stock column
                    def _colour_stock(val):
                        if val <= 0:
                            return "background-color:#3d0f0f;color:#fca5a5"
                        elif val <= max(5, baseline_vel * 3):
                            return "background-color:#3d2f0a;color:#fcd34d"
                        return ""
                    st.dataframe(
                        df_tl.style.applymap(_colour_stock, subset=["Remaining Stock"]),
                        use_container_width=True,
                        hide_index=True,
                    )
        else:
            st.info("Run the Agent 1 simulation first to generate product timelines for the calendar.")

        # ── Proceed button ────────────────────────────────────────────────────
        if needed and not st.session_state["a1_proceeded"]:
            st.divider()
            if st.button("✅ Proceed to Supplier RFQ Dispatch →", type="primary", key="a1_proceed"):
                st.session_state["a1_proceeded"] = True
                st.rerun()

    # ═══════════════════════════════════════════════════════════════════════════
    # ── AGENT 2 — shown after Agent 1 proceeds ────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    if st.session_state["a1_proceeded"] and st.session_state["agent1_result"] is not None:
        res          = st.session_state["agent1_result"]
        needed       = res.get("needed_products", [])
        a2_wf_id     = res.get("workflow_id", f"WF-SC-{datetime.now().strftime('%Y-%m-%d')}")

        _step_arrow()
        _agent_header("2", "Supplier RFQ Dispatcher",
                      "Groups restock items by category, matches MongoDB suppliers, "
                      "generates personalised Groq LLM emails and dispatches via SMTP.", "📧")

        # ── User identity (collected once) ────────────────────────────────────
        _section("Your Identity — used in all outgoing emails")
        st.markdown(
            "<p style='font-size:.8rem;color:#64748B;margin-bottom:12px'>"
            "This information will be used to sign and personalise every email "
            "sent to suppliers. Fill it once before dispatching.</p>",
            unsafe_allow_html=True)

        id_c1, id_c2, id_c3, id_c4 = st.columns(4)
        sender_name     = id_c1.text_input("Your Full Name",    key="sid_name",
                                           value=st.session_state["sender_info"].get("name", ""))
        sender_role     = id_c2.text_input("Your Role / Title", key="sid_role",
                                           value=st.session_state["sender_info"].get("title", ""))
        sender_company  = id_c3.text_input("Company Name",      key="sid_company",
                                           value=st.session_state["sender_info"].get("company", ""))
        sender_location = id_c4.text_input("Location / City",   key="sid_location",
                                           value=st.session_state["sender_info"].get("location", ""))

        identity_complete = all([sender_name, sender_role, sender_company, sender_location])
        if not identity_complete:
            st.warning("Fill in all four identity fields above before sending emails.")

        # Persist identity for Agent 3 reuse
        st.session_state["sender_info"] = {
            "name":     sender_name,
            "title":    sender_role,
            "company":  sender_company,
            "location": sender_location,
        }

        st.divider()

        # ── Group products by category & fetch suppliers ───────────────────────
        categories: Dict[str, List[Dict]] = {}
        for p in needed:
            categories.setdefault(p["category"], []).append(p)

        _section("Restock Categories & Matched Sellers")

        all_category_data: List[Dict[str, Any]] = []

        for category, prods in categories.items():
            db_suppliers = list(_db_col("suppliers").find(
                {"categories_supplied": {"$in": [category]}, "compliance_flag": {"$ne": True}},
                {"_id": 0}
            ))
            if not db_suppliers:
                db_suppliers = list(_db_col("suppliers").find(
                    {"categories_supplied": {"$elemMatch": {"$regex": f"^{category}$", "$options": "i"}},
                     "compliance_flag": {"$ne": True}},
                    {"_id": 0}
                ))

            all_category_data.append({
                "category": category,
                "prods":    prods,
                "suppliers": db_suppliers,
            })

        for cat_data in all_category_data:
            category     = cat_data["category"]
            prods        = cat_data["prods"]
            db_suppliers = cat_data["suppliers"]

            with st.expander(
                f"📦 **{category}** — {len(prods)} product(s) · {len(db_suppliers)} seller(s)",
                expanded=True,
            ):
                # Products table
                st.markdown("**Products needing restock**")
                df_prods = pd.DataFrame(prods)
                show_p = [c for c in ["product_id","product_name","reorder_quantity",
                                       "estimated_reorder_cost","stockout_warning_date"]
                          if c in df_prods.columns]
                st.dataframe(df_prods[show_p] if show_p else df_prods,
                             use_container_width=True, hide_index=True)

                # Sellers table
                st.markdown("**Matched sellers from database**")
                if not db_suppliers:
                    st.warning(
                        f"No active suppliers found for **{category}**. "
                        f"Add suppliers with `\"categories_supplied\": [\"{category}\"]` in MongoDB."
                    )
                else:
                    df_sup = pd.DataFrame(db_suppliers)
                    disp_cols = [c for c in ["supplier_id","supplier_name","contact_email",
                                              "trust_score","gstin","categories_supplied"]
                                 if c in df_sup.columns]
                    st.dataframe(df_sup[disp_cols] if disp_cols else df_sup,
                                 use_container_width=True, hide_index=True)

        st.divider()

        # ── Single "Send All Mails" button ────────────────────────────────────
        already_sent = st.session_state.get("a2_all_sent", False)
        if already_sent:
            st.success("✅ All RFQ emails were dispatched. See summary below.")
        else:
            send_disabled = not identity_complete
            if st.button(
                "📤 Send All RFQ Emails to All Sellers",
                type="primary",
                disabled=send_disabled,
                key="a2_send_all",
            ):
                if not identity_complete:
                    st.error("Complete your identity fields first.")
                else:
                    from agents.rfq_matcher import generate_inquiry_email, send_rfq_email

                    dispatched_summary: List[Dict[str, Any]] = []
                    total_sent = 0
                    total_failed: List[str] = []

                    prog = st.progress(0)
                    total_pairs = sum(
                        len(c["suppliers"]) for c in all_category_data if c["suppliers"]
                    )
                    done = 0

                    for cat_data in all_category_data:
                        category     = cat_data["category"]
                        prods        = cat_data["prods"]
                        db_suppliers = cat_data["suppliers"]
                        if not db_suppliers:
                            continue

                        products_desc = "\n".join(
                            f"- {p['product_name']}: reorder qty {p['reorder_quantity']} units"
                            for p in prods
                        )
                        contacted = []
                        for sup in db_suppliers:
                            s_email = sup.get("contact_email", "")
                            s_name  = sup.get("supplier_name", "Supplier")
                            if not s_email:
                                done += 1
                                prog.progress(done / max(total_pairs, 1))
                                continue
                            with st.spinner(f"Generating email for {s_name} ({category})…"):
                                body = generate_inquiry_email(
                                    sender_name, sender_company, sender_location,
                                    s_name, category, products_desc,
                                )
                            ok, msg = send_rfq_email(
                                s_email, f"Request for Quotation — {category}", body
                            )
                            done += 1
                            prog.progress(done / max(total_pairs, 1))
                            if ok:
                                total_sent += 1
                                contacted.append({
                                    "supplier_id":   sup.get("supplier_id", ""),
                                    "supplier_name": s_name,
                                    "email":         s_email,
                                    "category":      category,
                                    "products":      [p["product_name"] for p in prods],
                                })
                            else:
                                total_failed.append(f"{s_email}: {msg}")

                        dispatched_summary.append({
                            "category":        category,
                            "workflow_id":     a2_wf_id,
                            "contacted":       contacted,
                            "requested_items": [
                                {"name": p["product_name"], "quantity": p["reorder_quantity"]}
                                for p in prods
                            ],
                        })

                    st.session_state["a2_dispatched"] = dispatched_summary
                    st.session_state["a2_all_sent"]   = True

                    for f_msg in total_failed:
                        st.error(f"Failed: {f_msg}")
                    if total_sent:
                        st.success(f"✅ Dispatched {total_sent} RFQ email(s) across "
                                   f"{len(dispatched_summary)} categor{'y' if len(dispatched_summary)==1 else 'ies'}.")
                    st.rerun()

        # ── Dispatch summary ──────────────────────────────────────────────────
        dispatched_now = st.session_state.get("a2_dispatched", [])
        if dispatched_now:
            _section("Dispatch Summary")
            rows = []
            for d in dispatched_now:
                for c in d.get("contacted", []):
                    rows.append({"Category": d["category"], "Supplier": c["supplier_name"],
                                 "Email": c["email"], "Products": ", ".join(c.get("products", []))})
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════════════════
    # ── AGENT 3 — shown after Agent 2 has dispatched ─────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    if st.session_state.get("a2_all_sent") and st.session_state.get("a2_dispatched"):
        dispatched: List[Dict[str, Any]] = st.session_state["a2_dispatched"]

        _step_arrow()
        _agent_header("3", "Quote Evaluation & PO Awarding",
                      "Automatically polls for supplier replies, shows live quote status per seller, "
                      "then ranks & awards. Acceptance emails request a PDF e-invoice which is "
                      "forwarded to the Invoice Auditor automatically.", "🏆")

        sender_info = st.session_state.get("sender_info", {})

        # ── Non-blocking refresh controls ─────────────────────────────────────
        # Uses streamlit-autorefresh — NEVER calls time.sleep() which freezes UI
        from streamlit_autorefresh import st_autorefresh

        rc1, rc2, rc3 = st.columns([3, 1, 1])
        with rc1:
            auto_ms = st.select_slider(
                "⏱️ Auto-refresh interval",
                options=[0, 15, 30, 60, 90, 120, 180, 300],
                value=st.session_state.get("a3_refresh_ms", 0),
                format_func=lambda v: "Off" if v == 0 else f"{v}s",
                key="a3_refresh_slider",
            )
            st.session_state["a3_refresh_ms"] = auto_ms
        with rc2:
            st.write("")
            manual_refresh = st.button("🔄 Manual Refresh", key="a3_manual_refresh")
        with rc3:
            st.write("")
            st.caption(f"🕐 {datetime.now().strftime('%H:%M:%S')}")

        # Fire the non-blocking autorefresh (returns a counter, we ignore the value)
        if auto_ms > 0:
            st_autorefresh(interval=auto_ms * 1000, key="a3_autorefresh_widget")

        if manual_refresh:
            st.rerun()

        st.divider()

        # ── Session-state defaults for Agent 3 ───────────────────────────────
        # a3_fetching[cat_key]  = True  → keep polling inbox each render
        # a3_raw_replies[cat_key] = [list of raw email dicts matched so far]
        # a3_results[cat_key]   = {quotes, ranking, drafts, po}
        for _k2 in ["a3_fetching", "a3_raw_replies", "a3_results"]:
            if _k2 not in st.session_state:
                st.session_state[_k2] = {}

        from agents.rfq_matcher import fetch_recent_emails
        from orchestrator.data_contracts import QuotesReceivedPayload, SupplierQuote

        for dispatch_entry in dispatched:
            category        = dispatch_entry["category"]
            workflow_id     = dispatch_entry["workflow_id"]
            contacted       = dispatch_entry.get("contacted", [])
            requested_items = dispatch_entry.get("requested_items", [])
            sup_emails      = [c["email"] for c in contacted]
            sup_name_map    = {c["email"]: c["supplier_name"] for c in contacted}
            cat_key         = category.replace(" ", "_")

            # Initialise per-category state
            if cat_key not in st.session_state["a3_fetching"]:
                st.session_state["a3_fetching"][cat_key]     = True   # start polling by default
            if cat_key not in st.session_state["a3_raw_replies"]:
                st.session_state["a3_raw_replies"][cat_key]  = []
            if cat_key not in st.session_state["a3_results"]:
                st.session_state["a3_results"][cat_key]      = None

            currently_fetching = st.session_state["a3_fetching"][cat_key]
            cat_state          = st.session_state["a3_results"][cat_key]

            # ── Background inbox poll (runs every render while fetching=True) ─
            # This is pure Python — no sleep, no blocking. IMAP fetch is ~1-2s
            # and happens transparently on each Streamlit rerun.
            if currently_fetching and cat_state is None:
                try:
                    all_emails = fetch_recent_emails(limit=50)
                    matched_now = [
                        m for m in all_emails
                        if any(se.lower() in str(m["from"]).lower() for se in sup_emails)
                    ]
                    # Deduplicate by (from + subject) so we don't double-count
                    existing_keys = {
                        (r["from"], r.get("subject",""))
                        for r in st.session_state["a3_raw_replies"][cat_key]
                    }
                    for m in matched_now:
                        key = (m["from"], m.get("subject",""))
                        if key not in existing_keys:
                            st.session_state["a3_raw_replies"][cat_key].append(m)
                            existing_keys.add(key)
                except Exception:
                    pass  # IMAP errors are silent; next render will retry

            raw_replies = st.session_state["a3_raw_replies"][cat_key]

            # ── Expander header shows live status ─────────────────────────────
            replied_emails = set()
            for m in raw_replies:
                fa = m["from"].lower()
                if "<" in fa:
                    fa = fa.split("<")[1].rstrip(">").strip()
                replied_emails.add(fa)
            n_replied = sum(1 for se in sup_emails if se.lower() in replied_emails)
            n_total   = len(sup_emails)
            status_icon = "✅" if n_replied == n_total and n_total > 0 else ("⏳" if currently_fetching else "⏸️")

            with st.expander(
                f"{status_icon} **{category}** — {n_replied}/{n_total} replies received",
                expanded=True,
            ):
                # ── Seller details table ──────────────────────────────────────
                _section("Sellers Contacted")
                if contacted:
                    rows_sup = []
                    for c in contacted:
                        has_replied = c["email"].lower() in replied_emails
                        rows_sup.append({
                            "Supplier ID":   c.get("supplier_id", ""),
                            "Supplier Name": c["supplier_name"],
                            "Email":         c["email"],
                            "Category":      c.get("category", category),
                            "Products":      ", ".join(c.get("products", [])),
                            "Reply Status":  "✅ Replied" if has_replied else "⏳ Awaiting",
                        })
                    st.dataframe(pd.DataFrame(rows_sup), use_container_width=True, hide_index=True)

                st.divider()

                # ── Live quote receipt status ─────────────────────────────────
                _section("Live Quote Receipt Status")
                for c in contacted:
                    has_replied = c["email"].lower() in replied_emails
                    badge_cls   = "sv-green" if has_replied else ("sv-amber" if currently_fetching else "sv-red")
                    badge_text  = "Quote Received" if has_replied else ("Waiting…" if currently_fetching else "Not Received")
                    st.markdown(
                        f"<div class='sv-card' style='display:flex;align-items:center;gap:12px'>"
                        f"<div style='flex:1'>"
                        f"<span style='font-weight:600;color:#E2E8F0'>{c['supplier_name']}</span>"
                        f"<span style='font-size:.75rem;color:#64748B;margin-left:8px'>{c['email']}</span>"
                        f"</div>"
                        f"<span class='sv-badge {badge_cls}'>{badge_text}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                st.divider()

                # ── Stop & Process / Resume controls ─────────────────────────
                # Single button: pressing it stops polling AND immediately
                # parses + ranks — no second click required.
                if cat_state is None:
                    if currently_fetching:
                        stop_col, info_col = st.columns([1, 3])
                        with stop_col:
                            stop_clicked = st.button(
                                f"⏹️ Stop & Process — {category}",
                                key=f"a3_stop_{cat_key}",
                                type="primary",
                            )
                        with info_col:
                            if n_replied == 0:
                                st.info(
                                    "Polling inbox… waiting for replies. "
                                    "Click **Stop & Process** at any time to work with "
                                    "whatever quotes have arrived so far."
                                )
                            else:
                                st.success(
                                    f"✅ {n_replied}/{n_total} quote(s) received. "
                                    "Click **Stop & Process** to rank and award."
                                )

                        if stop_clicked:
                            # Mark fetching stopped immediately
                            st.session_state["a3_fetching"][cat_key] = False
                            # Parse & rank right now — no second button needed
                            with st.spinner(f"Parsing {len(raw_replies)} reply(ies) via Groq LLM…"):
                                supplier_replies = []
                                for m in raw_replies:
                                    fa = m["from"].lower()
                                    if "<" in fa:
                                        fa = fa.split("<")[1].rstrip(">").strip()
                                    matched_email = next(
                                        (se for se in sup_emails if se.lower() == fa), fa
                                    )
                                    matched_contact = next(
                                        (c for c in contacted
                                         if c["email"].lower() == matched_email.lower()), {}
                                    )
                                    supplier_replies.append({
                                        "supplier_id":    matched_contact.get("supplier_id", matched_email),
                                        "supplier_name":  matched_contact.get("supplier_name", matched_email),
                                        "supplier_email": matched_email,
                                        "email_body":     m.get("body", ""),
                                    })
                                if not supplier_replies:
                                    st.warning(
                                        "No replies to process yet. "
                                        "Use ▶️ Resume to keep polling."
                                    )
                                    st.session_state["a3_fetching"][cat_key] = True
                                else:
                                    quotes = svc3.parse_quotes(
                                        category, requested_items, supplier_replies
                                    )
                            if supplier_replies:
                                with st.spinner("Ranking quotes via Groq LLM…"):
                                    ranking = svc3.rank_quotes(category, quotes, requested_items)

                                sq_list = [
                                    SupplierQuote(
                                        supplier_id       = q["supplier_id"],
                                        supplier_email    = q["supplier_email"],
                                        category          = category,
                                        quoted_amount     = float(q.get("quoted_amount", 0.0)),
                                        delivery_date     = str(q.get("delivery_date", "Unknown")),
                                        quoted_items      = q.get("quoted_items", []),
                                        quoted_quantities = q.get("quoted_quantities", {}),
                                        itemized_costs    = q.get("itemized_costs", {}),
                                    )
                                    for q in quotes if not q.get("is_combination")
                                ]
                                sv.route(QuotesReceivedPayload(
                                    workflow_id=workflow_id, category=category,
                                    requested_items=requested_items, supplier_quotes=sq_list,
                                ))
                                st.session_state["a3_results"][cat_key] = {
                                    "quotes":  quotes,
                                    "ranking": ranking,
                                    "drafts":  None,
                                    "po":      None,
                                }
                            st.rerun()

                    else:
                        # Fetching already stopped but not yet processed
                        # (only reachable if a previous run left fetching=False with no results)
                        if n_replied == 0:
                            st.warning("No replies collected yet.")
                        else:
                            st.info(f"Polling stopped. {n_replied} reply(ies) ready.")
                        if st.button(f"▶️ Resume Fetching — {category}",
                                     key=f"a3_resume_{cat_key}"):
                            st.session_state["a3_fetching"][cat_key] = True
                            st.rerun()

                # ── Ranking, drafts & award (shown once quotes are processed) ─
                if cat_state is not None:
                    quotes     = cat_state["quotes"]
                    ranking    = cat_state["ranking"]
                    ranked_list = ranking.get("ranked_suppliers", [])

                    _section("Ranking Results")
                    if ranked_list:
                        # Build a clean display dataframe
                        df_rank = pd.DataFrame([{
                            "Rank":             r["rank"],
                            "Supplier":         r.get("supplier_name") or r["supplier_id"],
                            "Fulfillment":      r.get("fulfillment_tier", ""),
                            "Amount (₹)":       f"₹{r['total_quoted_amount']:,.2f}",
                            "Trust Score":      r.get("trust_score", "—"),
                            "Delivery":         r["delivery_date"],
                            "Justification":    r.get("justification", ""),
                        } for r in ranked_list])
                        # Colour the fulfillment tier column header info
                        st.dataframe(df_rank, use_container_width=True, hide_index=True)
                        # Legend
                        st.markdown(
                            "<div style='font-size:.72rem;color:#64748B;margin-top:4px'>"
                            "🟢 <b>Full fulfillment</b> = single supplier covers all items &nbsp;|&nbsp; "
                            "🟡 <b>Combo</b> = multiple suppliers combined &nbsp;|&nbsp; "
                            "🔴 <b>Partial</b> = items missing from this supplier"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.warning("No ranked suppliers returned.")

                    if ranked_list:
                        # Build radio options using supplier_id as key, display name as label
                        def _winner_label(s: Dict[str, Any]) -> str:
                            name = (
                                s.get("supplier_name")
                                or sup_name_map.get(s["supplier_id"], "")
                                or s["supplier_id"]
                            )
                            return (
                                f"Rank {s['rank']} — {name} "
                                f"(₹{s['total_quoted_amount']:,.2f} | {s['delivery_date']})"
                            )

                        winner_id = st.radio(
                            "Confirm winning supplier (pre-selected = LLM top rank)",
                            [s["supplier_id"] for s in ranked_list],
                            format_func=lambda x: _winner_label(
                                next(s for s in ranked_list if s["supplier_id"] == x)
                            ),
                            key=f"winner_{cat_key}",
                        )

                        # Preview drafts
                        if not cat_state.get("po"):
                            if st.button(f"📝 Preview Acceptance / Rejection Drafts — {category}",
                                         key=f"draft_{cat_key}"):
                                with st.spinner("Generating email drafts via Groq…"):
                                    winner_q = next(
                                        (q for q in quotes if q["supplier_id"] == winner_id), None
                                    )
                                    is_combo = winner_q.get("is_combination", False) if winner_q else False
                                    drafts = svc3.generate_draft_emails(
                                        category, ranking, quotes, sender_info,
                                        winner_id, is_combo_confirmation=is_combo,
                                    )
                                    cat_state["drafts"] = drafts
                                    st.session_state["a3_results"][cat_key] = cat_state

                        if cat_state.get("drafts"):
                            _section("Email Drafts")
                            for di, draft in enumerate(cat_state["drafts"]):
                                colour = {
                                    "ACCEPTED":             "sv-green",
                                    "REJECTED":             "sv-red",
                                    "CONFIRMATION_REQUEST": "sv-amber",
                                }.get(draft["status"], "sv-indigo")
                                # Header card
                                st.markdown(
                                    f"<div class='sv-card'>"
                                    f"<span class='sv-badge {colour}'>{draft['status']}</span>&nbsp;"
                                    f"<strong>To:</strong> {draft['to']}&nbsp;|&nbsp;"
                                    f"<strong>Subject:</strong> {draft['subject']}"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                                # Toggle body visibility — avoids nested expander error
                                body_key  = f"show_body_{cat_key}_{di}"
                                if body_key not in st.session_state:
                                    st.session_state[body_key] = False
                                tog_label = "▲ Hide email body" if st.session_state[body_key] else "▼ View email body"
                                if st.button(tog_label, key=f"tog_{cat_key}_{di}"):
                                    st.session_state[body_key] = not st.session_state[body_key]
                                    st.rerun()
                                if st.session_state[body_key]:
                                    st.text_area(
                                        "",
                                        value=draft["body"],
                                        height=180,
                                        key=f"body_{cat_key}_{di}",
                                    )

                        # Award PO & send emails
                        if not cat_state.get("po"):
                            if st.button(
                                f"✅ Award PO & Send Acceptance / Rejection Emails — {category}",
                                key=f"award_{cat_key}", type="primary",
                            ):
                                with st.spinner("Issuing PO and sending emails…"):
                                    po = svc3.award_and_emit_po(
                                        workflow_id=workflow_id, winner_id=winner_id,
                                        sender_info=sender_info, ranking_result=ranking,
                                        quotes=quotes,
                                    )
                                    winner_q = next(
                                        (q for q in quotes if q["supplier_id"] == winner_id), None
                                    )
                                    is_combo = winner_q.get("is_combination", False) if winner_q else False
                                    final_drafts = svc3.generate_draft_emails(
                                        category, ranking, quotes, sender_info,
                                        winner_id, is_combo_confirmation=is_combo,
                                    )
                                    sent_ok = 0
                                    for d in final_drafts:
                                        try:
                                            svc3.send_single_email(d["to"], d["subject"], d["body"])
                                            sent_ok += 1
                                        except Exception as mail_err:
                                            st.error(f"Email to {d['to']} failed: {mail_err}")

                                cat_state["po"]     = po
                                cat_state["drafts"] = final_drafts
                                st.session_state["a3_results"][cat_key] = cat_state
                                st.success(
                                    f"🎉 PO **{po.po_id}** awarded to **{po.winner_supplier_id}** "
                                    f"| ₹{po.total_po_amount:,.2f} | Delivery: {po.delivery_date} "
                                    f"| {sent_ok} email(s) dispatched ✓"
                                )
                                st.info(
                                    "📄 Acceptance email asked the supplier to reply with a "
                                    "**GST-compliant PDF e-invoice**. Use the section below to collect it."
                                )
                                st.rerun()
                        else:
                            po = cat_state["po"]
                            st.success(
                                f"✅ PO **{po.po_id}** — winner: **{po.winner_supplier_id}** "
                                f"| ₹{po.total_po_amount:,.2f} | Delivery: {po.delivery_date}"
                            )

        # ═══════════════════════════════════════════════════════════════════════

        # ═══════════════════════════════════════════════════════════════════════
        # ── E-INVOICE COLLECTION → STORE TO MONGODB → TRIGGER AGENT 4 ────────
        # ═══════════════════════════════════════════════════════════════════════
        any_po_awarded = any(
            (st.session_state["a3_results"].get(d["category"].replace(" ", "_")) or {}).get("po")
            for d in dispatched
        )

        if any_po_awarded:
            _step_arrow()
            st.markdown(
                "<div class='agent-header' style='border-left-color:#10B981'>"
                "<div style='font-size:.7rem;color:#10B981;text-transform:uppercase;"
                "letter-spacing:.1em;font-weight:700'>STEP 4 → AGENT 4</div>"
                "<div style='font-size:1.25rem;font-weight:700;color:#F8FAFC;margin:4px 0 2px'>"
                "📬 Collect & Store E-Invoice PDFs → Trigger Audit</div>"
                "<div style='font-size:.8rem;color:#64748B'>"
                "Polls the inbox for supplier e-invoice reply emails, stores each PDF in MongoDB, "
                "then triggers Agent 4 to extract and audit all stored invoices."
                "</div></div>",
                unsafe_allow_html=True,
            )

            # Collect winner emails and workflow_id for this procurement run
            winner_emails: List[str] = []
            einv_workflow_id = st.session_state.get("a2_workflow_id",
                f"WF-SC-{datetime.now().strftime('%Y-%m-%d')}")
            for d in dispatched:
                cat_k = d["category"].replace(" ", "_")
                po = (st.session_state["a3_results"].get(cat_k) or {}).get("po")
                if po and po.winner_email:
                    winner_emails.append(po.winner_email)

            if winner_emails:
                st.info(
                    f"Watching inbox for e-invoice PDF replies from: "
                    f"**{', '.join(winner_emails)}**"
                )

            # ── Live stored-PDF counter ───────────────────────────────────────
            counts = svc4.get_stored_pdf_count(einv_workflow_id)
            kc1, kc2, kc3 = st.columns(3)
            kc1.metric("PDFs in MongoDB",  counts["total"])
            kc2.metric("Already Audited",  counts["audited"])
            kc3.metric("Pending Audit",    counts["pending"])

            st.divider()

            # ── Phase 1: Poll inbox and store PDFs ────────────────────────────
            _section("Phase 1 — Fetch from inbox and store to MongoDB")

            ei_c1, ei_c2, ei_c3 = st.columns([3, 1, 1])
            with ei_c1:
                ei_auto_ms = st.select_slider(
                    "⏱️ Auto-fetch interval",
                    options=[0, 30, 60, 120, 180, 300],
                    value=st.session_state.get("einv_refresh_ms", 0),
                    format_func=lambda v: "Off" if v == 0 else f"{v}s",
                    key="einv_refresh_slider",
                )
                st.session_state["einv_refresh_ms"] = ei_auto_ms
            with ei_c2:
                st.write("")
                fetch_store_btn = st.button(
                    "📥 Fetch & Store PDFs", key="fetch_store_btn", type="primary"
                )
            with ei_c3:
                st.write("")
                st.caption(f"🕐 {datetime.now().strftime('%H:%M:%S')}")

            if ei_auto_ms > 0:
                st_autorefresh(interval=ei_auto_ms * 1000, key="einv_autorefresh_widget")

            if fetch_store_btn or ei_auto_ms > 0:
                from agents.rfq_matcher import store_einvoice_pdfs_from_inbox
                with st.spinner("Polling inbox and storing PDFs to MongoDB…"):
                    store_result = store_einvoice_pdfs_from_inbox(
                        winner_emails=winner_emails,
                        workflow_id=einv_workflow_id,
                        limit=50,
                    )
                if store_result["stored"] > 0:
                    st.success(
                        f"✅ Stored **{store_result['stored']}** new PDF(s) to MongoDB. "
                        f"{store_result['skipped']} already existed (skipped)."
                    )
                    for doc in store_result["docs"]:
                        st.caption(
                            f"📎 **{doc['filename']}** from {doc['from_email']} "
                            f"— {doc['size_bytes']:,} bytes"
                        )
                elif store_result["skipped"] > 0:
                    st.info(
                        f"No new PDFs found. {store_result['skipped']} already stored "
                        f"from a previous fetch."
                    )
                else:
                    st.warning(
                        "No e-invoice emails with PDF attachments found yet. "
                        "The supplier may not have replied — try again later."
                    )

            # ── Phase 2: Trigger Agent 4 audit ───────────────────────────────
            st.divider()
            _section("Phase 2 — Trigger Agent 4 to audit all stored PDFs")

            pending_count = svc4.get_stored_pdf_count(einv_workflow_id)["pending"]

            if pending_count == 0 and counts["total"] == 0:
                st.info("No PDFs stored yet. Complete Phase 1 first.")
            else:
                if pending_count > 0:
                    st.info(
                        f"**{pending_count}** PDF(s) are stored and waiting to be audited. "
                        "Click below to start Agent 4."
                    )
                else:
                    st.success("All stored PDFs have already been audited.")

                if st.button(
                    f"🚀 Trigger Agent 4 — Audit {pending_count} Stored Invoice(s)",
                    key="trigger_audit_btn",
                    type="primary",
                    disabled=(pending_count == 0),
                ):
                    with st.spinner(
                        f"Agent 4 is extracting and auditing {pending_count} invoice(s)…"
                    ):
                        audit_trigger_result = svc4.trigger_audit(einv_workflow_id)

                    st.success(audit_trigger_result["message"])

                    for r in audit_trigger_result.get("results", []):
                        icon = "✅" if r["audit_status"] == "PASSED" else (
                            "❌" if r["audit_status"] == "FAILED" else "⚠️"
                        )
                        with st.expander(
                            f"{icon} {r['filename']} — Invoice {r['invoice_number']} "
                            f"({r['audit_status']})"
                        ):
                            if r.get("error"):
                                st.error(f"Processing error: {r['error']}")
                            else:
                                ca, cb = st.columns(2)
                                ca.metric("Discrepancies", r["discrepancies"])
                                cb.metric("Passed Checks", r["passed_checks"])
                                st.caption(f"Supplier: {r['from_email']}")

                    st.info(
                        "Full audit details are available on the "
                        "**🧾 Invoice Auditor** page in the sidebar."
                    )
                    st.rerun()
