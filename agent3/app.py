import email
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import imaplib
import json
import os
import smtplib
from typing import Dict, List, Optional
import time

from dotenv import load_dotenv
from groq import Groq
import pandas as pd
from pydantic import BaseModel
import streamlit as st

# Load Environment Variables
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Quote Evaluator & Awarding Agent",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ Quote Evaluation & Awarding Agent")

# ---------------------------------------------------------------------
# API & DATA MODELS
# ---------------------------------------------------------------------
MODEL_ID = "llama-3.3-70b-versatile"

class QuoteExtraction(BaseModel):
    amount: float
    date: str
    quoted_items: List[str]
    quoted_quantities: Dict[str, int]
    itemized_costs: Dict[str, float]

class RankedSupplier(BaseModel):
    rank: int
    supplier_id: str
    supplier_name: str
    total_quoted_amount: float
    delivery_date: str
    justification: str

class CategoryEvaluationResult(BaseModel):
    category: str
    ranked_suppliers: List[RankedSupplier]
    selected_winner_id: str

class ConfirmationExtraction(BaseModel):
    confirmed: bool
    reason: str

# ---------------------------------------------------------------------
# CORE SERVICE LOGIC
# ---------------------------------------------------------------------
class EvaluatorService:
    def __init__(self, groq_key: str, email_user: str, email_pass: str,
                 smtp_host: str, smtp_port: int, imap_host: str, imap_port: int):
        self.client = Groq(api_key=groq_key)
        self.email_user = email_user
        self.email_pass = email_pass
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.imap_host = imap_host
        self.imap_port = imap_port

    def _call_groq(self, prompt: str, response_schema: Optional[type] = None) -> str:
        kwargs = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        if response_schema:
            schema_json = response_schema.model_json_schema()
            prompt += f"\n\nYou MUST return raw JSON adhering strictly to this schema: {json.dumps(schema_json)}"
            kwargs["messages"][0]["content"] = prompt
            kwargs["response_format"] = {"type": "json_object"}

        try:
            res = self.client.chat.completions.create(**kwargs)
            return res.choices[0].message.content
        except Exception as e:
            st.error(f"Groq API Error: {e}")
            return "{}"

    def fetch_emails(self, valid_senders: List[str], limit: int = 10) -> List[dict]:
        fetched_emails = []
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            mail.login(self.email_user, self.email_pass)
            mail.select('inbox')
            
            # Fetch recent emails
            status, data = mail.search(None, 'ALL')
            mail_ids = data[0].split()
            
            if not mail_ids:
                return []
                
            recent_ids = mail_ids[-limit:]
            
            for m_id in reversed(recent_ids):
                status, msg_data = mail.fetch(m_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else "utf-8")
                        from_ = msg.get("From", "")
                        
                        # Extract email address
                        sender_email = from_
                        if "<" in from_ and ">" in from_:
                            sender_email = from_.split("<")[1].split(">")[0]
                        sender_email = sender_email.lower().strip()
                        
                        if sender_email in [s.lower().strip() for s in valid_senders]:
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                            
                            fetched_emails.append({
                                "from": sender_email,
                                "subject": subject,
                                "body": body
                            })
            mail.logout()
        except Exception as e:
            st.error(f"IMAP Fetch Error: {e}")
        return fetched_emails

    def parse_quotes(self, category: str, requested_items: List[dict],
                     supplier_replies: List[dict]) -> List[dict]:
        received_quotes = []

        for reply in supplier_replies:
            s_id = str(reply.get("supplier_id"))
            s_email = str(reply.get("supplier_email"))
            body = str(reply.get("email_body", ""))

            prompt = f"""
            Extract structured details from this quote reply email:
            - total quoted amount (float)
            - delivery date (YYYY-MM-DD)
            - quoted_items (list of item names)
            - quoted_quantities (dict mapping item name to integer quantity)
            - itemized_costs (dict mapping item name to float unit cost)

            Email Content:
            {body}
            """
            raw_ext = self._call_groq(prompt, response_schema=QuoteExtraction)
            try:
                ext = json.loads(raw_ext)
                received_quotes.append({
                    "supplier_id": s_id,
                    "supplier_email": s_email,
                    "category": category,
                    "quoted_amount": ext.get("amount", 0.0),
                    "delivery_date": ext.get("date", "Unknown"),
                    "quoted_items": ext.get("quoted_items", []),
                    "quoted_quantities": ext.get("quoted_quantities", {}),
                    "itemized_costs": ext.get("itemized_costs", {}),
                    "is_combination": False,
                })
            except Exception as e:
                st.warning(f"Failed to parse reply for {s_email}: {e}")

        req_item_map = {
            str(i.get("name", "")).lower(): int(i.get("quantity", 0))
            for i in requested_items
        }
        full_quotes = []
        partial_quotes = []

        for q in received_quotes:
            is_full = True
            quoted_qtys = q.get("quoted_quantities", {})
            for r_name, r_qty in req_item_map.items():
                matched_qty = sum(
                    q_qty for q_name, q_qty in quoted_qtys.items()
                    if r_name in str(q_name).lower())
                if matched_qty < r_qty:
                    is_full = False
                    break
            if is_full:
                full_quotes.append(q)
            else:
                partial_quotes.append(q)

        if len(partial_quotes) > 1:
            remaining = req_item_map.copy()
            selected_quotes = []

            def score(q):
                return sum(
                    q_qty for q_name, q_qty in q.get("quoted_quantities", {}).items()
                    if any(r in str(q_name).lower() for r in remaining))

            sorted_partials = sorted(partial_quotes, key=score, reverse=True)

            for pq in sorted_partials:
                useful = False
                taken_items = {}
                for q_name, q_qty in pq.get("quoted_quantities", {}).items():
                    for r_name in list(remaining.keys()):
                        if r_name in str(q_name).lower() and remaining[r_name] > 0:
                            useful = True
                            taken = min(q_qty, remaining[r_name])
                            remaining[r_name] -= taken
                            taken_items[str(q_name)] = taken
                            if remaining[r_name] == 0:
                                del remaining[r_name]
                if useful:
                    pq["allocated_items"] = taken_items
                    selected_quotes.append(pq)
                if not remaining:
                    break

            if not remaining:
                combo_quote = {
                    "supplier_id": "COMBO_" + "_".join([q["supplier_id"] for q in selected_quotes]),
                    "supplier_email": " & ".join([q["supplier_email"] for q in selected_quotes]),
                    "is_combination": True,
                    "component_quotes": selected_quotes,
                    "quoted_amount": sum(q["quoted_amount"] for q in selected_quotes),
                    "delivery_date": max((q["delivery_date"] for q in selected_quotes), default="Unknown"),
                    "category": category,
                }
                received_quotes.append(combo_quote)

        return received_quotes

    def rank_quotes(self, category: str, quotes: List[dict]) -> dict:
        prompt = f"""
        Analyze and rank these supplier proposals for '{category}' from best to worst (Rank 1 = Winner).
        Evaluation Criteria:
        - Compare single suppliers with 100% fulfillment against combination packages.
        - If a single source supplier's amount is higher than the combo quote amount, rank the combo quote higher.
        - If the single source is cheaper, rank the single source higher.
        - Rank unfulfilled (partial) single quotes lowest.
        - Balance low total cost with fastest delivery date.
        
        Proposals:
        {json.dumps(quotes, indent=2)}
        """
        raw = self._call_groq(prompt, response_schema=CategoryEvaluationResult)
        return json.loads(raw)

    def generate_draft_emails(self, category: str, ranking_result: dict,
                              quotes: List[dict],
                              sender_info: dict, winner_id: str, is_combo_confirmation: bool = False) -> List[dict]:
        winner_quote = next(q for q in quotes if q["supplier_id"] == winner_id)

        drafts = []
        accepted_emails = set()

        if winner_quote.get("is_combination"):
            if is_combo_confirmation:
                # We need to ask for confirmation first
                for comp in winner_quote["component_quotes"]:
                    accepted_emails.add(comp["supplier_email"])
                    items_str = "\n".join([
                        f"- {k}: {v} units"
                        for k, v in comp.get("allocated_items", {}).items()
                    ])
                    prompt = f"""
                    Draft a warm, professional CONFIRMATION REQUEST email to '{comp['supplier_email']}'.
                    We want to award them a partial order (they couldn't fulfill everything).
                    Context:
                    - Category: {category}
                    - Allocated items to them:
                    {items_str}
                    - Total Amount for their part: ${comp['quoted_amount']}
                    
                    Ask them to reply YES if they can fulfill this partial order at this pricing.
                    Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}.
                    """
                    body = self._call_groq(prompt)
                    drafts.append({
                        "to": comp["supplier_email"],
                        "supplier_name": comp["supplier_id"],
                        "status": "CONFIRMATION_REQUEST",
                        "subject": f"Please Confirm Partial Order: {category.title()} Procurement",
                        "body": body,
                        "type": "confirmation"
                    })
            else:
                # Actual acceptance after they all said yes
                for comp in winner_quote["component_quotes"]:
                    accepted_emails.add(comp["supplier_email"])
                    items_str = "\n".join([
                        f"- {k}: {v} units"
                        for k, v in comp.get("allocated_items", {}).items()
                    ])
                    prompt = f"""
                    Draft a warm, professional purchase order ACCEPTANCE email to '{comp['supplier_email']}'.
                    Context:
                    - Category: {category}
                    - Allocated items:
                    {items_str}
                    - Amount: ${comp['quoted_amount']}
                    
                    Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}.
                    """
                    body = self._call_groq(prompt)
                    drafts.append({
                        "to": comp["supplier_email"],
                        "supplier_name": comp["supplier_id"],
                        "status": "ACCEPTED",
                        "subject": f"ACCEPTANCE & PO AWARD: {category.title()} Procurement",
                        "body": body,
                        "type": "acceptance"
                    })
        else:
            accepted_emails.add(winner_quote["supplier_email"])
            if not is_combo_confirmation:
                prompt = f"""
                Draft a warm, professional purchase order ACCEPTANCE email to '{winner_quote['supplier_email']}'.
                Context:
                - Category: {category}
                - Quoted Price: ${winner_quote['quoted_amount']}
                - Delivery Date: {winner_quote['delivery_date']}
                - Items: {', '.join(winner_quote.get('quoted_items', []))}
                
                Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}.
                """
                body = self._call_groq(prompt)
                drafts.append({
                    "to": winner_quote["supplier_email"],
                    "supplier_name": winner_quote["supplier_id"],
                    "status": "ACCEPTED",
                    "subject": f"ACCEPTANCE & PO AWARD: {category.title()} Procurement",
                    "body": body,
                    "type": "acceptance"
                })

        # Rejection Drafts
        if not is_combo_confirmation:
            for q in quotes:
                if q.get("is_combination"):
                    continue
                if q["supplier_email"] not in accepted_emails:
                    prompt = f"""
                    Draft a polite, highly personalized REJECTION email to vendor '{q['supplier_email']}'.
                    Context:
                    - Category: {category}
                    - Quoted Price: ${q['quoted_amount']}
                    - Delivery Date: {q['delivery_date']}
                    
                    Explicitly mention their quoted price of ${q['quoted_amount']} so they know it is personalized.
                    Sign off: {sender_info.get('name')}, {sender_info.get('title')} at {sender_info.get('company')}.
                    """
                    body = self._call_groq(prompt)
                    drafts.append({
                        "to": q["supplier_email"],
                        "supplier_name": q["supplier_id"],
                        "status": "REJECTED",
                        "subject": f"Update regarding your quote for {category.title()}",
                        "body": body,
                        "type": "rejection"
                    })

        return drafts

    def send_single_email(self, to_email: str, subject: str, body: str):
        msg = MIMEMultipart()
        msg["From"] = self.email_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.email_user, self.email_pass)
            server.send_message(msg)
            
    def check_confirmation_reply(self, email_body: str) -> bool:
        prompt = f"""
        Analyze this email reply from a supplier to determine if they are CONFIRMING our partial order request.
        Reply YES (true) if they agree to the terms or say yes. Reply NO (false) if they reject or demand changes.
        
        Email Body:
        {email_body}
        """
        raw = self._call_groq(prompt, response_schema=ConfirmationExtraction)
        try:
            return json.loads(raw).get("confirmed", False)
        except:
            return False

