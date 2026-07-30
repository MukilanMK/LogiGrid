"""
agents/quote_evaluator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 3 — Quote Evaluation & Awarding Agent

Core logic (preserved from original agent3/app.py):
  • parse_quotes()          — extract structured data from email bodies
  • _build_combo_quote()    — greedy partial-supplier combination logic
  • rank_quotes()           — LLM-based ranking with combo vs single comparison
  • generate_draft_emails() — personalised PO acceptance / rejection drafts
  • send_single_email()     — SMTP dispatch
  • check_confirmation_reply() — LLM confirmation check for combo orders

Integration:
  • ingest_quotes()   — entry point called by Supervisor
  • Emits POIssuedPayload → Supervisor after contract award
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from core.config import settings
from core.llm_client import get_groq_client
from orchestrator.data_contracts import (
    AgentID,
    POIssuedPayload,
    QuotesReceivedPayload,
    RankedSupplierEntry,
    WorkflowStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC RESPONSE MODELS  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

class QuoteExtraction(BaseModel):
    amount:            float
    date:              str
    quoted_items:      List[str]
    quoted_quantities: Dict[str, int]
    itemized_costs:    Dict[str, float]


class RankedSupplier(BaseModel):
    rank:                int
    supplier_id:         str
    supplier_name:       str
    total_quoted_amount: float
    delivery_date:       str
    justification:       str


class CategoryEvaluationResult(BaseModel):
    category:          str
    ranked_suppliers:  List[RankedSupplier]
    selected_winner_id: str


class ConfirmationExtraction(BaseModel):
    confirmed: bool
    reason:    str


# ─────────────────────────────────────────────────────────────────────────────
# QUOTE EVALUATOR SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class QuoteEvaluatorService:

    def __init__(self):
        self._pending_quotes: Dict[str, QuotesReceivedPayload] = {}

    # ── Groq helper ──────────────────────────────────────────────────────────

    def _call_groq(self, prompt: str, response_schema: Optional[type] = None) -> str:
        client = get_groq_client()
        kwargs: Dict[str, Any] = {
            "model":    settings.groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens":  1024,
        }
        if response_schema:
            schema_json = response_schema.model_json_schema()
            prompt += f"\n\nYou MUST return raw JSON adhering strictly to this schema: {json.dumps(schema_json)}"
            kwargs["messages"][0]["content"] = prompt
            kwargs["response_format"] = {"type": "json_object"}
        res = client.chat.completions.create(**kwargs)
        return res.choices[0].message.content

    # ── Email parsing ─────────────────────────────────────────────────────────

    def parse_quotes(
        self,
        category:        str,
        requested_items: List[Dict[str, Any]],
        supplier_replies: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract structured quote data from raw email bodies.
        Builds combo quotes from partial responses if needed.
        (Original logic preserved exactly.)
        """
        received_quotes: List[Dict[str, Any]] = []

        for reply in supplier_replies:
            s_id    = str(reply.get("supplier_id"))
            s_email = str(reply.get("supplier_email"))
            body    = str(reply.get("email_body", ""))

            prompt = (
                "Extract structured details from this quote reply email:\n"
                "- total quoted amount (float)\n"
                "- delivery date (YYYY-MM-DD)\n"
                "- quoted_items (list of item names)\n"
                "- quoted_quantities (dict mapping item name to integer quantity)\n"
                "- itemized_costs (dict mapping item name to float unit cost)\n\n"
                f"Email Content:\n{body}"
            )
            raw_ext = self._call_groq(prompt, response_schema=QuoteExtraction)
            try:
                ext = json.loads(raw_ext)
                received_quotes.append({
                    "supplier_id":        s_id,
                    "supplier_name":      reply.get("supplier_name", s_id),  # carry name through
                    "supplier_email":     s_email,
                    "category":           category,
                    "quoted_amount":      ext.get("amount", 0.0),
                    "delivery_date":      ext.get("date", "Unknown"),
                    "quoted_items":       ext.get("quoted_items", []),
                    "quoted_quantities":  ext.get("quoted_quantities", {}),
                    "itemized_costs":     ext.get("itemized_costs", {}),
                    "is_combination":     False,
                })
            except Exception:
                pass

        req_item_map = {
            str(i.get("name", "")).lower(): int(i.get("quantity", 0))
            for i in requested_items
        }

        full_quotes:    List[Dict[str, Any]] = []
        partial_quotes: List[Dict[str, Any]] = []

        for q in received_quotes:
            is_full = True
            for r_name, r_qty in req_item_map.items():
                matched = sum(
                    q_qty for q_name, q_qty in q.get("quoted_quantities", {}).items()
                    if r_name in str(q_name).lower()
                )
                if matched < r_qty:
                    is_full = False
                    break
            (full_quotes if is_full else partial_quotes).append(q)

        # Greedy combo from partials (original algorithm preserved)
        if len(partial_quotes) > 1:
            remaining = req_item_map.copy()
            selected: List[Dict[str, Any]] = []

            def score(q: Dict[str, Any]) -> int:
                return sum(
                    q_qty for q_name, q_qty in q.get("quoted_quantities", {}).items()
                    if any(r in str(q_name).lower() for r in remaining)
                )

            sorted_partials = sorted(partial_quotes, key=score, reverse=True)

            for pq in sorted_partials:
                useful = False
                taken: Dict[str, int] = {}
                for q_name, q_qty in pq.get("quoted_quantities", {}).items():
                    for r_name in list(remaining.keys()):
                        if r_name in str(q_name).lower() and remaining[r_name] > 0:
                            useful = True
                            taken_qty = min(q_qty, remaining[r_name])
                            remaining[r_name] -= taken_qty
                            taken[str(q_name)] = taken_qty
                            if remaining[r_name] == 0:
                                del remaining[r_name]
                if useful:
                    pq["allocated_items"] = taken
                    selected.append(pq)
                if not remaining:
                    break

            if not remaining:
                combo: Dict[str, Any] = {
                    "supplier_id":   "COMBO_" + "_".join(q["supplier_id"] for q in selected),
                    "supplier_email": " & ".join(q["supplier_email"] for q in selected),
                    "is_combination": True,
                    "component_quotes": selected,
                    "quoted_amount":    sum(q["quoted_amount"] for q in selected),
                    "delivery_date":    max((q["delivery_date"] for q in selected), default="Unknown"),
                    "category":         category,
                }
                received_quotes.append(combo)

        return received_quotes

    # ── Ranking ───────────────────────────────────────────────────────────────

    def rank_quotes(
        self,
        category:        str,
        quotes:          List[Dict[str, Any]],
        requested_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Deterministic ranking — the LLM is NOT used for the ordering decision.

        Priority tiers (Rank 1 = highest priority):
          Tier 1  —  Full-fulfillment single supplier
          Tier 2  —  Combo (multi-supplier) that covers 100 % of items
          Tier 3  —  Partial / unfulfilled single suppliers

        Within any tier:
          1. Lower total quoted_amount wins.
          2. On equal price: higher supplier trust_score wins
             (fetched from the MongoDB suppliers collection).
          3. On equal trust score: earlier delivery_date wins.

        The LLM is called once per supplier only to write a short
        human-readable justification sentence — it has no effect on order.
        """
        from core.db import col as _db_col

        # ── Build requested-items map for fulfillment check ───────────────────
        req_map: Dict[str, int] = {}
        if requested_items:
            for item in requested_items:
                name = str(item.get("name", item.get("item_name", ""))).lower().strip()
                qty  = int(item.get("quantity", 0))
                if name:
                    req_map[name] = qty

        def _fulfillment_tier(q: Dict[str, Any]) -> int:
            """
            0 = full single supplier
            1 = combo (treated as full coverage)
            2 = partial single supplier
            """
            if q.get("is_combination"):
                return 1

            if not req_map:
                # No requested items in context — treat every single as full
                return 0

            qty_supplied = q.get("quoted_quantities", {})
            for r_name, r_qty in req_map.items():
                covered = sum(
                    v for k, v in qty_supplied.items()
                    if r_name in k.lower()
                )
                if covered < r_qty:
                    return 2   # at least one item under-supplied → partial
            return 0

        # ── Fetch trust scores from MongoDB (single query) ────────────────────
        trust_scores: Dict[str, float] = {}
        try:
            all_suppliers = list(_db_col("suppliers").find({}, {"supplier_id": 1, "trust_score": 1, "_id": 0}))
            for s in all_suppliers:
                sid = str(s.get("supplier_id", ""))
                if sid:
                    trust_scores[sid] = float(s.get("trust_score", 100.0))
        except Exception:
            pass  # if DB is down, trust scores default to 100

        def _get_trust(q: Dict[str, Any]) -> float:
            # For combos, use the average of component trust scores
            if q.get("is_combination"):
                scores = [
                    trust_scores.get(str(c.get("supplier_id", "")), 100.0)
                    for c in q.get("component_quotes", [])
                ]
                return sum(scores) / len(scores) if scores else 100.0
            return trust_scores.get(str(q.get("supplier_id", "")), 100.0)

        def _delivery_ordinal(d: str) -> int:
            """Convert 'YYYY-MM-DD' to integer days from epoch for comparison."""
            import datetime as _dt
            try:
                return (_dt.date.fromisoformat(d) - _dt.date(2000, 1, 1)).days
            except Exception:
                return 99999  # unknown date goes last

        # ── Sort by (tier ASC, amount ASC, trust DESC, delivery ASC) ──────────
        scored = []
        for q in quotes:
            tier    = _fulfillment_tier(q)
            amount  = float(q.get("quoted_amount", 0.0))
            trust   = _get_trust(q)
            deliv   = _delivery_ordinal(str(q.get("delivery_date", "")))
            scored.append((tier, amount, -trust, deliv, q))   # negate trust so higher = better

        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

        # ── Combo vs full-single cost comparison (may swap Tier-0 and Tier-1) ─
        # If the cheapest full single-supplier is MORE expensive than the combo,
        # the combo earns a higher rank than that single supplier.
        # (Tier-0 entries cheaper than the combo stay ahead.)
        best_combo_amount = next(
            (float(q.get("quoted_amount", 0)) for t, _, _, _, q in scored if t == 1),
            float("inf"),
        )
        re_sorted = []
        for entry in scored:
            tier, amount, neg_trust, deliv, q = entry
            # Full single supplier that costs MORE than the combo → demote to tier 1.5
            # Represented as tier=1 with a tiny offset so they sort after combos.
            # We model this by keeping tier=1 for combos and using 0.5 for costlier singles.
            effective_tier = tier
            if tier == 0 and amount > best_combo_amount:
                effective_tier = 1   # treat it same tier as combo
            re_sorted.append((effective_tier, amount, neg_trust, deliv, q))

        re_sorted.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

        # ── Assign sequential ranks ───────────────────────────────────────────
        ranked_quotes = [entry[4] for entry in re_sorted]

        tier_labels = {0: "Full fulfillment", 1: "Combo / cost-comparable", 2: "Partial fulfillment"}

        # ── LLM: one justification sentence per supplier (non-blocking) ───────
        def _justification(q: Dict[str, Any], rank: int, tier: int) -> str:
            try:
                name   = q.get("supplier_name") or q.get("supplier_email", q["supplier_id"])
                amount = q.get("quoted_amount", 0)
                trust  = _get_trust(q)
                tier_l = tier_labels.get(tier, "")
                prompt = (
                    f"Write ONE concise sentence (max 25 words) explaining why "
                    f"'{name}' is ranked #{rank} for the '{category}' procurement.\n"
                    f"Facts: {tier_l}, total ₹{amount:,.0f}, trust score {trust:.0f}/100."
                )
                resp = get_groq_client().chat.completions.create(
                    model=settings.groq_model_fast,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=60,
                )
                return resp.choices[0].message.content.strip()
            except Exception:
                tier_l = tier_labels.get(tier, "")
                t      = _get_trust(q)
                return (
                    f"Ranked #{rank}: {tier_l}, "
                    f"₹{q.get('quoted_amount', 0):,.0f}, trust {t:.0f}/100."
                )

        ranked_suppliers = []
        for rank, q in enumerate(ranked_quotes, start=1):
            tier = _fulfillment_tier(q)
            # Recalculate effective tier for label (same logic as above)
            if tier == 0 and float(q.get("quoted_amount", 0)) > best_combo_amount:
                tier = 1
            ranked_suppliers.append({
                "rank":                rank,
                "supplier_id":         q["supplier_id"],
                "supplier_name":       (
                    q.get("supplier_name")
                    or q.get("supplier_email", q["supplier_id"])
                ),
                "total_quoted_amount": float(q.get("quoted_amount", 0.0)),
                "delivery_date":       str(q.get("delivery_date", "Unknown")),
                "trust_score":         round(_get_trust(q), 1),
                "fulfillment_tier":    tier_labels.get(tier, "Unknown"),
                "justification":       _justification(q, rank, tier),
            })

        winner = ranked_quotes[0] if ranked_quotes else {}
        return {
            "category":           category,
            "selected_winner_id": winner.get("supplier_id", ""),
            "ranked_suppliers":   ranked_suppliers,
        }

    # ── Draft generation ──────────────────────────────────────────────────────

    def generate_draft_emails(
        self,
        category:       str,
        ranking_result: Dict[str, Any],
        quotes:         List[Dict[str, Any]],
        sender_info:    Dict[str, str],
        winner_id:      str,
        is_combo_confirmation: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generate acceptance / rejection / confirmation-request email drafts."""
        winner_quote = next(
            (q for q in quotes if q["supplier_id"] == winner_id), None
        ) or next(
            (q for q in quotes if q.get("supplier_email", "") == winner_id), None
        )
        if winner_quote is None:
            return []
        drafts:          List[Dict[str, Any]] = []
        accepted_emails: set = set()

        if winner_quote.get("is_combination"):
            for comp in winner_quote["component_quotes"]:
                accepted_emails.add(comp["supplier_email"])
                items_str = "\n".join(
                    f"- {k}: {v} units"
                    for k, v in comp.get("allocated_items", {}).items()
                )
                if is_combo_confirmation:
                    prompt = (
                        f"Draft a warm, professional CONFIRMATION REQUEST email to '{comp['supplier_email']}'.\n"
                        f"We want to award them a partial order.\n"
                        f"Context:\n- Category: {category}\n"
                        f"- Allocated items:\n{items_str}\n"
                        f"- Total Amount for their part: ₹{comp['quoted_amount']}\n\n"
                        "Ask them to reply YES if they can fulfill this partial order at this pricing.\n"
                        "IMPORTANT: Also explicitly request that once they confirm, they must reply to "
                        "this email with a formal PDF e-invoice (GST-compliant) as an attachment, "
                        "which is required for our internal audit process before payment can be released.\n"
                        f"Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}."
                    )
                    status = "CONFIRMATION_REQUEST"
                    subject = f"Please Confirm Partial Order: {category.title()} Procurement"
                else:
                    prompt = (
                        f"Draft a warm, professional purchase order ACCEPTANCE email to '{comp['supplier_email']}'.\n"
                        f"Context:\n- Category: {category}\n"
                        f"- Allocated items:\n{items_str}\n"
                        f"- Amount: ₹{comp['quoted_amount']}\n\n"
                        "IMPORTANT: In the email, explicitly request that the supplier reply to this "
                        "email with a formal PDF e-invoice (GST-compliant) as an email attachment. "
                        "Explain that the e-invoice is mandatory for our internal audit and payment "
                        "processing cannot begin until it is received.\n"
                        f"Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}."
                    )
                    status = "ACCEPTED"
                    subject = f"ACCEPTANCE & PO AWARD: {category.title()} Procurement"

                body = self._call_groq(prompt)
                drafts.append({
                    "to":            comp["supplier_email"],
                    "supplier_name": comp["supplier_id"],
                    "status":        status,
                    "subject":       subject,
                    "body":          body,
                    "type":          "confirmation" if is_combo_confirmation else "acceptance",
                })
        else:
            accepted_emails.add(winner_quote["supplier_email"])
            if not is_combo_confirmation:
                prompt = (
                    f"Draft a warm, professional purchase order ACCEPTANCE email to '{winner_quote['supplier_email']}'.\n"
                    f"Context:\n- Category: {category}\n"
                    f"- Quoted Price: ₹{winner_quote['quoted_amount']}\n"
                    f"- Delivery Date: {winner_quote['delivery_date']}\n"
                    f"- Items: {', '.join(winner_quote.get('quoted_items', []))}\n\n"
                    "IMPORTANT: In the email, explicitly request that the supplier reply to this "
                    "email with a formal PDF e-invoice (GST-compliant, with GSTIN, HSN codes, "
                    "and itemised amounts) as an email attachment. "
                    "Explain that the PDF e-invoice is mandatory for our internal audit and payment "
                    "processing will not begin until the e-invoice is received and verified.\n"
                    f"Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}."
                )
                body = self._call_groq(prompt)
                drafts.append({
                    "to":            winner_quote["supplier_email"],
                    "supplier_name": winner_quote["supplier_id"],
                    "status":        "ACCEPTED",
                    "subject":       f"ACCEPTANCE & PO AWARD: {category.title()} Procurement",
                    "body":          body,
                    "type":          "acceptance",
                })

        # Rejection drafts (only on final award pass, not confirmation stage)
        if not is_combo_confirmation:
            for q in quotes:
                if q.get("is_combination"):
                    continue
                if q["supplier_email"] not in accepted_emails:
                    prompt = (
                        f"Draft a polite, highly personalized REJECTION email to vendor '{q['supplier_email']}'.\n"
                        f"Context:\n- Category: {category}\n"
                        f"- Quoted Price: ₹{q['quoted_amount']}\n"
                        f"- Delivery Date: {q['delivery_date']}\n\n"
                        f"Explicitly mention their quoted price of ₹{q['quoted_amount']} so they know it is personalized.\n"
                        f"Sign off: {sender_info.get('name')}, {sender_info.get('title')} at "
                        f"{sender_info.get('company')}, {sender_info.get('location', '')}."
                    )
                    body = self._call_groq(prompt)
                    drafts.append({
                        "to":            q["supplier_email"],
                        "supplier_name": q["supplier_id"],
                        "status":        "REJECTED",
                        "subject":       f"Update regarding your quote for {category.title()}",
                        "body":          body,
                        "type":          "rejection",
                    })
        return drafts

    def check_confirmation_reply(self, email_body: str) -> bool:
        """LLM check: did the supplier confirm a partial order?"""
        prompt = (
            "Analyze this email reply from a supplier to determine if they are "
            "CONFIRMING our partial order request.\n"
            "Reply YES (true) if they agree to the terms or say yes. "
            "Reply NO (false) if they reject or demand changes.\n\n"
            f"Email Body:\n{email_body}"
        )
        raw = self._call_groq(prompt, response_schema=ConfirmationExtraction)
        try:
            return json.loads(raw).get("confirmed", False)
        except Exception:
            return False

    # ── SMTP dispatch ─────────────────────────────────────────────────────────

    def send_single_email(self, to_email: str, subject: str, body: str) -> None:
        """
        Send one email via SMTP.
        Tries STARTTLS on port 587 first (standard Gmail).
        Raises on failure so the caller can surface the error to the UI.
        """
        if not settings.email_address or not settings.email_password:
            raise RuntimeError(
                "Email credentials not configured. "
                "Set EMAIL_ADDRESS and EMAIL_PASSWORD in your .env file."
            )
        msg = MIMEMultipart("alternative")
        msg["From"]    = settings.email_address
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.email_address, settings.email_password)
                server.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            raise RuntimeError(
                "SMTP authentication failed. "
                "For Gmail, use an App Password (not your regular password). "
                "Generate one at myaccount.google.com → Security → App passwords."
            )
        except smtplib.SMTPException as exc:
            raise RuntimeError(f"SMTP error while sending to {to_email}: {exc}")

    # ── Supervisor entry point ────────────────────────────────────────────────

    def ingest_quotes(self, payload: QuotesReceivedPayload) -> None:
        """Store the incoming quotes payload for later evaluation via UI or API."""
        self._pending_quotes[payload.workflow_id] = payload

    def award_and_emit_po(
        self,
        workflow_id:  str,
        winner_id:    str,
        sender_info:  Dict[str, str],
        ranking_result: Dict[str, Any],
        quotes:       List[Dict[str, Any]],
    ) -> POIssuedPayload:
        """
        Award the contract, build POIssuedPayload, and route through Supervisor.
        Called after the user confirms the winner in the UI.
        """
        from orchestrator.supervisor import get_supervisor

        # Safe winner lookup: match by supplier_id first, then by email as fallback
        winner_quote = next(
            (q for q in quotes if q["supplier_id"] == winner_id), None
        ) or next(
            (q for q in quotes if q.get("supplier_email", "") == winner_id), None
        )
        if winner_quote is None:
            raise ValueError(
                f"award_and_emit_po: could not find quote for winner_id='{winner_id}'. "
                f"Available supplier_ids: {[q['supplier_id'] for q in quotes]}"
            )
        category = winner_quote.get("category", "General")

        ranked_entries = [
            RankedSupplierEntry(
                rank                = r["rank"],
                supplier_id         = r["supplier_id"],
                supplier_name       = r.get("supplier_name", r["supplier_id"]),
                total_quoted_amount = r["total_quoted_amount"],
                delivery_date       = r["delivery_date"],
                justification       = r.get("justification", ""),
            )
            for r in ranking_result.get("ranked_suppliers", [])
        ]

        # quoted_items is List[str] — convert to List[Dict] as required by POIssuedPayload.
        # Also handle combo orders where component quantities are available.
        raw_items = winner_quote.get("quoted_items", [])
        qty_map   = winner_quote.get("quoted_quantities", {})
        cost_map  = winner_quote.get("itemized_costs", {})

        def _item_to_dict(item: Any) -> Dict[str, Any]:
            if isinstance(item, dict):
                return item
            # item is a string — enrich with quantity and unit cost if available
            name = str(item)
            return {
                "item_name":  name,
                "quantity":   qty_map.get(name, 0),
                "unit_cost":  cost_map.get(name, 0.0),
            }

        line_items_dicts = [_item_to_dict(i) for i in raw_items]

        payload = POIssuedPayload(
            workflow_id         = workflow_id,
            category            = category,
            winner_supplier_id  = winner_id,
            winner_email        = winner_quote.get("supplier_email", ""),
            total_po_amount     = float(winner_quote.get("quoted_amount", 0.0)),
            delivery_date       = str(winner_quote.get("delivery_date", "Unknown")),
            line_items          = line_items_dicts,
            ranked_suppliers    = ranked_entries,
            is_combo_order      = bool(winner_quote.get("is_combination", False)),
            status              = WorkflowStatus.SUCCESS,
        )

        get_supervisor().route(payload)
        return payload


def register_with_supervisor() -> QuoteEvaluatorService:
    from orchestrator.supervisor import get_supervisor
    service = QuoteEvaluatorService()
    get_supervisor().register_agent(AgentID.QUOTE_EVALUATOR, service)
    return service
