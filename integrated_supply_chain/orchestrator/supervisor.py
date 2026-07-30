"""
orchestrator/supervisor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 7 — SUPERVISOR ORCHESTRATOR

Responsibilities:
  1. Central Message Bus   — every payload from every agent flows through here
  2. Schema Validation     — rejects payloads that fail Pydantic validation
  3. Workflow State Engine — tracks run state in `workflow_states` in-memory
                             dict AND in MongoDB system_logs
  4. Routing Engine        — dispatches validated payloads to the correct
                             downstream agent service
  5. Error Recovery        — catches agent exceptions, logs failure points,
                             returns structured error payloads
  6. Health API            — exposes live workflow & health snapshots

STRICT HUB-AND-SPOKE:
  Agents NEVER call each other directly. Every output is passed to:
      supervisor.route(payload)
  The Supervisor calls the target agent internally.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from orchestrator.data_contracts import (
    AgentID,
    AgentPayload,
    AuditCompletedPayload,
    BIQueryPayload,
    POIssuedPayload,
    QualityScoredPayload,
    QuotesReceivedPayload,
    RFQDispatchedPayload,
    StockAlertPayload,
    WorkflowStatus,
)
from orchestrator.logger import log_event, log_raw, logger


# ─────────────────────────────────────────────────────────────────────────────
# WORKFLOW STATE STORE  (in-memory; also persisted via log_event)
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowState:
    """Tracks a single end-to-end workflow run."""

    def __init__(self, workflow_id: str, initiated_by: AgentID):
        self.workflow_id   = workflow_id
        self.initiated_by  = initiated_by
        self.status        = WorkflowStatus.PENDING
        self.steps: List[Dict[str, Any]] = []
        self.created_at    = datetime.now(timezone.utc)
        self.updated_at    = self.created_at

    def advance(self, status: WorkflowStatus, note: str = "") -> None:
        self.status     = status
        self.updated_at = datetime.now(timezone.utc)
        self.steps.append({
            "status":    status.value,
            "note":      note,
            "timestamp": self.updated_at.isoformat(),
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id":   self.workflow_id,
            "initiated_by":  self.initiated_by.value,
            "status":        self.status.value,
            "steps":         self.steps,
            "created_at":    self.created_at.isoformat(),
            "updated_at":    self.updated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SUPERVISOR SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

class Supervisor:
    """
    Central Orchestrator — singleton accessible via `get_supervisor()`.
    Agents import the singleton and call route() to pass payloads.
    """

    def __init__(self):
        # In-memory workflow registry
        self._workflows: Dict[str, WorkflowState] = {}

        # Lazy-imported agent services (breaks circular imports at module load)
        self._agent_services: Dict[AgentID, Any] = {}

        logger.info("Supervisor initialised — hub-and-spoke message bus ready.")

    # ── Agent registration ────────────────────────────────────────────────────

    def register_agent(self, agent_id: AgentID, service: Any) -> None:
        """
        Called by each agent service at startup to register itself.
        Allows the Supervisor to dispatch without knowing the concrete class.
        """
        self._agent_services[agent_id] = service
        logger.info("Registered agent: %s", agent_id.value)

    def _get_service(self, agent_id: AgentID) -> Optional[Any]:
        return self._agent_services.get(agent_id)

    # ── Workflow management ───────────────────────────────────────────────────

    def _get_or_create_workflow(self, payload: AgentPayload) -> WorkflowState:
        wf_id = payload.workflow_id
        if wf_id not in self._workflows:
            self._workflows[wf_id] = WorkflowState(wf_id, payload.source_agent)
        return self._workflows[wf_id]

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        wf = self._workflows.get(workflow_id)
        return wf.to_dict() if wf else None

    def get_all_workflows(self) -> List[Dict[str, Any]]:
        return [wf.to_dict() for wf in self._workflows.values()]

    def get_active_workflows(self) -> List[Dict[str, Any]]:
        active = {WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS}
        return [
            wf.to_dict() for wf in self._workflows.values()
            if wf.status in active
        ]

    # ── Central Router ────────────────────────────────────────────────────────

    def route(self, payload: AgentPayload) -> AgentPayload:
        """
        PRIMARY ENTRY POINT for all inter-agent communication.

        Steps:
          1. Validate payload (Pydantic already enforced on construction)
          2. Advance workflow state to IN_PROGRESS
          3. Log the incoming event
          4. Dispatch to the correct handler
          5. Log the outcome (SUCCESS or FAILED)
          6. Return the resulting downstream payload (or the input on terminal nodes)
        """
        wf = self._get_or_create_workflow(payload)
        wf.advance(WorkflowStatus.IN_PROGRESS, f"Received {type(payload).__name__}")

        # ── 1. Log incoming payload ──────────────────────────────────────────
        log_event(payload, WorkflowStatus.IN_PROGRESS)

        try:
            # ── 2. Dispatch ──────────────────────────────────────────────────
            result_payload = self._dispatch(payload, wf)

            # ── 3. Log success ───────────────────────────────────────────────
            wf.advance(WorkflowStatus.SUCCESS, f"Routed to {payload.target_agent.value}")
            log_event(payload, WorkflowStatus.SUCCESS)

            return result_payload

        except Exception as exc:
            tb = traceback.format_exc()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Supervisor routing error for %s (workflow=%s): %s\n%s",
                type(payload).__name__,
                payload.workflow_id,
                error_msg,
                tb,
            )
            wf.advance(WorkflowStatus.FAILED, error_msg)
            log_event(payload, WorkflowStatus.FAILED, error=error_msg)
            raise

    def _dispatch(self, payload: AgentPayload, wf: WorkflowState) -> AgentPayload:
        """
        Internal routing table.  Maps payload types to agent handler calls.
        All branches are exhaustive — unknown payloads raise ValueError.
        """

        # ── StockAlertPayload: Agent 1 → Agent 2 ────────────────────────────
        if isinstance(payload, StockAlertPayload):
            return self._handle_stock_alert(payload, wf)

        # ── RFQDispatchedPayload: Agent 2 → Supervisor (log only) ───────────
        if isinstance(payload, RFQDispatchedPayload):
            return self._handle_rfq_dispatched(payload, wf)

        # ── QuotesReceivedPayload: Agent 2 → Agent 3 ────────────────────────
        if isinstance(payload, QuotesReceivedPayload):
            return self._handle_quotes_received(payload, wf)

        # ── POIssuedPayload: Agent 3 → Agent 4 ──────────────────────────────
        if isinstance(payload, POIssuedPayload):
            return self._handle_po_issued(payload, wf)

        # ── AuditCompletedPayload: Agent 4 → Agent 5 ────────────────────────
        if isinstance(payload, AuditCompletedPayload):
            return self._handle_audit_completed(payload, wf)

        # ── QualityScoredPayload: Agent 5 → Supervisor (log only) ───────────
        if isinstance(payload, QualityScoredPayload):
            return self._handle_quality_scored(payload, wf)

        # ── BIQueryPayload: Agent 6 → Supervisor (read / enrich) ────────────
        if isinstance(payload, BIQueryPayload):
            return self._handle_bi_query(payload, wf)

        raise ValueError(
            f"Supervisor has no handler for payload type: {type(payload).__name__}"
        )

    # ── Per-payload handlers ──────────────────────────────────────────────────

    def _handle_stock_alert(
        self, payload: StockAlertPayload, wf: WorkflowState
    ) -> StockAlertPayload:
        """
        Receives stock depletion results from Agent 1.
        Triggers Agent 2 (RFQ Matcher) for each category needing restock.
        """
        categories = payload.categories_needing_rfq
        wf.advance(
            WorkflowStatus.IN_PROGRESS,
            f"Stock alert: {len(payload.needed_products)} products across "
            f"{len(categories)} categories — triggering RFQ dispatch.",
        )
        logger.info(
            "[Supervisor] StockAlertPayload received. "
            "Products needing restock: %d | Deadstock: %d | Categories: %s",
            len(payload.needed_products),
            len(payload.deadstock_products),
            categories,
        )

        service = self._get_service(AgentID.RFQ_MATCHER)
        if service:
            try:
                service.trigger_rfq_from_stock_alert(payload)
            except Exception as exc:
                logger.warning(
                    "[Supervisor] RFQ Matcher trigger failed: %s — "
                    "payload stored for manual dispatch.",
                    exc,
                )
        return payload

    def _handle_rfq_dispatched(
        self, payload: RFQDispatchedPayload, wf: WorkflowState
    ) -> RFQDispatchedPayload:
        """Acknowledgement from Agent 2 — log the dispatch record."""
        logger.info(
            "[Supervisor] RFQ dispatched: category=%s | suppliers=%d",
            payload.category,
            len(payload.contacted_suppliers),
        )
        return payload

    def _handle_quotes_received(
        self, payload: QuotesReceivedPayload, wf: WorkflowState
    ) -> QuotesReceivedPayload:
        """
        Routes parsed quotes from Agent 2 to Agent 3 for evaluation.
        """
        wf.advance(
            WorkflowStatus.IN_PROGRESS,
            f"Quotes received for '{payload.category}': "
            f"{len(payload.supplier_quotes)} quote(s) — routing to Quote Evaluator.",
        )
        logger.info(
            "[Supervisor] QuotesReceivedPayload: category=%s | quotes=%d",
            payload.category,
            len(payload.supplier_quotes),
        )

        service = self._get_service(AgentID.QUOTE_EVALUATOR)
        if service:
            try:
                service.ingest_quotes(payload)
            except Exception as exc:
                logger.warning(
                    "[Supervisor] Quote Evaluator ingest failed: %s", exc
                )
        return payload

    def _handle_po_issued(
        self, payload: POIssuedPayload, wf: WorkflowState
    ) -> POIssuedPayload:
        """
        Receives PO award from Agent 3.
        Stores PO record in MongoDB, then notifies Agent 5 to track quality.
        """
        wf.advance(
            WorkflowStatus.IN_PROGRESS,
            f"PO {payload.po_id} issued to {payload.winner_supplier_id} "
            f"(₹{payload.total_po_amount:,.2f}) — recording and notifying Vendor Quality.",
        )
        logger.info(
            "[Supervisor] POIssuedPayload: po_id=%s | supplier=%s | amount=%.2f",
            payload.po_id,
            payload.winner_supplier_id,
            payload.total_po_amount,
        )

        # Persist to purchase_orders collection
        self._persist_po(payload)

        # Notify Agent 5
        service = self._get_service(AgentID.VENDOR_QUALITY)
        if service:
            try:
                service.register_new_po(payload)
            except Exception as exc:
                logger.warning(
                    "[Supervisor] Vendor Quality PO registration failed: %s", exc
                )
        return payload

    def _handle_audit_completed(
        self, payload: AuditCompletedPayload, wf: WorkflowState
    ) -> AuditCompletedPayload:
        """
        Receives audit results from Agent 4.
        If discrepancies found, creates auto-complaints in Agent 5.
        """
        status_label = payload.audit_status.value
        disc_count = len(payload.discrepancies)

        wf.advance(
            WorkflowStatus.IN_PROGRESS if disc_count == 0 else WorkflowStatus.FLAGGED,
            f"Audit {status_label}: invoice={payload.invoice_data.invoice_number} "
            f"| discrepancies={disc_count}",
        )
        logger.info(
            "[Supervisor] AuditCompletedPayload: invoice=%s | status=%s | discrepancies=%d",
            payload.invoice_data.invoice_number,
            status_label,
            disc_count,
        )

        if disc_count > 0:
            service = self._get_service(AgentID.VENDOR_QUALITY)
            if service:
                try:
                    service.ingest_audit_discrepancies(payload)
                except Exception as exc:
                    logger.warning(
                        "[Supervisor] Vendor Quality audit ingest failed: %s", exc
                    )
        return payload

    def _handle_quality_scored(
        self, payload: QualityScoredPayload, wf: WorkflowState
    ) -> QualityScoredPayload:
        """Receives updated trust score from Agent 5 — log and flag if needed."""
        flag_note = " — COMPLIANCE FLAGGED" if payload.compliance_flag else ""
        wf.advance(
            WorkflowStatus.FLAGGED if payload.compliance_flag else WorkflowStatus.SUCCESS,
            f"Trust score updated: supplier={payload.supplier_id} "
            f"| score={payload.new_trust_score:.1f}{flag_note}",
        )
        logger.info(
            "[Supervisor] QualityScoredPayload: supplier=%s | score=%.1f | "
            "delta=%.2f | flagged=%s",
            payload.supplier_id,
            payload.new_trust_score,
            payload.score_delta,
            payload.compliance_flag,
        )
        return payload

    def _handle_bi_query(
        self, payload: BIQueryPayload, wf: WorkflowState
    ) -> BIQueryPayload:
        """
        Enriches BI results from Agent 6 with Supervisor system context
        (active workflow count, recent error count) injected into metadata.
        """
        from orchestrator.logger import get_system_health  # local import to avoid circular
        health = get_system_health()

        payload.metadata["supervisor_health"] = health
        payload.metadata["active_workflows"] = len(self.get_active_workflows())
        payload.metadata["total_workflows"]  = len(self._workflows)

        wf.advance(
            WorkflowStatus.SUCCESS,
            f"BI query enriched with system context: "
            f"active_workflows={payload.metadata['active_workflows']}",
        )
        logger.info(
            "[Supervisor] BIQueryPayload: query=%r | rows=%d",
            payload.nl_query[:80],
            len(payload.result_rows),
        )
        return payload

    # ── DB persistence helpers ────────────────────────────────────────────────

    def _persist_po(self, payload: POIssuedPayload) -> None:
        """Write a purchase_orders record for the awarded PO."""
        from core.db import col as db_col
        doc = {
            "po_id":        payload.po_id,
            "category":     payload.category,
            "supplier_id":  payload.winner_supplier_id,
            "supplier_email": payload.winner_email,
            "total_amount": payload.total_po_amount,
            "delivery_date": payload.delivery_date,
            "line_items":   payload.line_items,
            "rfq_status":   "AWARDED",
            "order_date":   datetime.now(timezone.utc),
            "workflow_id":  payload.workflow_id,
            "is_combo":     payload.is_combo_order,
        }
        try:
            db_col("purchase_orders").update_one(
                {"po_id": payload.po_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            logger.error("Failed to persist PO %s: %s", payload.po_id, exc)

    # ── Manual workflow trigger ───────────────────────────────────────────────

    def trigger_pipeline(
        self,
        initiated_by: AgentID = AgentID.SUPERVISOR,
        notes: str = "Manual trigger",
    ) -> str:
        """
        Kick off a new end-to-end supply chain workflow from Agent 1.
        Returns the workflow_id.
        """
        workflow_id = f"WF-{uuid4().hex[:8].upper()}"
        wf = WorkflowState(workflow_id, initiated_by)
        self._workflows[workflow_id] = wf

        log_raw(
            workflow_id  = workflow_id,
            source_agent = AgentID.SUPERVISOR.value,
            target_agent = AgentID.SUPPLY_CHAIN.value,
            payload_type = "PipelineTrigger",
            payload      = {"notes": notes, "initiated_by": initiated_by.value},
            status       = WorkflowStatus.PENDING,
        )

        wf.advance(WorkflowStatus.IN_PROGRESS, notes)
        logger.info("[Supervisor] Pipeline triggered: workflow_id=%s", workflow_id)

        service = self._get_service(AgentID.SUPPLY_CHAIN)
        if service:
            try:
                service.run_pipeline(workflow_id=workflow_id)
            except Exception as exc:
                wf.advance(WorkflowStatus.FAILED, str(exc))
                logger.error(
                    "[Supervisor] Pipeline trigger failed: %s", exc
                )

        return workflow_id


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

_supervisor_instance: Optional[Supervisor] = None


def get_supervisor() -> Supervisor:
    """Return the global Supervisor singleton, creating it on first call."""
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = Supervisor()
    return _supervisor_instance
