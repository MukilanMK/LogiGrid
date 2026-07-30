"""
agents/invoice_auditor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 4 — Indian Shop Mini Auditing Agent

Core logic (preserved from original agent4/app.py):
  • extract_text_from_pdf()    — pypdf text extraction
  • parse_invoice_with_llm()   — LangChain + Groq structured extraction
  • run_audit_validation()     — cross-check against inventory & billing DBs
  • audit_chatbot_response()   — RAG chatbot with audit logs + Indian law context

Integration:
  • Emits AuditCompletedPayload → Supervisor after each invoice batch
  • AuditDiscrepancies auto-trigger Agent 5 via Supervisor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from pypdf import PdfReader

from core.db import col
from core.llm_client import get_langchain_llm
from orchestrator.data_contracts import (
    AgentID,
    AuditCompletedPayload,
    AuditDiscrepancy,
    AuditStatus,
    InvoiceLineItem,
    SupplierInvoiceData,
    WorkflowStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC EXTRACTION MODELS  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceItem(BaseModel):
    product_name: str   = Field(description="Name of the product/item in the invoice")
    count:        int   = Field(description="Quantity/Count of items supplied")
    cost_price:   float = Field(description="Per-unit cost price of the item")


class SupplierInvoice(BaseModel):
    invoice_number: str            = Field(description="Unique invoice number")
    supplier_name:  str            = Field(description="Name of the supplying vendor")
    supplier_email: str            = Field(description="Email address of supplier (Unique Key)")
    items:          List[InvoiceItem] = Field(description="List of items in the invoice")
    total_cost:     float          = Field(description="Total invoice amount")


# ─────────────────────────────────────────────────────────────────────────────
# PDF EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_file) -> str:
    """Extract raw text from an uploaded PDF file object (preserved from original)."""
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def parse_invoice_with_llm(invoice_text: str) -> SupplierInvoice:
    """Parse raw invoice text into a SupplierInvoice via Groq LLM (preserved)."""
    llm = get_langchain_llm(temperature=0)
    structured_llm = llm.with_structured_output(SupplierInvoice)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an expert Indian billing and GST audit parser. "
            "Extract all relevant supplier e-invoice details accurately.",
        ),
        ("human", "Extract invoice information from the following e-invoice content:\n\n{content}"),
    ])
    chain = prompt | structured_llm
    return chain.invoke({"content": invoice_text})


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT VALIDATION ENGINE  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

def run_audit_validation(parsed_invoice: SupplierInvoice) -> Dict[str, Any]:
    """
    Validate extracted supplier e-invoice against inventory and billing collections.
    Returns an audit_entry dict and persists it to the `auditing` collection.

    Checks:
      1. Supplier email exists in inventory records
      2. Per-item cost price matches DB
      3. Per-item quantity doesn't exceed DB stock
      4. Selling price > invoice cost price (margin safety)
      5. Item-level sum matches stated total
    """
    supplier_email = parsed_invoice.supplier_email.strip().lower()
    invoice_num    = parsed_invoice.invoice_number

    discrepancies: List[AuditDiscrepancy] = []
    passed_checks: List[str] = []

    inventory_items = list(
        col("inventory").find({
            "supplier_email": {"$regex": f"^{supplier_email}$", "$options": "i"}
        })
    )

    if not inventory_items:
        discrepancies.append(AuditDiscrepancy(
            description=f"Supplier email '{supplier_email}' not found in active Inventory records.",
            severity="WARNING",
        ))

    calc_total = 0.0

    for item in parsed_invoice.items:
        p_name    = item.product_name
        inv_count = item.count
        inv_cost  = item.cost_price
        calc_total += inv_count * inv_cost

        matched_inv = next(
            (inv for inv in inventory_items
             if inv.get("product_name", "").strip().lower() == p_name.strip().lower()),
            None,
        )

        if matched_inv:
            db_cost = float(matched_inv.get("cost_price", 0))
            if db_cost != inv_cost:
                discrepancies.append(AuditDiscrepancy(
                    description=(
                        f"Cost Price Mismatch for '{p_name}': "
                        f"Invoice CP = ₹{inv_cost}, DB CP = ₹{db_cost}"
                    ),
                    severity="WARNING",
                ))
            else:
                passed_checks.append(f"Cost Price verified for '{p_name}' (₹{inv_cost}).")

            db_count = int(matched_inv.get("count", 0))
            if inv_count > db_count:
                discrepancies.append(AuditDiscrepancy(
                    description=(
                        f"Quantity Discrepancy for '{p_name}': "
                        f"Invoice Count ({inv_count}) > DB Current Stock ({db_count})"
                    ),
                    severity="WARNING",
                ))
        else:
            discrepancies.append(AuditDiscrepancy(
                description=f"Product '{p_name}' in invoice not registered under supplier in Inventory DB.",
                severity="WARNING",
            ))

        # Margin safety check against billing collection
        billing_records = list(
            col("billing").find({"sold_product": {"$regex": f"^{p_name}$", "$options": "i"}})
        )
        for bill in billing_records:
            selling_price = float(bill.get("selling_price", 0))
            if selling_price < inv_cost:
                discrepancies.append(AuditDiscrepancy(
                    description=(
                        f"CRITICAL MARGIN ALERT: Selling Price (₹{selling_price}) of '{p_name}' "
                        f"is LESS than Invoice Cost Price (₹{inv_cost}). Loss risk detected!"
                    ),
                    severity="CRITICAL",
                ))

    # Total cost consistency
    if abs(calc_total - parsed_invoice.total_cost) > 0.01:
        discrepancies.append(AuditDiscrepancy(
            description=(
                f"Math Inconsistency: Item sum (₹{calc_total:.2f}) does not match "
                f"Invoice Stated Total (₹{parsed_invoice.total_cost:.2f})."
            ),
            severity="WARNING",
        ))

    audit_status = AuditStatus.PASSED if not discrepancies else AuditStatus.FLAGGED_WITH_ISSUES

    audit_entry = {
        "invoice_number":         invoice_num,
        "supplier_name":          parsed_invoice.supplier_name,
        "supplier_email":         supplier_email,
        "stated_total_cost":      parsed_invoice.total_cost,
        "calculated_total_cost":  calc_total,
        "items":                  [item.model_dump() for item in parsed_invoice.items],
        "audit_status":           audit_status.value,
        "discrepancies":          [d.model_dump() for d in discrepancies],
        "passed_checks":          passed_checks,
        "audited_at":             pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    col("auditing").update_one(
        {"invoice_number": invoice_num},
        {"$set": audit_entry},
        upsert=True,
    )

    return {
        "audit_entry":   audit_entry,
        "discrepancies": discrepancies,
        "passed_checks": passed_checks,
        "audit_status":  audit_status,
        "parsed_invoice": parsed_invoice,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LEGAL / AUDIT CHATBOT  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 AUDIT TRIGGER  (called by Agent 3 after PDFs are stored in MongoDB)
# ─────────────────────────────────────────────────────────────────────────────

def trigger_audit_from_stored_pdfs(workflow_id: str) -> Dict[str, Any]:
    """
    Agent 4 entry point — called by Agent 3 after all e-invoice PDFs have been
    stored in the `einvoice_store` collection.

    For every un-audited PDF in einvoice_store (filtered by workflow_id):
      1. Retrieve raw PDF bytes from MongoDB (bson.binary.Binary)
      2. Extract text from the PDF
      3. Parse structured invoice details via Groq LLM
      4. Run audit validation (cost/qty/margin checks)
      5. Store the full extracted + validated result in `invoice_audit_results`
         (private collection — only accessible by Agent 4)
      6. Mark the einvoice_store document as audited=True
      7. Emit AuditCompletedPayload → Supervisor

    Returns a summary dict with counts and per-invoice results.
    """
    import io
    import uuid
    from orchestrator.supervisor import get_supervisor

    pending = list(col("einvoice_store").find(
        {"workflow_id": workflow_id, "audited": False},
        sort=[("stored_at", 1)],
    ))

    if not pending:
        return {"processed": 0, "results": [], "message": "No unaudited PDFs found for this workflow."}

    wf_id   = f"WF-AUDIT-{uuid.uuid4().hex[:8].upper()}"
    results = []

    for doc in pending:
        pdf_bytes = bytes(doc["pdf_data"])
        filename  = doc.get("filename", "invoice.pdf")
        from_email = doc.get("from_email", "unknown")

        try:
            # Extract text from raw PDF bytes
            buf = io.BytesIO(pdf_bytes)
            raw_text    = extract_text_from_pdf(buf)
            parsed_inv  = parse_invoice_with_llm(raw_text)
            audit_result = run_audit_validation(parsed_inv)

            # Build full audit result document for invoice_audit_results collection
            audit_doc = {
                "workflow_id":         workflow_id,
                "einvoice_store_id":   str(doc["_id"]),
                "filename":            filename,
                "from_email":          from_email,
                "email_subject":       doc.get("email_subject", ""),
                "email_date":          doc.get("email_date"),
                # Extracted invoice fields
                "invoice_number":      parsed_inv.invoice_number,
                "supplier_name":       parsed_inv.supplier_name,
                "supplier_email":      parsed_inv.supplier_email,
                "items":               [item.model_dump() for item in parsed_inv.items],
                "total_cost":          parsed_inv.total_cost,
                # Audit outcome
                "audit_status":        audit_result["audit_entry"]["audit_status"],
                "discrepancies":       audit_result["audit_entry"]["discrepancies"],
                "passed_checks":       audit_result["audit_entry"]["passed_checks"],
                "calculated_total":    audit_result["audit_entry"]["calculated_total_cost"],
                "audited_at":          audit_result["audit_entry"]["audited_at"],
                "size_bytes":          doc.get("size_bytes", 0),
            }

            # Upsert into private invoice_audit_results collection
            col("invoice_audit_results").update_one(
                {"workflow_id": workflow_id, "filename": filename, "from_email": from_email},
                {"$set": audit_doc},
                upsert=True,
            )

            # Mark the einvoice_store doc as audited
            col("einvoice_store").update_one(
                {"_id": doc["_id"]},
                {"$set": {"audited": True, "audit_result_id": audit_doc.get("invoice_number")}},
            )

            # Build and route AuditCompletedPayload
            line_items_pd = [
                InvoiceLineItem(
                    product_name=item.product_name,
                    count=item.count,
                    cost_price=item.cost_price,
                )
                for item in parsed_inv.items
            ]
            invoice_data = SupplierInvoiceData(
                invoice_number=parsed_inv.invoice_number,
                supplier_name=parsed_inv.supplier_name,
                supplier_email=parsed_inv.supplier_email,
                items=line_items_pd,
                total_cost=parsed_inv.total_cost,
            )
            payload = AuditCompletedPayload(
                workflow_id    = wf_id,
                invoice_data   = invoice_data,
                audit_status   = audit_result["audit_status"],
                discrepancies  = audit_result["discrepancies"],
                passed_checks  = audit_result["passed_checks"],
                status         = WorkflowStatus.SUCCESS,
            )
            try:
                get_supervisor().route(payload)
            except Exception as exc:
                from orchestrator.logger import logger
                logger.warning("Supervisor routing failed for AuditCompletedPayload: %s", exc)

            results.append({
                "filename":     filename,
                "from_email":   from_email,
                "invoice_number": parsed_inv.invoice_number,
                "audit_status": audit_doc["audit_status"],
                "discrepancies": len(audit_result["discrepancies"]),
                "passed_checks": len(audit_result["passed_checks"]),
                "error":        None,
            })

        except Exception as exc:
            # Record the failure but don't block the rest of the batch
            from orchestrator.logger import logger
            logger.error("trigger_audit_from_stored_pdfs failed for %s: %s", filename, exc)
            results.append({
                "filename":      filename,
                "from_email":    from_email,
                "invoice_number": "PARSE_ERROR",
                "audit_status":  "FAILED",
                "discrepancies": 0,
                "passed_checks": 0,
                "error":         str(exc),
            })

    return {
        "processed": len(results),
        "results":   results,
        "message":   f"Audited {len(results)} invoice(s) from einvoice_store.",
    }


def get_invoice_audit_results(workflow_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return all records from the private `invoice_audit_results` collection.
    Optionally filtered by workflow_id. PDF binary data is excluded.
    """
    query = {"workflow_id": workflow_id} if workflow_id else {}
    return list(col("invoice_audit_results").find(
        query,
        {"_id": 0, "pdf_data": 0},
        sort=[("audited_at", -1)],
    ))


