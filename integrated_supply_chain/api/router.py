"""
api/router.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FastAPI Application — REST layer for the integrated platform.

All endpoints interact with the Supervisor (never directly with agents).
The Supervisor then routes to the appropriate agent service.

Groups:
  /health          — system health & DB ping
  /supervisor      — workflow state, system logs, pipeline trigger
  /agent1          — supply chain simulation
  /agent2          — RFQ dispatch & reply checking
  /agent3          — quote evaluation & PO award
  /agent4          — invoice audit
  /agent5          — vendor quality / feedback
  /agent6          — BI analytics / NL query
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import settings
from core.db import ping
from orchestrator.supervisor import get_supervisor
from orchestrator.logger import get_recent_logs, get_logs_for_workflow, get_system_health
from orchestrator.data_contracts import AgentID


# ─────────────────────────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Integrated Supply Chain Platform",
        description=(
            "Unified 7-Agent Supply Chain Ecosystem with Supervisor Orchestrator. "
            "All inter-agent data flows through the Supervisor hub."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Register all agent services on startup ────────────────────────────────
    @app.on_event("startup")
    def _register_agents() -> None:
        from agents.supply_chain   import register_with_supervisor as reg1
        from agents.rfq_matcher    import register_with_supervisor as reg2
        from agents.quote_evaluator import register_with_supervisor as reg3
        from agents.invoice_auditor import register_with_supervisor as reg4
        from agents.vendor_quality  import register_with_supervisor as reg5
        from agents.bi_analytics    import register_with_supervisor as reg6

        reg1(); reg2(); reg3(); reg4(); reg5(); reg6()

    # ── Mount all route groups ────────────────────────────────────────────────
    app.include_router(health_router,     prefix="/health",     tags=["Health"])
    app.include_router(supervisor_router, prefix="/supervisor",  tags=["Supervisor"])
    app.include_router(agent1_router,     prefix="/agent1",      tags=["Agent 1 — Supply Chain"])
    app.include_router(agent2_router,     prefix="/agent2",      tags=["Agent 2 — RFQ Matcher"])
    app.include_router(agent3_router,     prefix="/agent3",      tags=["Agent 3 — Quote Evaluator"])
    app.include_router(agent4_router,     prefix="/agent4",      tags=["Agent 4 — Invoice Auditor"])
    app.include_router(agent5_router,     prefix="/agent5",      tags=["Agent 5 — Vendor Quality"])
    app.include_router(agent6_router,     prefix="/agent6",      tags=["Agent 6 — BI Analytics"])

    return app


# ─────────────────────────────────────────────────────────────────────────────
# ROUTERS
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter

health_router     = APIRouter()
supervisor_router = APIRouter()
agent1_router     = APIRouter()
agent2_router     = APIRouter()
agent3_router     = APIRouter()
agent4_router     = APIRouter()
agent5_router     = APIRouter()
agent6_router     = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@health_router.get("/")
def health_check() -> Dict[str, Any]:
    db_ok = ping()
    return {
        "status":    "ok" if db_ok else "degraded",
        "db":        "connected" if db_ok else "unreachable",
        "db_name":   settings.db_name,
        "api_version": "1.0.0",
    }


@health_router.get("/system")
def system_health() -> Dict[str, Any]:
    """Aggregate health snapshot from system_logs + workflow states."""
    health = get_system_health()
    sv     = get_supervisor()
    return {
        **health,
        "active_workflows": len(sv.get_active_workflows()),
        "total_workflows":  len(sv.get_all_workflows()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR
# ══════════════════════════════════════════════════════════════════════════════

class TriggerPipelineRequest(BaseModel):
    notes: str = "API-triggered pipeline run"


@supervisor_router.post("/trigger")
def trigger_pipeline(req: TriggerPipelineRequest) -> Dict[str, str]:
    """Kick off a new end-to-end supply chain workflow run."""
    wf_id = get_supervisor().trigger_pipeline(
        initiated_by=AgentID.SUPERVISOR,
        notes=req.notes,
    )
    return {"workflow_id": wf_id, "status": "triggered"}


@supervisor_router.get("/workflows")
def list_workflows() -> List[Dict[str, Any]]:
    return get_supervisor().get_all_workflows()


@supervisor_router.get("/workflows/active")
def list_active_workflows() -> List[Dict[str, Any]]:
    return get_supervisor().get_active_workflows()


@supervisor_router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> Dict[str, Any]:
    wf = get_supervisor().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    return wf


@supervisor_router.get("/logs")
def get_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch the most recent system_log entries."""
    return get_recent_logs(limit=limit)


