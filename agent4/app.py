import os
import json
import pandas as pd
import streamlit as st
from pypdf import PdfReader
from dotenv import load_dotenv
from pymongo import MongoClient
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "shop_audit_db")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ------------------------------------------------------------------------------
# 1. MongoDB Database Connection
# ------------------------------------------------------------------------------
@st.cache_resource
def get_mongo_client():
    if not MONGODB_URI:
        st.error("Missing MONGODB_URI in environment variables.")
        return None
    return MongoClient(MONGODB_URI)

mongo_client = get_mongo_client()
db = mongo_client[DB_NAME] if mongo_client else None

# Collections
col_inventory = db["inventory"] if db is not None else None
col_billing = db["billing"] if db is not None else None
col_auditing = db["auditing"] if db is not None else None


# ------------------------------------------------------------------------------
# 2. Pydantic Models for Structured Extraction
# ------------------------------------------------------------------------------
class InvoiceItem(BaseModel):
    product_name: str = Field(description="Name of the product/item in the invoice")
    count: int = Field(description="Quantity/Count of items supplied")
    cost_price: float = Field(description="Per-unit cost price of the item")

class SupplierInvoice(BaseModel):
    invoice_number: str = Field(description="Unique invoice number")
    supplier_name: str = Field(description="Name of the supplying vendor")
    supplier_email: str = Field(description="Email address of supplier (Unique Key)")
    items: list[InvoiceItem] = Field(description="List of items in the invoice")
    total_cost: float = Field(description="Total invoice amount")


# ------------------------------------------------------------------------------
# 3. PDF Extraction Engine
# ------------------------------------------------------------------------------
def extract_text_from_pdf(pdf_file) -> str:
    """Extracts raw text from an uploaded PDF file."""
    reader = PdfReader(pdf_file)
    extracted_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            extracted_text += text + "\n"
    return extracted_text


def parse_invoice_with_llm(invoice_text: str) -> SupplierInvoice:
    """Parses raw text into structured SupplierInvoice model using Groq LLM."""
    llm = ChatGroq(
        model_name="llama-3.3-70b-versatile",
        groq_api_key=GROQ_API_KEY,
        temperature=0
    )
    structured_llm = llm.with_structured_output(SupplierInvoice)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert Indian billing and GST audit parser. Extract all relevant supplier e-invoice details accurately."),
        ("human", "Extract invoice information from the following e-invoice content:\n\n{content}")
    ])
    
    chain = prompt | structured_llm
    return chain.invoke({"content": invoice_text})