# ─────────────────────────────────────────────────────────────────────────────
# LEGAL / AUDIT CHATBOT — reads only from invoice_audit_results
# ─────────────────────────────────────────────────────────────────────────────

_AUDIT_CHATBOT_SYSTEM = """
You are Agent 4 — an AI Invoice Audit Assistant for a supply chain procurement system.

Your ONLY data source is the `invoice_audit_results` table shown below.
This table contains structured details extracted from supplier PDF e-invoices,
including invoice numbers, supplier names, line items, costs, and audit outcomes.

STRICT SCOPE RULES:
- Answer questions ONLY about the invoices in the data below.
- If a question is unrelated to invoice auditing, procurement, or the records shown,
  respond: "I can only answer questions about the audited invoices in this system."
- Do NOT answer questions about Indian law, GST rules, Consumer Protection Act,
  or Legal Metrology Act — those are outside this agent's scope.
- Do NOT invent data. If information is not in the records, say so clearly.

Current Invoice Audit Records ({count} invoice(s)):
{audit_data}
"""


def get_audit_chatbot_response(
    messages: List[Dict[str, str]],
    workflow_id: Optional[str] = None,
) -> str:
    """
    Chatbot that answers ONLY questions about the invoice_audit_results collection.
    Uses the full conversation history for context.
    workflow_id: if provided, only loads records for that workflow.
    """
    audit_records = get_invoice_audit_results(workflow_id)

    # Strip binary fields and keep only what's useful for the LLM
    clean_records = []
    for r in audit_records:
        clean_records.append({
            "invoice_number":  r.get("invoice_number"),
            "supplier_name":   r.get("supplier_name"),
            "supplier_email":  r.get("supplier_email"),
            "filename":        r.get("filename"),
            "from_email":      r.get("from_email"),
            "total_cost":      r.get("total_cost"),
            "audit_status":    r.get("audit_status"),
            "items":           r.get("items", []),
            "discrepancies":   r.get("discrepancies", []),
            "passed_checks":   r.get("passed_checks", []),
            "audited_at":      str(r.get("audited_at", "")),
        })

    system_prompt = _AUDIT_CHATBOT_SYSTEM.format(
        count=len(clean_records),
        audit_data=json.dumps(clean_records, indent=2, default=str),
    )

    llm = get_langchain_llm(temperature=0.2)
    chat_messages: List[tuple] = [("system", system_prompt)]
    for m in messages:
        role = m["role"] if m["role"] in ("user", "assistant") else "user"
        chat_messages.append((role, m["content"]))

    response = llm.invoke(chat_messages)
    return response.content


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditorService:
    """
    Service class registered with the Supervisor.
    Processes PDF invoices and emits AuditCompletedPayload → Supervisor.
    """

    def process_pdf_batch(
        self,
        pdf_files: List[Any],
        workflow_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process a list of PDF file objects.
        Emits one AuditCompletedPayload per invoice through the Supervisor.
        Returns the full batch result list for UI rendering.
        """
        from orchestrator.supervisor import get_supervisor
        import uuid

        results: List[Dict[str, Any]] = []
        wf_id = workflow_id or f"WF-AUDIT-{uuid.uuid4().hex[:8].upper()}"

        for pdf_file in pdf_files:
            raw_text    = extract_text_from_pdf(pdf_file)
            parsed_inv  = parse_invoice_with_llm(raw_text)
            audit_result = run_audit_validation(parsed_inv)

            # Build Pydantic payload
            line_items = [
                InvoiceLineItem(
                    product_name=item.product_name,
                    count=item.count,
                    cost_price=item.cost_price,
                )
                for item in parsed_inv.items
            ]
            invoice_data = SupplierInvoiceData(
                invoice_number=parsed_inv.invoice_number,
                supplier_name=parsed_inv.supplier_name,
                supplier_email=parsed_inv.supplier_email,
                items=line_items,
                total_cost=parsed_inv.total_cost,
            )
            payload = AuditCompletedPayload(
                workflow_id    = wf_id,
                invoice_data   = invoice_data,
                audit_status   = audit_result["audit_status"],
                discrepancies  = audit_result["discrepancies"],
                passed_checks  = audit_result["passed_checks"],
                status         = WorkflowStatus.SUCCESS,
            )

            try:
                get_supervisor().route(payload)
            except Exception as exc:
                from orchestrator.logger import logger
                logger.warning(
                    "Supervisor routing failed for AuditCompletedPayload: %s", exc
                )

            results.append({
                "filename":  getattr(pdf_file, "name", "unknown.pdf"),
                "parsed":    parsed_inv,
                "audit":     audit_result["audit_entry"],
            })

        return results

    def get_all_audit_logs(self) -> List[Dict[str, Any]]:
        """Return all records from invoice_audit_results (private Agent 4 collection)."""
        return get_invoice_audit_results()

    def trigger_audit(self, workflow_id: str) -> Dict[str, Any]:
        """Trigger Agent 4 to process all unaudited PDFs for a given workflow."""
        return trigger_audit_from_stored_pdfs(workflow_id)

    def get_stored_pdf_count(self, workflow_id: str) -> Dict[str, int]:
        """Return counts of stored / audited PDFs for a workflow."""
        total    = col("einvoice_store").count_documents({"workflow_id": workflow_id})
        audited  = col("einvoice_store").count_documents({"workflow_id": workflow_id, "audited": True})
        pending  = total - audited
        return {"total": total, "audited": audited, "pending": pending}

    def sync_inventory_from_csv(self, records: List[Dict[str, Any]]) -> int:
        """Replace inventory collection contents from CSV upload."""
        col("inventory").delete_many({})
        if records:
            col("inventory").insert_many(records)
        return len(records)

    def sync_billing_from_csv(self, records: List[Dict[str, Any]]) -> int:
        """Replace billing collection contents from CSV upload."""
        col("billing").delete_many({})
        if records:
            col("billing").insert_many(records)
        return len(records)


def register_with_supervisor() -> InvoiceAuditorService:
    from orchestrator.supervisor import get_supervisor
    service = InvoiceAuditorService()
    get_supervisor().register_agent(AgentID.INVOICE_AUDITOR, service)
    return service