# ---------------------------------------------------------------------
# INITIALIZATION & STATE
# ---------------------------------------------------------------------
groq_key = os.getenv("GROQ_API_KEY", "")
email_user = os.getenv("EMAIL_USER", "")
email_pass = os.getenv("EMAIL_PASS", "")
smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
smtp_port = int(os.getenv("SMTP_PORT", 587))
imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
imap_port = int(os.getenv("IMAP_PORT", 993))

if "waiting_for_combo_confirmation" not in st.session_state:
    st.session_state["waiting_for_combo_confirmation"] = False
if "combo_suppliers_pending" not in st.session_state:
    st.session_state["combo_suppliers_pending"] = []
if "combo_winner_quote" not in st.session_state:
    st.session_state["combo_winner_quote"] = None
if "all_quotes_cache" not in st.session_state:
    st.session_state["all_quotes_cache"] = []
if "ranking_result_cache" not in st.session_state:
    st.session_state["ranking_result_cache"] = {}

# ---------------------------------------------------------------------
# MAIN APPS DASHBOARD
# ---------------------------------------------------------------------
tab1, tab2 = st.tabs(["Upload & Config", "Mail Fetch & Evaluation"])

with tab1:
    st.subheader("Sender Info")
    col_sender1, col_sender2, col_sender3 = st.columns(3)
    with col_sender1:
        sender_name = st.text_input("Name", value="Mukilan Muthukumar")
    with col_sender2:
        sender_title = st.text_input("Title", value="Procurement Manager")
    with col_sender3:
        sender_company = st.text_input("Company", value="Apex Solutions")

    sender_details = {
        "name": sender_name,
        "title": sender_title,
        "company": sender_company
    }
    
    st.divider()

    col_req, col_sup = st.columns(2)
    with col_req:
        st.subheader("Upload Demand")
        req_file = st.file_uploader("Upload Requested Items CSV", type=["csv"])
    with col_sup:
        st.subheader("Upload Supplier Detail")
        rep_file = st.file_uploader("Upload Supplier Detail CSV", type=["csv"])

    category_name = st.text_input("Procurement Category Name", value="Hardware Equipment")

    st.divider()
    if st.button("Start Process", type="primary", use_container_width=True):
        if req_file and rep_file:
            st.session_state["process_started"] = True
            st.success("Configuration saved! Please switch to the 'Mail Fetch & Evaluation' tab.")
        else:
            st.error("Please upload both CSV files first.")

