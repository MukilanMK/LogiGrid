# ⚡ Quote Evaluation & Awarding Agent

An intelligent, autonomous AI agent built with **Streamlit** and **Groq (Llama 3)** that modernizes and streamlines the procurement and vendor management process. 

This agent acts as your personal automated procurement assistant. It automatically fetches supplier quotes from your email inbox, parses unstructured email text into structured data, intelligently evaluates and ranks proposals (even building "combo" quotes for partial fulfillments), and drafts highly personalized acceptance and rejection emails.

---

## 🚀 Key Features

- **Automated IMAP Email Fetching**: Securely connects to your inbox via IMAP and filters the latest emails directly from your verified suppliers.
- **AI-Powered Quote Parsing**: Uses the Groq LLM (Llama 3) to read raw email bodies and extract structured JSON data, including: Total Cost, Delivery Dates, Itemized Costs, and Quantities.
- **Smart Combination Quotes (Combo Quotes)**: If suppliers can only partially fulfill a demand, the agent intelligently pieces together a "Combo Quote" from multiple suppliers to fulfill 100% of the requested items at the lowest possible cost.
- **Intelligent Proposal Ranking**: Evaluates and ranks proposals. It explicitly compares single full-fulfillment quotes against combination quotes to ensure you get the absolute best price and delivery timeline.
- **Interactive Winner Selection**: Provides a clean, intuitive Streamlit UI for you to review the AI's rankings and manually select the winning supplier (or combo of suppliers).
- **Automated Email Drafting & Dispatch via SMTP**: 
  - Drafts highly personalized Acceptance (PO) and Rejection emails.
  - For Combo Quotes, it drafts individualized **Confirmation Requests** for partial orders.
  - Dispatches the emails directly to suppliers via SMTP.
- **Intent Polling & Confirmation Engine**: For combo quotes, the agent can poll your inbox for supplier replies and use the LLM to determine if the supplier said "YES" or "NO" to the partial order before finalizing the PO.

---

## 📋 Prerequisites

1. **Python 3.8+**
2. A **[Groq API Key](https://console.groq.com/keys)** for lightning-fast Llama 3 inference.
3. An email account with **IMAP/SMTP** enabled (e.g., Gmail with an App Password).

---

## 🛠️ Installation & Setup

1. **Clone the repository** and navigate to the project directory:
   ```bash
   git clone <repository_url>
   cd RANK
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   - Rename `.env.example` to `.env` (or create a new `.env` file).
   - Add your credentials:
     ```env
     GROQ_API_KEY=your_groq_api_key
     EMAIL_USER=your_email@gmail.com
     EMAIL_PASS=your_app_password
     SMTP_HOST=smtp.gmail.com
     SMTP_PORT=587
     IMAP_HOST=imap.gmail.com
     IMAP_PORT=993
     ```

---

## 🔄 Application Flow In Detail

The application is divided into a streamlined pipeline across two main tabs in the Streamlit UI.

### Phase 1: Upload & Configuration (Tab 1)
1. **Launch the Interface**: Start the application by running `streamlit run app.py`.
2. **Sender Information**: In the first tab, provide the sender details (Name, Title, Company). This information is dynamically injected into the email signatures.
3. **Category Context**: Define the **Procurement Category Name** (e.g., *"Hardware Equipment"*, *"Office Supplies"*). This grounds the AI, giving it context to accurately parse emails and generate appropriate subject lines.
4. **Data Ingestion**: Upload two crucial CSV files:
   - **Demand CSV**: Defines what you need (`name`, `category`, `quantity`).
   - **Supplier Detail CSV**: Defines your vendors (`supplier_id`, `name`, `category`, `email`).
5. **Data Matching**: The app cross-references the categories in both CSVs to identify which suppliers can provide the requested items, displaying a visual mapping table. Click **Start Process** to initialize the evaluation pipeline.

### Phase 2: Fetching & Parsing (Tab 2)
1. **Initiate Fetch**: Switch to the *Mail Fetch & Evaluation* tab and click **Fetch Quotes (Latest 10 Mails) & Evaluate**.
2. **IMAP Retrieval**: The system securely logs into your IMAP server and pulls the most recent emails originating strictly from the mapped suppliers' email addresses.
3. **LLM Extraction**: The raw text of each fetched email is passed to the Groq LLM. The AI meticulously extracts a structured JSON payload containing the quoted amount, quoted items, unit costs, and delivery dates.

### Phase 3: Combination Logic & Intelligent Ranking (Tab 2)
1. **Fulfillment Analysis**: The system maps the extracted quoted quantities against your original requested demand to determine if a quote is a *Full Fulfillment* or *Partial Fulfillment*.
2. **Combo Generation**: If multiple suppliers offer partial fulfillments, the algorithm calculates the best way to combine them into a single "Combo Quote" that perfectly satisfies the original demand.
3. **LLM Ranking**: All viable proposals (full individual quotes + combo quotes) are sent to the LLM with a strict evaluation prompt. The AI ranks them based on total cost, delivery speed, and fulfillment completeness, placing the best option at Rank 1.

### Phase 4: Manual Selection & Email Drafting
1. **Review Rankings**: The AI's ranking results are presented in an easy-to-read table.
2. **Human-in-the-Loop Selection**: Using a radio button selector, you review the options and formally select the winning supplier or combination.
3. **Draft Generation**: Upon confirmation, the LLM drafts context-aware emails:
   - **Single Supplier Winner**: Generates an enthusiastic PO Acceptance email for the winner, and polite, highly personalized Rejection emails for the remaining bidders (explicitly mentioning their quoted price so they know it's not an automated template).
   - **Combo Winner**: Generates an individual *Confirmation Request* for each supplier in the combo. Because they are receiving a partial order, the email asks them to confirm if they can still honor the pricing for the reduced quantity.

### Phase 5: Dispatch & Intent Polling
1. **Review & Edit**: You can preview and manually edit any of the generated email subjects and bodies directly in the UI.
2. **SMTP Dispatch**: Click **Dispatch All Emails via SMTP** to send the emails directly to the vendors.
3. **Combo Polling Workflow**: 
   - If a Combo Quote was selected, the system enters a "Waiting State".
   - You can periodically click **Check for Combo Confirmations**.
   - The app fetches new inbox replies and uses the LLM to classify the supplier's intent (Did they reply "YES/Agree" or "NO/Reject"?).
   - Once all combo suppliers confirm, the system automatically generates and dispatches the final Acceptance POs!

---

## 📝 Required CSV Schemas

### 1. demand.csv
This file lists the exact items and quantities you are looking to procure.
```csv
name,category,quantity
Dell XPS 15,Hardware Equipment,5
MacBook Pro 16,Hardware Equipment,3
```

### 2. suppliers.csv
This file lists your verified vendors and their contact information.
```csv
supplier_id,name,category,email
SUP001,Tech Haven,Hardware Equipment,sales@techhaven.com
SUP002,Global IT Supplies,Hardware Equipment,quotes@globalitsupplies.com
```
