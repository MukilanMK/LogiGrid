"""
agents/rfq_matcher.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 2 — Supplier Category Matcher & RFQ Dispatcher

Core logic (preserved from original agent2/app_email.py):
  • generate_email()   — Groq LLM-generated personalised inquiry email
  • send_email()       — SMTP dispatch + sent timestamp logging
  • fetch_recent_emails() — IMAP inbox polling for replies
  • trigger_rfq_from_stock_alert() — Supervisor-triggered entry point

Integration:
  • Receives StockAlertPayload from Supervisor
  • Emits RFQDispatchedPayload back to Supervisor
  • Emits QuotesReceivedPayload to Supervisor when replies detected
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import datetime
import email
import email.utils
import imaplib
import json
import smtplib
from email.header import decode_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings
from core.llm_client import get_groq_client
from orchestrator.data_contracts import (
    AgentID,
    RFQDispatchedPayload,
    QuotesReceivedPayload,
    StockAlertPayload,
    SupplierQuote,
    WorkflowStatus,
)

# Sent-timestamp log lives inside the package directory
_SENT_LOG = Path(__file__).parent.parent / "sent_timestamps.json"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_sent_times() -> Dict[str, str]:
    if _SENT_LOG.exists():
        try:
            return json.loads(_SENT_LOG.read_text())
        except Exception:
            pass
    return {}


def _save_sent_times(data: Dict[str, str]) -> None:
    try:
        _SENT_LOG.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL GENERATOR  (original Groq prompt preserved)
# ─────────────────────────────────────────────────────────────────────────────

def generate_inquiry_email(
    user_name:      str,
    user_company:   str,
    user_location:  str,
    seller_name:    str,
    seller_category: str,
    product_details: str,
) -> str:
    """Generate a personalised RFQ inquiry email via Groq LLM."""
    prompt = (
        f"You are {user_name} from {user_company} located in {user_location}.\n"
        f"Write a professional and personalized inquiry email to {seller_name}, "
        f"a supplier of {seller_category}.\n\n"
        f"We are interested in the following products:\n{product_details}\n\n"
        "In the email, please explicitly ask the seller about:\n"
        "1. Date of delivery\n"
        "2. Available quantity\n"
        "3. Advance payment requirements\n"
        "4. Terms in case of a return\n\n"
        "Make it concise and professional. Do not include placeholders, "
        "use the provided information."
    )
    client = get_groq_client()
    resp = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=settings.groq_model_fast,
    )
    return resp.choices[0].message.content


# ─────────────────────────────────────────────────────────────────────────────
# SMTP SEND
# ─────────────────────────────────────────────────────────────────────────────

def send_rfq_email(
    to_email: str,
    subject:  str,
    body:     str,
) -> tuple[bool, str]:
    """Send an email via SMTP and record the sent timestamp."""
    if not settings.email_address or not settings.email_password:
        return False, "Email credentials not configured."
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"]    = settings.email_address
        msg["To"]      = to_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(settings.email_address, settings.email_password)
            smtp.send_message(msg)

        sent_times = _load_sent_times()
        sent_times[to_email] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_sent_times(sent_times)
        return True, "Email sent successfully."
    except Exception as exc:
        return False, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# IMAP FETCH  (original logic preserved)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_recent_emails(limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch the most recent inbox emails via IMAP."""
    if not settings.email_address or not settings.email_password:
        return []
    try:
        mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        mail.login(settings.email_address, settings.email_password)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")
        if status != "OK":
            return []

        email_ids    = messages[0].split()
        latest_ids   = email_ids[-limit:]
        emails_data: List[Dict[str, Any]] = []

        for e_id in reversed(latest_ids):
            status, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, enc = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(enc if enc else "utf-8", errors="ignore")

                    from_ = msg.get("From", "")
                    date_ = msg.get("Date")
                    dt    = None
                    if date_:
                        try:
                            dt = email.utils.parsedate_to_datetime(date_)
                        except Exception:
                            pass

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                    emails_data.append({
                        "from":    from_,
                        "subject": subject,
                        "body":    body,
                        "date":    dt,
                    })
        mail.logout()
        return emails_data
    except Exception:
        return []