with tab2:
    if st.session_state.get("process_started") and req_file and rep_file:
        try:
            req_df = pd.read_csv(req_file)
            sup_df = pd.read_csv(rep_file)

            st.subheader("Matched Products & Suppliers by Category")
            
            # Simple visualization of matches
            if 'category' in req_df.columns and 'category' in sup_df.columns:
                merged = pd.merge(req_df, sup_df, on='category', how='inner')
                if not merged.empty:
                    # After merge, 'name' column exists in both CSVs, so pandas creates 'name_x' and 'name_y'
                    display_df = merged[['name_x', 'name_y', 'category', 'email']].rename(
                        columns={'name_x': 'Requested Item', 'name_y': 'Supplier Name'}
                    )
                    st.dataframe(display_df, use_container_width=True)
                else:
                    st.warning("No matches found based on category.")
            else:
                st.error("Missing 'category' column in one of the CSV files.")
            
            st.divider()
            
            if not groq_key or not email_user or not email_pass:
                st.error("Please configure your .env file with GROQ and Email credentials.")
            else:
                service = EvaluatorService(groq_key, email_user, email_pass, smtp_host, smtp_port, imap_host, imap_port)
                
                # Check for confirmations mode
                if st.session_state["waiting_for_combo_confirmation"]:
                    st.warning("⏳ Waiting for combo suppliers to confirm partial order...")
                    st.write(f"Pending confirmations from: {', '.join(st.session_state['combo_suppliers_pending'])}")
                    
                    if st.button("Check for Combo Confirmations", type="primary"):
                        with st.spinner("Checking inbox for replies..."):
                            fetched_emails = service.fetch_emails(st.session_state["combo_suppliers_pending"], limit=10)
                            
                            confirmed_by = []
                            for mail in fetched_emails:
                                is_confirmed = service.check_confirmation_reply(mail["body"])
                                if is_confirmed and mail["from"] in st.session_state["combo_suppliers_pending"]:
                                    confirmed_by.append(mail["from"])
                            
                            for c_email in confirmed_by:
                                if c_email in st.session_state["combo_suppliers_pending"]:
                                    st.session_state["combo_suppliers_pending"].remove(c_email)
                            
                            if not st.session_state["combo_suppliers_pending"]:
                                st.success("All combo suppliers have confirmed!")
                                st.session_state["waiting_for_combo_confirmation"] = False
                                
                                # Generate final POs and Rejections
                                with st.spinner("Generating final POs..."):
                                    email_drafts = service.generate_draft_emails(
                                        category_name, 
                                        st.session_state["ranking_result_cache"], 
                                        st.session_state["all_quotes_cache"], 
                                        sender_details,
                                        st.session_state["combo_winner_quote"]["supplier_id"],
                                        is_combo_confirmation=False
                                    )
                                    st.session_state["email_drafts"] = email_drafts
                            else:
                                st.info("Still waiting for remaining suppliers to reply...")
                                
                else:
                    if st.button("Fetch Quotes (Latest 10 Mails) & Evaluate", type="primary"):
                        supplier_emails = sup_df['email'].dropna().unique().tolist()
                        
                        with st.spinner("Fetching latest emails from suppliers..."):
                            fetched_emails = service.fetch_emails(supplier_emails, limit=10)
                        
                        if not fetched_emails:
                            st.warning("No recent emails found from the listed suppliers.")
                        else:
                            st.success(f"Fetched {len(fetched_emails)} emails. Extracting quotes...")
                            
                            requested_items = req_df.to_dict(orient="records")
                            supplier_replies = []
                            for femail in fetched_emails:
                                # Map back to supplier ID
                                s_id = sup_df[sup_df['email'] == femail['from']]['supplier_id'].values[0]
                                supplier_replies.append({
                                    "supplier_id": s_id,
                                    "supplier_email": femail["from"],
                                    "email_body": femail["body"]
                                })
                            
                            parsed_quotes = service.parse_quotes(category_name, requested_items, supplier_replies)
                            st.session_state["all_quotes_cache"] = parsed_quotes
                            
                            with st.expander("🔍 View Parsed Quotes Data"):
                                st.json(parsed_quotes)
                                
                            with st.spinner("Ranking options via Groq..."):
                                ranking = service.rank_quotes(category_name, parsed_quotes)
                                st.session_state["ranking_result_cache"] = ranking
                                
                            # Clear any old drafts if re-fetching
                            if "email_drafts" in st.session_state:
                                del st.session_state["email_drafts"]
                                
                    # Always render the UI if ranking exists in session state
                    if st.session_state.get("ranking_result_cache"):
                        ranking = st.session_state["ranking_result_cache"]
                        parsed_quotes = st.session_state["all_quotes_cache"]
                        
                        st.subheader("🏆 Supplier Ranking Results")
                        rank_df = pd.DataFrame(ranking.get("ranked_suppliers", []))
                        st.dataframe(rank_df, use_container_width=True)
                        
                        st.divider()
                        st.subheader("Select Winner")
                        winner_options = {s["supplier_id"]: f"Rank {s['rank']} - {s['supplier_name']} (${s['total_quoted_amount']})" for s in ranking.get("ranked_suppliers", [])}
                        selected_winner_id = st.radio("Choose the supplier (or combo) to award the PO to:", options=list(winner_options.keys()), format_func=lambda x: winner_options[x])
                        
                        if st.button("Confirm Winner & Generate Drafts", type="primary"):
                            winner_quote = next(q for q in parsed_quotes if q["supplier_id"] == selected_winner_id)
                            
                            if winner_quote.get("is_combination"):
                                st.info("💡 A combination quote was selected. Generating Confirmation Requests.")
                                st.session_state["combo_winner_quote"] = winner_quote
                                st.session_state["combo_suppliers_pending"] = [c["supplier_email"] for c in winner_quote["component_quotes"]]
                                
                                email_drafts = service.generate_draft_emails(
                                    category_name, ranking, parsed_quotes, sender_details, selected_winner_id, is_combo_confirmation=True
                                )
                                st.session_state["email_drafts"] = email_drafts
                            else:
                                email_drafts = service.generate_draft_emails(
                                    category_name, ranking, parsed_quotes, sender_details, selected_winner_id, is_combo_confirmation=False
                                )
                                st.session_state["email_drafts"] = email_drafts

                # Common Email Preview block
                if "email_drafts" in st.session_state:
                    st.divider()
                    st.subheader("📧 Email Drafts Preview")
                    
                    drafts = st.session_state["email_drafts"]
                    for idx, draft in enumerate(drafts):
                        if draft["status"] == "ACCEPTED": badge = "🟢 ACCEPTANCE"
                        elif draft["status"] == "REJECTED": badge = "🔴 REJECTION"
                        else: badge = "🟡 CONFIRMATION REQUEST"
                        
                        with st.expander(f"{badge}: {draft['supplier_name']} ({draft['to']})"):
                            st.text_input("Subject", value=draft["subject"], key=f"subj_{idx}")
                            st.text_area("Body", value=draft["body"], height=200, key=f"body_{idx}")
                            
                    if st.button("📤 Dispatch All Emails via SMTP"):
                        success_count = 0
                        for idx, draft in enumerate(drafts):
                            try:
                                subj = st.session_state.get(f"subj_{idx}", draft["subject"])
                                body = st.session_state.get(f"body_{idx}", draft["body"])
                                service.send_single_email(draft["to"], subj, body)
                                success_count += 1
                            except Exception as ex:
                                st.error(f"Failed to send to {draft['to']}: {ex}")
                                
                        if success_count > 0:
                            st.success(f"Successfully sent {success_count} personalized emails via SMTP!")
                            if st.session_state.get("combo_winner_quote") and not st.session_state["waiting_for_combo_confirmation"]:
                                # If we sent confirmation requests
                                if "CONFIRMATION_REQUEST" in [d["status"] for d in drafts]:
                                    st.session_state["waiting_for_combo_confirmation"] = True
                                    st.session_state["email_drafts"] = []
                                    st.rerun()

        except Exception as e:
            st.error(f"Error executing pipeline: {e}")
    else:
        st.info("Upload both CSV files in the Upload & Config tab to proceed.")
