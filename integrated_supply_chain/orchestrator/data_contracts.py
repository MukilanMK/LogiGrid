"""
orchestrator/data_contracts.py

Pydantic v2 schemas for EVERY payload that travels through the Supervisor.
No agent communicates directly with another; all inter-agent data is wrapped
in one of these models before being passed to supervisor.route().

Payload hierarchy:
  AgentPayload (base)
    ├── StockAlertPayload          Agent 1 → Supervisor → Agent 2
    ├── RFQDispatchedPayload       Agent 2 → Supervisor
    ├── QuotesReceivedPayload      Agent 2 → Supervisor → Agent 3
    ├── POIssuedPayload            Agent 3 → Supervisor → Agent 4 / Agent 5
    ├── AuditCompletedPayload      Agent 4 → Supervisor → Agent 5
    ├── QualityScoredPayload       Agent 5 → Supervisor
    └── BIQueryPayload             Agent 6 → Supervisor (read)

Supporting sub-models (used inside payloads):
  ProductNeed, SupplierQuote, InvoiceItem, SupplierInvoiceData,
  FeedbackItem, WorkflowStatus
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class AgentID(str, Enum):
    SUPERVISOR      = "SUPERVISOR"
    SUPPLY_CHAIN    = "AGENT_1_SUPPLY_CHAIN"
    RFQ_MATCHER     = "AGENT_2_RFQ_MATCHER"
    QUOTE_EVALUATOR = "AGENT_3_QUOTE_EVALUATOR"
    INVOICE_AUDITOR = "AGENT_4_INVOICE_AUDITOR"
    VENDOR_QUALITY  = "AGENT_5_VENDOR_QUALITY"
    BI_ANALYTICS    = "AGENT_6_BI_ANALYTICS"


class WorkflowStatus(str, Enum):
    PENDING     = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS     = "SUCCESS"
    FAILED      = "FAILED"
    FLAGGED     = "FLAGGED"


class RFQStatus(str, Enum):
    OPEN        = "OPEN"
    SENT        = "SENT"
    REPLIED     = "REPLIED"
    EVALUATED   = "EVALUATED"
    AWARDED     = "AWARDED"
    REJECTED    = "REJECTED"


class AuditStatus(str, Enum):
    PASSED             = "PASSED"
    FLAGGED_WITH_ISSUES = "FLAGGED_WITH_ISSUES"
    PENDING            = "PENDING"


class FeedbackCategory(str, Enum):
    MFG_DEFECT        = "MFG_DEFECT"
    LOGISTICS_DAMAGE  = "LOGISTICS_DAMAGE"
    USER_ERROR        = "USER_ERROR"
    POSITIVE          = "POSITIVE"
    OTHER             = "OTHER"


class FeedbackSeverity(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"
    NONE   = "NONE"


# ─────────────────────────────────────────────────────────────────────────────
# BASE PAYLOAD
# ─────────────────────────────────────────────────────────────────────────────

class AgentPayload(BaseModel):
    """
    Base class for all inter-agent messages.
    Every payload carries routing metadata so the Supervisor can log
    and validate it without inspecting the subclass fields.
    """
    payload_id:   str       = Field(default_factory=lambda: f"PLD-{uuid4().hex[:10].upper()}")
    workflow_id:  str       = Field(default_factory=lambda: f"WF-{uuid4().hex[:8].upper()}")
    source_agent: AgentID
    target_agent: AgentID
    status:       WorkflowStatus = WorkflowStatus.PENDING
    timestamp:    datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata:     Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# SUB-MODELS
# ─────────────────────────────────────────────────────────────────────────────

class ProductNeed(BaseModel):
    """A single product that needs restocking (output of Agent 1 simulation)."""
    product_id:             str
    product_name:           str
    category:               str
    current_stock:          int
    projected_30d_demand:   int
    reorder_quantity:       int
    estimated_reorder_cost: float
    stockout_warning_date:  str  # YYYY-MM-DD or "N/A (Sufficient Stock)"


class DeadstockItem(BaseModel):
    """A product with zero velocity and capital tied up."""
    product_id:       str
    product_name:     str
    category:         str
    current_stock:    int
    days_on_hand:     int
    capital_tied_up:  float
    reason:           str


class SupplierQuote(BaseModel):
    """A single supplier's parsed quote for a procurement category."""
    supplier_id:        str
    supplier_email:     str
    category:           str
    quoted_amount:      float
    delivery_date:      str
    quoted_items:       List[str]       = Field(default_factory=list)
    quoted_quantities:  Dict[str, int]  = Field(default_factory=dict)
    itemized_costs:     Dict[str, float] = Field(default_factory=dict)
    is_combination:     bool            = False
    component_quotes:   List[Dict[str, Any]] = Field(default_factory=list)