@supervisor_router.get("/logs/workflow/{workflow_id}")
def get_workflow_logs(workflow_id: str) -> List[Dict[str, Any]]:
    return get_logs_for_workflow(workflow_id)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 1 — SUPPLY CHAIN
# ══════════════════════════════════════════════════════════════════════════════

@agent1_router.post("/run")
def run_supply_chain_pipeline(workflow_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Trigger the 30-day supply chain simulation.
    Routes StockAlertPayload through Supervisor → Agent 2.
    """
    from agents.supply_chain import SupplyChainService
    svc = _get_service(AgentID.SUPPLY_CHAIN, SupplyChainService)
    try:
        result = svc.run_pipeline(workflow_id=workflow_id)
        return {
            "needed_products":      result["needed_products"],
            "not_selling_products": result["not_selling_products"],
            "events_in_window":     result.get("events_in_window", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@agent1_router.get("/products")
def get_products() -> List[Dict[str, Any]]:
    from agents.supply_chain import SupplyChainService
    svc = _get_service(AgentID.SUPPLY_CHAIN, SupplyChainService)
    return svc.db.fetch_products()


@agent1_router.get("/events")
def get_events() -> List[Dict[str, Any]]:
    from agents.supply_chain import SupplyChainService
    svc = _get_service(AgentID.SUPPLY_CHAIN, SupplyChainService)
    return svc.db.fetch_events()


class AddEventRequest(BaseModel):
    event_name: str
    notes:      str
    start_date: str  # YYYY-MM-DD
    end_date:   str  # YYYY-MM-DD


@agent1_router.post("/events")
def add_event(req: AddEventRequest) -> Dict[str, str]:
    from agents.supply_chain import SupplyChainService
    svc        = _get_service(AgentID.SUPPLY_CHAIN, SupplyChainService)
    inserted_id = svc.db.insert_event(req.event_name, req.notes, req.start_date, req.end_date)
    return {"inserted_id": inserted_id}


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 2 — RFQ MATCHER
# ══════════════════════════════════════════════════════════════════════════════

class ManualRFQRequest(BaseModel):
    category:        str
    supplier_emails: List[str]
    products:        List[Dict[str, Any]]
    workflow_id:     Optional[str] = None


@agent2_router.post("/dispatch")
def dispatch_rfq(req: ManualRFQRequest) -> Dict[str, Any]:
    """Manually send RFQ emails for a category and notify Supervisor."""
    from agents.rfq_matcher import RFQMatcherService
    svc     = _get_service(AgentID.RFQ_MATCHER, RFQMatcherService)
    payload = svc.dispatch_manual(
        category         = req.category,
        supplier_emails  = req.supplier_emails,
        products_df_records = req.products,
        workflow_id      = req.workflow_id,
    )
    return {
        "workflow_id":          payload.workflow_id,
        "category":             payload.category,
        "contacted_count":      len(payload.contacted_suppliers),
        "contacted_suppliers":  payload.contacted_suppliers,
    }


@agent2_router.post("/check-replies")
def check_rfq_replies(supplier_emails: List[str]) -> Dict[str, bool]:
    """Check which suppliers have replied since their RFQ was sent."""
    from agents.rfq_matcher import check_for_replies
    return check_for_replies(supplier_emails)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 3 — QUOTE EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════

class ParseQuotesRequest(BaseModel):
    category:         str
    requested_items:  List[Dict[str, Any]]
    supplier_replies: List[Dict[str, Any]]   # [{supplier_id, supplier_email, email_body}]


class AwardPORequest(BaseModel):
    workflow_id:    str
    winner_id:      str
    sender_info:    Dict[str, str]           # {name, title, company}
    ranking_result: Dict[str, Any]
    quotes:         List[Dict[str, Any]]


@agent3_router.post("/parse-quotes")
def parse_quotes(req: ParseQuotesRequest) -> List[Dict[str, Any]]:
    from agents.quote_evaluator import QuoteEvaluatorService
    svc = _get_service(AgentID.QUOTE_EVALUATOR, QuoteEvaluatorService)
    try:
        return svc.parse_quotes(req.category, req.requested_items, req.supplier_replies)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class RankQuotesRequest(BaseModel):
    category: str
    quotes:   List[Dict[str, Any]]


@agent3_router.post("/rank-quotes")
def rank_quotes(req: RankQuotesRequest) -> Dict[str, Any]:
    from agents.quote_evaluator import QuoteEvaluatorService
    svc = _get_service(AgentID.QUOTE_EVALUATOR, QuoteEvaluatorService)
    try:
        return svc.rank_quotes(req.category, req.quotes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@agent3_router.post("/award-po")
def award_po(req: AwardPORequest) -> Dict[str, Any]:
    """
    Award the contract, emit POIssuedPayload through Supervisor.
    Supervisor persists the PO and notifies Agent 5.
    """
    from agents.quote_evaluator import QuoteEvaluatorService
    svc = _get_service(AgentID.QUOTE_EVALUATOR, QuoteEvaluatorService)
    try:
        payload = svc.award_and_emit_po(
            workflow_id    = req.workflow_id,
            winner_id      = req.winner_id,
            sender_info    = req.sender_info,
            ranking_result = req.ranking_result,
            quotes         = req.quotes,
        )
        return {
            "po_id":               payload.po_id,
            "winner_supplier_id":  payload.winner_supplier_id,
            "total_po_amount":     payload.total_po_amount,
            "delivery_date":       payload.delivery_date,
            "is_combo":            payload.is_combo_order,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 4 — INVOICE AUDITOR
# ══════════════════════════════════════════════════════════════════════════════

@agent4_router.post("/audit-invoices")
async def audit_invoices(
    files:       List[UploadFile] = File(...),
    workflow_id: Optional[str]    = Form(default=None),
) -> List[Dict[str, Any]]:
    """
    Upload one or more PDF e-invoices for batch auditing.
    Emits AuditCompletedPayload per invoice through Supervisor.
    """
    from agents.invoice_auditor import InvoiceAuditorService
    svc = _get_service(AgentID.INVOICE_AUDITOR, InvoiceAuditorService)
    try:
        # Convert UploadFile objects to file-like objects pypdf can read
        import io
        pdf_buffers = []
        for f in files:
            content = await f.read()
            buf = io.BytesIO(content)
            buf.name = f.filename
            pdf_buffers.append(buf)

        results = svc.process_pdf_batch(pdf_buffers, workflow_id=workflow_id)
        # Return JSON-serialisable summary
        return [
            {
                "filename":       r["filename"],
                "invoice_number": r["audit"]["invoice_number"],
                "supplier_name":  r["audit"]["supplier_name"],
                "audit_status":   r["audit"]["audit_status"],
                "discrepancies":  r["audit"]["discrepancies"],
                "passed_checks":  r["audit"]["passed_checks"],
            }
            for r in results
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@agent4_router.get("/audit-logs")
def get_audit_logs() -> List[Dict[str, Any]]:
    from agents.invoice_auditor import InvoiceAuditorService
    svc = _get_service(AgentID.INVOICE_AUDITOR, InvoiceAuditorService)
    return svc.get_all_audit_logs()


class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]   # [{role, content}]


@agent4_router.post("/chat")
def audit_chatbot(req: ChatRequest) -> Dict[str, str]:
    from agents.invoice_auditor import get_audit_chatbot_response
    response = get_audit_chatbot_response(req.messages)
    return {"response": response}


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 5 — VENDOR QUALITY
# ══════════════════════════════════════════════════════════════════════════════

class FeedbackRequest(BaseModel):
    source_type:        str          # SELLER | CUSTOMER
    supplier_id:        str
    raw_feedback:       str
    additional_details: str          = ""
    invoice_id:         Optional[str] = None
    product_id:         Optional[str] = None
    workflow_id:        Optional[str] = None


@agent5_router.post("/feedback")
def submit_feedback(req: FeedbackRequest) -> Dict[str, Any]:
    """
    Submit quality feedback. Classifies, scores, and routes
    QualityScoredPayload through the Supervisor.
    """
    from agents.vendor_quality import VendorQualityService
    svc = _get_service(AgentID.VENDOR_QUALITY, VendorQualityService)
    try:
        result = svc.submit_feedback(
            source_type        = req.source_type,
            supplier_id        = req.supplier_id,
            raw_feedback       = req.raw_feedback,
            additional_details = req.additional_details,
            invoice_id         = req.invoice_id,
            product_id         = req.product_id,
            workflow_id        = req.workflow_id,
        )
        return {
            "supplier_id":    req.supplier_id,
            "supplier_name":  result.get("supplier_name", ""),
            "trust_score":    result["trust_score"],
            "compliance_flag": result["compliance_flag"],
            "ai_category":    result["ai_category"],
            "ai_severity":    result["ai_severity"],
            "score_delta":    result["score_delta"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@agent5_router.get("/suppliers")
def get_suppliers() -> List[Dict[str, Any]]:
    from agents.vendor_quality import get_all_suppliers
    return get_all_suppliers()


@agent5_router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: str) -> Dict[str, Any]:
    from agents.vendor_quality import get_supplier_by_id
    doc = get_supplier_by_id(supplier_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")
    return doc


@agent5_router.get("/suppliers/{supplier_id}/history")
def get_score_history(supplier_id: str) -> List[Dict[str, Any]]:
    from agents.vendor_quality import get_score_history
    history = get_score_history(supplier_id)
    return [
        {
            "created_at":  h["created_at"].isoformat() if hasattr(h["created_at"], "isoformat") else str(h["created_at"]),
            "trust_score": h["trust_score"],
        }
        for h in history
    ]


@agent5_router.post("/reprocess")
def reprocess_feedback(supplier_id: Optional[str] = None) -> Dict[str, Any]:
    """Re-classify fallback-poisoned feedback rows and recompute trust scores."""
    from agents.vendor_quality import reprocess_all_feedback
    return reprocess_all_feedback(supplier_id=supplier_id)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 6 — BI ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

class BIQueryRequest(BaseModel):
    query:       str
    workflow_id: Optional[str] = None


@agent6_router.post("/query")
def bi_query(req: BIQueryRequest) -> Dict[str, Any]:
    """
    Natural language → MongoDB aggregation → insights.
    Routes BIQueryPayload through Supervisor for context enrichment.
    """
    from agents.bi_analytics import BIAnalyticsService
    svc = _get_service(AgentID.BI_ANALYTICS, BIAnalyticsService)
    try:
        return svc.process_query(req.query, workflow_id=req.workflow_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — lazy service retrieval from Supervisor registry
# ─────────────────────────────────────────────────────────────────────────────

def _get_service(agent_id: AgentID, fallback_class: type) -> Any:
    """
    Retrieve the registered service from the Supervisor.
    Falls back to constructing a new instance if not yet registered
    (e.g. when calling the API without running main.py startup).
    """
    sv  = get_supervisor()
    svc = sv._get_service(agent_id)
    if svc is None:
        svc = fallback_class()
        sv.register_agent(agent_id, svc)
    return svc


# ─────────────────────────────────────────────────────────────────────────────
# Instantiate the app at module level so uvicorn can import it
# ─────────────────────────────────────────────────────────────────────────────

app = create_app()