# ------------------------------------------------------------------------------
# 4. Audit & Validation Engine
# ------------------------------------------------------------------------------
def run_audit_validation(parsed_invoice: SupplierInvoice):
    """
    Validates extracted supplier e-invoice data against Inventory DB and Billing DB.
    Matches supplier by supplier_email (unique key).
    """
    supplier_email = parsed_invoice.supplier_email.strip().lower()
    invoice_num = parsed_invoice.invoice_number
    
    discrepancies = []
    passed_checks = []
    
    # 1. Fetch related inventory entries by supplier_email
    inventory_items = list(col_inventory.find({"supplier_email": {"$regex": f"^{supplier_email}$", "$options": "i"}})) if col_inventory is not None else []
    
    if not inventory_items:
        discrepancies.append(f"Supplier email '{supplier_email}' not found in active Inventory records.")
    
    calc_total_cost = 0.0

    for item in parsed_invoice.items:
        p_name = item.product_name
        inv_count = item.count
        inv_cost = item.cost_price
        calc_total_cost += (inv_count * inv_cost)

        # Match with Inventory DB
        matched_inv = next((inv for inv in inventory_items if inv.get("product_name", "").strip().lower() == p_name.strip().lower()), None)
        
        if matched_inv:
            # Check Cost Price Mismatch
            db_cost = float(matched_inv.get("cost_price", 0))
            if db_cost != inv_cost:
                discrepancies.append(
                    f"Cost Price Mismatch for '{p_name}': Invoice CP = ₹{inv_cost}, DB CP = ₹{db_cost}"
                )
            else:
                passed_checks.append(f"Cost Price verified for '{p_name}' (₹{inv_cost}).")

            # Check Quantity Mismatch
            db_count = int(matched_inv.get("count", 0))
            if inv_count > db_count:
                discrepancies.append(
                    f"Quantity Discrepancy for '{p_name}': Invoice Count ({inv_count}) > DB Current Stock ({db_count})"
                )
        else:
            discrepancies.append(f"Product '{p_name}' in invoice not registered under supplier in Inventory DB.")

        # Match with Billing DB to check Margin Safety (Selling Price vs Invoice Cost Price)
        billing_records = list(col_billing.find({"sold_product": {"$regex": f"^{p_name}$", "$options": "i"}})) if col_billing is not None else []
        for bill in billing_records:
            selling_price = float(bill.get("selling_price", 0))
            if selling_price < inv_cost:
                discrepancies.append(
                    f"CRITICAL MARGIN ALERT: Selling Price (₹{selling_price}) of '{p_name}' is LESS than Invoice Cost Price (₹{inv_cost}). Loss risk detected!"
                )

    # Total Invoice Cost Validation
    if abs(calc_total_cost - parsed_invoice.total_cost) > 0.01:
        discrepancies.append(
            f"Math Inconsistency: Item sum (₹{calc_total_cost}) does not match Invoice Stated Total (₹{parsed_invoice.total_cost})."
        )

    # Determine Audit Status
    audit_status = "PASSED" if len(discrepancies) == 0 else "FLAGGED_WITH_ISSUES"

    audit_entry = {
        "invoice_number": invoice_num,
        "supplier_name": parsed_invoice.supplier_name,
        "supplier_email": supplier_email,
        "stated_total_cost": parsed_invoice.total_cost,
        "calculated_total_cost": calc_total_cost,
        "items": [item.dict() for item in parsed_invoice.items],
        "audit_status": audit_status,
        "discrepancies": discrepancies,
        "passed_checks": passed_checks,
        "audited_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Save to MongoDB Auditing Collection
    if col_auditing is not None:
        col_auditing.update_one(
            {"invoice_number": invoice_num},
            {"$set": audit_entry},
            upsert=True
        )

    return audit_entry


# ------------------------------------------------------------------------------
# 5. Streamlit App Layout & Navigation
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Indian Shop Mini-Auditor", layout="wide", page_icon="🧾")

st.title("🧾 Indian Shop Audit Helper Agent")
st.markdown("Automated E-Invoice Audit & Legal Compliance Assistant for Indian Small Businesses.")

tab1, tab2, tab3 = st.tabs([
    "📥 Data Setup (CSV Feeds)", 
    "⚙️ Invoice Audit Cycle", 
    "🤖 Audit & Indian Law Chatbot"
])

# ------------------------------------------------------------------------------
# TAB 1: CSV Uploads (Populate Inventory & Billing DBs)
# ------------------------------------------------------------------------------
with tab1:
    st.subheader("Populate Prototype Collections")
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("### Inventory CSV Upload")
        st.caption("Expected headers: `product_name`, `count`, `cost_price`, `supplier_email`")
        inv_file = st.file_uploader("Upload Inventory CSV", type=["csv"], key="inv_upload")
        if inv_file and st.button("Sync Inventory DB"):
            df_inv = pd.read_csv(inv_file)
            if col_inventory is not None:
                col_inventory.delete_many({}) # Clear existing
                col_inventory.insert_many(df_inv.to_dict("records"))
                st.success(f"Successfully synced {len(df_inv)} items to Inventory Collection!")

    with col_b:
        st.markdown("### Billing CSV Upload")
        st.caption("Expected headers: `sold_product`, `count`, `selling_price`")
        bill_file = st.file_uploader("Upload Billing CSV", type=["csv"], key="bill_upload")
        if bill_file and st.button("Sync Billing DB"):
            df_bill = pd.read_csv(bill_file)
            if col_billing is not None:
                col_billing.delete_many({}) # Clear existing
                col_billing.insert_many(df_bill.to_dict("records"))
                st.success(f"Successfully synced {len(df_bill)} records to Billing Collection!")

    st.markdown("---")
    st.markdown("### Current Database Status")
    col_c1, col_c2, col_c3 = st.columns(3)
    col_c1.metric("Inventory Records", col_inventory.count_documents({}) if col_inventory is not None else 0)
    col_c2.metric("Billing Records", col_billing.count_documents({}) if col_billing is not None else 0)
    col_c3.metric("Audited Invoices", col_auditing.count_documents({}) if col_auditing is not None else 0)


# ------------------------------------------------------------------------------
# TAB 2: Batch Invoice Processing (Updated for Multi-PDF Uploads)
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("Scan & Run Batch Supplier E-Invoice Audit Cycle")
    
    uploaded_invoices = st.file_uploader(
        "Upload Supplier E-Invoices (Multiple PDFs allowed)", 
        type=["pdf"], 
        accept_multiple_files=True
    )
    
    if uploaded_invoices:
        st.info(f"📁 {len(uploaded_invoices)} invoice file(s) selected for processing.")
        
        if st.button("🚀 Process & Audit All Invoices"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            processed_results = []
            
            for idx, pdf_file in enumerate(uploaded_invoices):
                status_text.text(f"⏳ Processing [{idx + 1}/{len(uploaded_invoices)}]: {pdf_file.name}...")
                
                # 1. Extract raw text
                raw_text = extract_text_from_pdf(pdf_file)
                
                # 2. Extract structured fields via Groq LLM
                parsed_inv = parse_invoice_with_llm(raw_text)
                
                # 3. Validate against DB & log audit entry
                audit_result = run_audit_validation(parsed_inv)
                
                processed_results.append({
                    "filename": pdf_file.name,
                    "parsed": parsed_inv,
                    "audit": audit_result
                })
                
                # Update progress
                progress_bar.progress((idx + 1) / len(uploaded_invoices))
            
            status_text.success("🎉 Batch processing complete! All invoices audited and saved to DB.")

            # Summary Results Accordion/Expanders
            st.markdown("### 📊 Batch Processing Results")
            for item in processed_results:
                audit_res = item["audit"]
                parsed_res = item["parsed"]
                status = audit_res["audit_status"]
                
                icon = "✅" if status == "PASSED" else "⚠️"
                label = f"{icon} File: {item['filename']} | Invoice #{audit_res['invoice_number']} ({parsed_res.supplier_name}) - Status: {status}"
                
                with st.expander(label, expanded=(status != "PASSED")):
                    col_res1, col_res2 = st.columns(2)
                    
                    with col_res1:
                        st.markdown("#### ❌ Identified Discrepancies")
                        if audit_res["discrepancies"]:
                            for disc in audit_res["discrepancies"]:
                                st.error(f"• {disc}")
                        else:
                            st.write("None")

                    with col_res2:
                        st.markdown("#### ✅ Passed Checks")
                        if audit_res["passed_checks"]:
                            for check in audit_res["passed_checks"]:
                                st.success(f"• {check}")
                        else:
                            st.write("None")
                    
                    st.json(parsed_res.dict())

    st.markdown("---")
    st.subheader("📋 Complete Auditing Database Log")
    if col_auditing is not None:
        audit_logs = list(col_auditing.find({}, {"_id": 0}))
        if audit_logs:
            st.dataframe(pd.DataFrame(audit_logs), use_container_width=True)
        else:
            st.info("No audit logs present yet.")


# ------------------------------------------------------------------------------
# TAB 3: Chatbot (Auditing & Indian Laws)
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("💬 AI Audit & Indian Business Legal Assistant")
    st.caption("Ask questions about your audit logs, GST compliance, Consumer Protection Act 2019, or Legal Metrology rules.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_query = st.chat_input("e.g., Which supplier invoices were flagged? Or What are the MRP labeling rules in India?")

    if user_query:
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        # Context Fetching from MongoDB Auditing DB
        audit_data_context = list(col_auditing.find({}, {"_id": 0})) if col_auditing is not None else []

        bot_system_prompt = f"""
        You are an expert AI Audit Assistant and Legal Advisor specialized in Indian Business Laws.
        Your expertise includes:
        1. Querying and summarizing Audit Logs from the shop's database.
        2. Indian GST Acts (CGST/SGST/IGST, ITC claim rules, e-Invoicing thresholds).
        3. Consumer Protection Act 2019 (Return policies, unfair trade practices, defect liabilities).
        4. Legal Metrology Act (Mandatory MRP, net quantity, manufacturer address declarations).

        Current Auditing DB Records:
        {json.dumps(audit_data_context, indent=2)}

        Provide clear, concise, and highly relevant factual answers.
        """

        llm_chat = ChatGroq(
            model_name="llama-3.3-70b-versatile",
            groq_api_key=GROQ_API_KEY,
            temperature=0.3
        )

        chat_messages = [("system", bot_system_prompt)]
        for m in st.session_state.messages:
            chat_messages.append((m["role"], m["content"]))

        with st.chat_message("assistant"):
            response = llm_chat.invoke(chat_messages)
            st.markdown(response.content)
            st.session_state.messages.append({"role": "assistant", "content": response.content})