class RankedSupplierEntry(BaseModel):
    rank:                 int
    supplier_id:          str
    supplier_name:        str
    total_quoted_amount:  float
    delivery_date:        str
    justification:        str


class InvoiceLineItem(BaseModel):
    product_name: str
    count:        int
    cost_price:   float


class SupplierInvoiceData(BaseModel):
    """Structured data extracted from a PDF e-invoice by Agent 4."""
    invoice_number: str
    supplier_name:  str
    supplier_email: str
    items:          List[InvoiceLineItem]
    total_cost:     float


class AuditDiscrepancy(BaseModel):
    description: str
    severity:    str = "WARNING"  # WARNING | CRITICAL


class FeedbackItem(BaseModel):
    """A single quality feedback record to be scored by Agent 5."""
    feedback_id:        str = Field(default_factory=lambda: f"FB-{uuid4().hex[:8].upper()}")
    source_type:        str  # SELLER | CUSTOMER
    supplier_id:        str
    invoice_id:         Optional[str] = None
    product_id:         Optional[str] = None
    raw_feedback:       str
    additional_details: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 1: StockAlertPayload   (Agent 1 → Supervisor → Agent 2)
# ─────────────────────────────────────────────────────────────────────────────

class StockAlertPayload(AgentPayload):
    """
    Emitted by Agent 1 after the 30-day deterministic simulation.
    Contains all products that need restocking, grouped by category,
    so Agent 2 can generate category-grouped RFQ emails.
    """
    source_agent: AgentID = AgentID.SUPPLY_CHAIN
    target_agent: AgentID = AgentID.RFQ_MATCHER

    needed_products:     List[ProductNeed]  = Field(default_factory=list)
    deadstock_products:  List[DeadstockItem] = Field(default_factory=list)
    simulation_window_days: int             = 30

    @property
    def categories_needing_rfq(self) -> List[str]:
        """Distinct categories with at least one restock-needed product."""
        return list({p.category for p in self.needed_products})


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 2: RFQDispatchedPayload  (Agent 2 → Supervisor)
# ─────────────────────────────────────────────────────────────────────────────

class RFQDispatchedPayload(AgentPayload):
    """
    Emitted by Agent 2 after sending RFQ inquiry emails to suppliers.
    Records which suppliers were contacted and when, so Agent 3
    knows which inboxes to watch for replies.
    """
    source_agent: AgentID = AgentID.RFQ_MATCHER
    target_agent: AgentID = AgentID.SUPERVISOR

    category:             str
    contacted_suppliers:  List[Dict[str, str]]  # [{supplier_id, email, sent_at}]
    rfq_status:           RFQStatus = RFQStatus.SENT
    product_details:      List[Dict[str, Any]]  = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 3: QuotesReceivedPayload  (Agent 2 → Supervisor → Agent 3)
# ─────────────────────────────────────────────────────────────────────────────

class QuotesReceivedPayload(AgentPayload):
    """
    Emitted by Agent 2 (or manually triggered) once supplier reply emails
    have been parsed.  Carries all raw quotes to Agent 3 for evaluation.
    """
    source_agent: AgentID = AgentID.RFQ_MATCHER
    target_agent: AgentID = AgentID.QUOTE_EVALUATOR

    category:          str
    requested_items:   List[Dict[str, Any]]
    supplier_quotes:   List[SupplierQuote]


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 4: POIssuedPayload  (Agent 3 → Supervisor → Agent 4 / Agent 5)
# ─────────────────────────────────────────────────────────────────────────────