def check_for_replies(supplier_emails: List[str]) -> Dict[str, bool]:
    """
    Check whether each supplier in the list has replied since the RFQ was sent.
    Returns {email: has_replied}.
    """
    recent  = fetch_recent_emails(30)
    sent_times = _load_sent_times()
    results: Dict[str, bool] = {}

    for s_email in supplier_emails:
        sent_time_str = sent_times.get(s_email)
        sent_time     = None
        if sent_time_str:
            try:
                sent_time = datetime.datetime.fromisoformat(sent_time_str)
            except Exception:
                pass

        has_replied = False
        for m in recent:
            if s_email.lower() in str(m["from"]).lower():
                reply_date = m.get("date")
                if sent_time and reply_date:
                    if reply_date > sent_time:
                        has_replied = True
                        break
                else:
                    has_replied = True
                    break

        results[s_email] = has_replied
    return results


# ─────────────────────────────────────────────────────────────────────────────
# E-INVOICE EMAIL FETCHER
# ─────────────────────────────────────────────────────────────────────────────

def fetch_invoice_attachment_emails(
    filter_senders: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Poll the IMAP inbox for emails that carry PDF attachments (e-invoices).

    Parameters
    ----------
    filter_senders : list of email addresses to restrict search to (the awarded suppliers).
                     If None or empty, all emails with PDF attachments are returned.
    limit          : maximum number of recent emails to inspect.

    Returns
    -------
    List of dicts:
        {
            "from":        str,
            "subject":     str,
            "date":        datetime | None,
            "body":        str,
            "attachments": [(filename: str, bytes: bytes), ...]
        }
    Only emails that have at least one PDF attachment are included.
    """
    if not settings.email_address or not settings.email_password:
        return []

    results: List[Dict[str, Any]] = []

    try:
        mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        mail.login(settings.email_address, settings.email_password)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")
        if status != "OK":
            mail.logout()
            return []

        email_ids  = messages[0].split()
        latest_ids = email_ids[-limit:]

        for e_id in reversed(latest_ids):
            status, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if not isinstance(response_part, tuple):
                    continue

                msg = email.message_from_bytes(response_part[1])

                # Decode subject
                subject_raw, enc = decode_header(msg["Subject"] or "")[0]
                if isinstance(subject_raw, bytes):
                    subject = subject_raw.decode(enc if enc else "utf-8", errors="ignore")
                else:
                    subject = subject_raw or ""

                from_ = msg.get("From", "")
                date_ = msg.get("Date")
                dt    = None
                if date_:
                    try:
                        dt = email.utils.parsedate_to_datetime(date_)
                    except Exception:
                        pass

                # Filter by sender if requested
                if filter_senders:
                    from_lower = from_.lower()
                    # extract bare address from "Name <addr>" format
                    if "<" in from_lower:
                        bare = from_lower.split("<")[1].rstrip(">").strip()
                    else:
                        bare = from_lower.strip()
                    if not any(s.lower() in bare or s.lower() in from_lower
                               for s in filter_senders):
                        continue

                # Extract body text and PDF attachments
                body        = ""
                attachments: List[tuple] = []

                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get("Content-Disposition", ""))

                        if ctype == "text/plain" and "attachment" not in cdispo and not body:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")

                        # Capture PDF attachments
                        if ctype == "application/pdf" or (
                            "attachment" in cdispo and
                            part.get_filename("").lower().endswith(".pdf")
                        ):
                            filename = part.get_filename() or "invoice.pdf"
                            pdf_bytes = part.get_payload(decode=True)
                            if pdf_bytes:
                                attachments.append((filename, pdf_bytes))
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                # Only include emails that actually have PDF attachments
                if attachments:
                    results.append({
                        "from":        from_,
                        "subject":     subject,
                        "date":        dt,
                        "body":        body,
                        "attachments": attachments,
                    })

        mail.logout()
    except Exception:
        pass

    return results


# ─────────────────────────────────────────────────────────────────────────────
# E-INVOICE PDF STORE  (Agent 3 → MongoDB)
# ─────────────────────────────────────────────────────────────────────────────

def store_einvoice_pdfs_from_inbox(
    winner_emails: List[str],
    workflow_id:   str,
    limit:         int = 50,
) -> Dict[str, Any]:
    """
    Poll the IMAP inbox for reply emails from awarded suppliers that contain
    PDF attachments.  Each PDF is stored in MongoDB `einvoice_store` collection
    using bson.binary.Binary so it can be retrieved and processed by Agent 4.

    Deduplication: a document is skipped if an entry with the same
    (workflow_id, from_email, filename) already exists.

    Returns
    -------
    {
        "stored":   int,   # new PDFs written to DB
        "skipped":  int,   # already existed
        "total":    int,   # total attachments found
        "docs":     list,  # list of inserted doc summaries
    }
    """
    from bson.binary import Binary
    from core.db import col as _db_col
    import hashlib

    raw_emails = fetch_invoice_attachment_emails(
        filter_senders=winner_emails, limit=limit
    )

    stored  = 0
    skipped = 0
    docs    = []

    for mail_item in raw_emails:
        from_addr = mail_item["from"]
        # Extract bare email address
        bare = from_addr.lower()
        if "<" in bare:
            bare = bare.split("<")[1].rstrip(">").strip()

        for filename, pdf_bytes in mail_item.get("attachments", []):
            # Dedup: check by workflow + sender + filename + content hash
            content_hash = hashlib.sha256(pdf_bytes).hexdigest()
            existing = _db_col("einvoice_store").find_one({
                "workflow_id":   workflow_id,
                "from_email":    bare,
                "filename":      filename,
                "content_hash":  content_hash,
            })
            if existing:
                skipped += 1
                continue

            doc = {
                "workflow_id":    workflow_id,
                "from_email":     bare,
                "from_display":   from_addr,
                "email_subject":  mail_item.get("subject", ""),
                "email_date":     mail_item.get("date"),
                "filename":       filename,
                "pdf_data":       Binary(pdf_bytes),
                "content_hash":   content_hash,
                "size_bytes":     len(pdf_bytes),
                "stored_at":      datetime.datetime.now(datetime.timezone.utc),
                "audited":        False,   # flipped to True by Agent 4 after processing
            }
            _db_col("einvoice_store").insert_one(doc)
            stored += 1
            docs.append({
                "filename":    filename,
                "from_email":  bare,
                "size_bytes":  len(pdf_bytes),
            })

    return {
        "stored":  stored,
        "skipped": skipped,
        "total":   stored + skipped,
        "docs":    docs,
    }

class RFQMatcherService:
    """
    Service class registered with the Supervisor.
    Triggered by Supervisor when a StockAlertPayload arrives.
    """

    def __init__(
        self,
        sender_name:    str = "Procurement Manager",
        sender_company: str = "Supply Chain Ecosystem",
        sender_location: str = "India",
    ):
        self.sender_name     = sender_name
        self.sender_company  = sender_company
        self.sender_location = sender_location

    def trigger_rfq_from_stock_alert(self, payload: StockAlertPayload) -> None:
        """
        Called by Supervisor when StockAlertPayload arrives.
        Groups needed products by category, looks up suppliers, sends RFQ emails,
        and emits RFQDispatchedPayload back to Supervisor for each category.
        """
        from orchestrator.supervisor import get_supervisor
        from core.db import col as db_col

        supervisor = get_supervisor()

        categories: Dict[str, List[Any]] = {}
        for p in payload.needed_products:
            categories.setdefault(p.category, []).append(p)

        for category, products in categories.items():
            # Supplier schema uses "categories_supplied" (array field).
            # $in matches any supplier whose array contains this category.
            suppliers = list(db_col("suppliers").find({
                "categories_supplied": {"$in": [category]},
                "compliance_flag": {"$ne": True},
            }))

            if not suppliers:
                from orchestrator.logger import logger
                logger.info(
                    "[Agent2] No active suppliers found for category '%s' — skipping RFQ.",
                    category,
                )
                continue

            products_desc = "\n".join(
                f"- {p.product_name}: reorder qty {p.reorder_quantity} units"
                for p in products
            )

            contacted: List[Dict[str, str]] = []
            for supplier in suppliers:
                s_email = supplier.get("contact_email", "")
                s_name  = supplier.get("supplier_name", "Supplier")
                if not s_email:
                    continue

                email_body = generate_inquiry_email(
                    self.sender_name,
                    self.sender_company,
                    self.sender_location,
                    s_name,
                    category,
                    products_desc,
                )
                success, _ = send_rfq_email(
                    s_email,
                    f"Request for Quotation — {category}",
                    email_body,
                )
                if success:
                    contacted.append({
                        "supplier_id": supplier.get("supplier_id", ""),
                        "email":       s_email,
                        "sent_at":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    })

            rfq_payload = RFQDispatchedPayload(
                workflow_id          = payload.workflow_id,
                category             = category,
                contacted_suppliers  = contacted,
                product_details      = [p.model_dump() for p in products],
                status               = WorkflowStatus.SUCCESS,
            )
            supervisor.route(rfq_payload)

    def dispatch_manual(
        self,
        category:        str,
        supplier_emails: List[str],
        products_df_records: List[Dict[str, Any]],
        workflow_id:     Optional[str] = None,
    ) -> RFQDispatchedPayload:
        """
        Manual dispatch triggered from the Streamlit UI.
        Sends RFQ emails to the provided supplier emails and notifies Supervisor.
        """
        from orchestrator.supervisor import get_supervisor
        from core.db import col as db_col
        import uuid

        wf_id = workflow_id or f"WF-RFQ-{uuid.uuid4().hex[:8].upper()}"
        products_desc = "\n".join(
            f"- {r.get('name', 'Product')}: {r.get('description', '')}"
            for r in products_df_records
        )
        contacted: List[Dict[str, str]] = []
        for s_email in supplier_emails:
            sup_doc = db_col("suppliers").find_one({"contact_email": s_email}) or {}
            s_name  = sup_doc.get("supplier_name", s_email)

            email_body = generate_inquiry_email(
                self.sender_name, self.sender_company, self.sender_location,
                s_name, category, products_desc,
            )
            success, _ = send_rfq_email(
                s_email, f"Request for Quotation — {category}", email_body
            )
            if success:
                contacted.append({
                    "supplier_id": sup_doc.get("supplier_id", ""),
                    "email":       s_email,
                    "sent_at":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })

        payload = RFQDispatchedPayload(
            workflow_id         = wf_id,
            category            = category,
            contacted_suppliers = contacted,
            product_details     = products_df_records,
            status              = WorkflowStatus.SUCCESS,
        )
        get_supervisor().route(payload)
        return payload

    def build_quotes_received_payload(
        self,
        category:        str,
        requested_items: List[Dict[str, Any]],
        supplier_replies: List[Dict[str, Any]],
        workflow_id:     Optional[str] = None,
    ) -> QuotesReceivedPayload:
        """
        Build and route a QuotesReceivedPayload after parsing supplier emails.
        supplier_replies: list of {supplier_id, supplier_email, email_body}
        """
        from orchestrator.supervisor import get_supervisor
        import uuid

        wf_id = workflow_id or f"WF-QR-{uuid.uuid4().hex[:8].upper()}"

        quotes: List[SupplierQuote] = []
        for reply in supplier_replies:
            quotes.append(SupplierQuote(
                supplier_id    = str(reply.get("supplier_id", "")),
                supplier_email = str(reply.get("supplier_email", "")),
                category       = category,
                quoted_amount  = float(reply.get("quoted_amount", 0.0)),
                delivery_date  = str(reply.get("delivery_date", "Unknown")),
                quoted_items   = reply.get("quoted_items", []),
                quoted_quantities = reply.get("quoted_quantities", {}),
                itemized_costs    = reply.get("itemized_costs", {}),
            ))

        payload = QuotesReceivedPayload(
            workflow_id      = wf_id,
            category         = category,
            requested_items  = requested_items,
            supplier_quotes  = quotes,
            status           = WorkflowStatus.SUCCESS,
        )
        get_supervisor().route(payload)
        return payload


def register_with_supervisor(
    sender_name:    str = "Procurement Manager",
    sender_company: str = "Supply Chain Ecosystem",
    sender_location: str = "India",
) -> RFQMatcherService:
    from orchestrator.supervisor import get_supervisor
    service = RFQMatcherService(sender_name, sender_company, sender_location)
    get_supervisor().register_agent(AgentID.RFQ_MATCHER, service)
    return service