class POIssuedPayload(AgentPayload):
    """
    Emitted by Agent 3 after awarding the contract and dispatching PO /
    rejection emails.  Triggers invoice audit (Agent 4) and quality
    score setup (Agent 5).
    """
    source_agent: AgentID = AgentID.QUOTE_EVALUATOR
    target_agent: AgentID = AgentID.INVOICE_AUDITOR

    po_id:              str = Field(default_factory=lambda: f"PO-{uuid4().hex[:8].upper()}")
    category:           str
    winner_supplier_id: str
    winner_email:       str
    total_po_amount:    float
    delivery_date:      str
    line_items:         List[Dict[str, Any]] = Field(default_factory=list)
    ranked_suppliers:   List[RankedSupplierEntry] = Field(default_factory=list)
    is_combo_order:     bool = False


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 5: AuditCompletedPayload  (Agent 4 → Supervisor → Agent 5)
# ─────────────────────────────────────────────────────────────────────────────

class AuditCompletedPayload(AgentPayload):
    """
    Emitted by Agent 4 after auditing one or more supplier e-invoices.
    Carries structured results so Agent 5 can create quality complaints
    for flagged discrepancies.
    """
    source_agent: AgentID = AgentID.INVOICE_AUDITOR
    target_agent: AgentID = AgentID.VENDOR_QUALITY

    invoice_data:   SupplierInvoiceData
    audit_status:   AuditStatus
    discrepancies:  List[AuditDiscrepancy] = Field(default_factory=list)
    passed_checks:  List[str]              = Field(default_factory=list)
    audited_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 6: QualityScoredPayload  (Agent 5 → Supervisor)
# ─────────────────────────────────────────────────────────────────────────────

class QualityScoredPayload(AgentPayload):
    """
    Emitted by Agent 5 after processing a feedback batch or audit-triggered
    complaint.  The Supervisor stores the updated supplier trust state.
    """
    source_agent: AgentID = AgentID.VENDOR_QUALITY
    target_agent: AgentID = AgentID.SUPERVISOR

    supplier_id:      str
    supplier_name:    str
    new_trust_score:  float
    compliance_flag:  bool
    ai_category:      FeedbackCategory
    ai_severity:      FeedbackSeverity
    score_delta:      float
    feedback_id:      str


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD 7: BIQueryPayload  (Agent 6 → Supervisor)
# ─────────────────────────────────────────────────────────────────────────────

class BIQueryPayload(AgentPayload):
    """
    Emitted by Agent 6 when submitting a natural language BI query.
    The Supervisor logs the query intent and returns enriched context
    (system_logs summary, active workflows) alongside the DB result.
    """
    source_agent: AgentID = AgentID.BI_ANALYTICS
    target_agent: AgentID = AgentID.SUPERVISOR

    nl_query:          str
    mql_pipeline:      List[Dict[str, Any]] = Field(default_factory=list)
    result_rows:       List[Dict[str, Any]] = Field(default_factory=list)
    chart_config:      Dict[str, Any]       = Field(default_factory=dict)
    ai_summary:        str                  = ""


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM LOG DOCUMENT  (written to MongoDB system_logs by the Supervisor)
# ─────────────────────────────────────────────────────────────────────────────

class SystemLogEntry(BaseModel):
    """
    Schema for a single record persisted to the system_logs collection.
    The Supervisor writes one entry for every payload it routes.
    """
    log_id:       str       = Field(default_factory=lambda: f"LOG-{uuid4().hex[:12].upper()}")
    workflow_id:  str
    source_agent: str
    target_agent: str
    payload_type: str       # class name of the payload
    payload:      Dict[str, Any]
    status:       WorkflowStatus
    error:        Optional[str] = None
    timestamp:    datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))
