# 🌐 LogiGrid: Autonomous Multi-Agent Supply Chain & Auditing Ecosystem

> **An enterprise-grade, closed-loop multi-agent infrastructure** designed to automate the complete commercial lifecycle—from predictive demand forecasting and automated supplier outreach to financial auditing, margin defense, and executive business intelligence.

---

## 📌 Problem Statement

Traditional supply chain management for small and medium retail, kirana networks, and industrial traders is plagued by operational inefficiencies:

* **📉 Static Reordering Blindness**
  Reordering inventory based on flat historical averages ignores qualitative market events (festivals, weather anomalies, local demand surges), leading to stockouts or deadstock.

* **📧 Manual Procurement Drag**
  Sourcing quotes from multiple vendors requires endless email threads, manual price comparisons, and fragmented vendor tracking.

* **💸 Unnoticed Cost Price Hikes**
  Suppliers alter cost prices on e-invoices without notice, silently eroding profit margins.

* **⚠️ Selling at a Loss**
  Billing systems fail to update retail selling prices when inbound supplier costs increase, resulting in items being sold below cost.

* **🔗 Siloed Data & Zero Feedback Loops**
  Operational data remains trapped across emails, inventory sheets, and invoices without a unified intelligence layer.

---

## 🤖 The 6-Agent Architecture

LogiGrid breaks down complex supply chain operations into six specialized, cooperative autonomous agents:

### 1. 📊 Demand Forecast Agent

* **Core Role**: Predictive Inventory Planning
* **Function**: Combines historical sales data with qualitative event insights (via LLMs) to forecast demand spikes, calculate inventory countdowns, and generate precise reorder quantities.

---

### 2. 📬 Supplier Outreach Agent

* **Core Role**: Sourcing & Vendor Communication
* **Function**: Uses reorder requirements to query vendor databases, generate context-aware RFQ (Request for Quote) emails, and automate outreach.

---

### 3. 🧠 Quote Ranking Agent

* **Core Role**: Procurement Decision Engine
* **Function**: Parses supplier replies, extracts pricing and lead times, applies multi-variable logic (price, delivery speed, trust score), ranks vendors, and issues Purchase Orders.

---

### 4. 💰 Financial Agent

* **Core Role**: Invoice Auditing & Margin Defense
* **Function**:

  * Extracts structured data from e-invoice PDFs
  * Performs line-item validation
  * Checks GST & ITC compliance
  * Triggers **Critical Margin Alerts** when selling prices fall below cost

---

### 5. ⭐ Quality Feedback Agent

* **Core Role**: Vendor Trust Intelligence
* **Function**: Analyzes customer feedback, returns, and seller notes to dynamically update **Supplier Trust Scores**, influencing future procurement.

---

### 6. 📈 Executive BI Agent

* **Core Role**: Strategic Business Intelligence
* **Function**: Aggregates insights from all agents and enables natural language queries to evaluate business performance, profitability, and operational health.

---

## 📐 System Architecture Flow

```text
                           LOGIGRID ECOSYSTEM
                                   │
 ┌─────────────────────────────────┼─────────────────────────────────┐
 │                                 │                                 │
 │        Phase 1: Planning        │     Phase 2: Procurement        │   Phase 3: Fulfillment
 │                                 │                                 │
 ▼                                 ▼                                 ▼

┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ Demand Forecast │ ─────► │ Supplier        │ ─────► │ Financial Agent │
│ Agent           │        │ Outreach Agent  │        │ (Audit / PO)    │
└─────────────────┘        └────────┬────────┘        └────────┬────────┘
         │                           │                          │
         ▼                           ▼
┌─────────────────┐        ┌─────────────────┐
│ Quote Ranking   │        │ Quality Feedback│
│ Agent           │        │ Agent           │
└─────────────────┘        └────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Executive BI    │
│ Agent           │
└─────────────────┘
```

---

## 🔄 Detailed Operational Flow (Closed-Loop Cycle)

1. **📊 Demand Prediction**
   The system analyzes inventory levels, sales velocity, and contextual events to generate precise reorder requirements.

2. **📬 Autonomous Sourcing**
   Vendors are automatically identified, and RFQs are generated and sent via email.

3. **🧠 Smart Evaluation & Ordering**
   Incoming quotes are parsed, ranked, and the best supplier is selected for automated Purchase Order issuance.

4. **💰 Financial Safeguard**
   Invoices are validated, pricing discrepancies are flagged, and compliance checks are performed.

5. **⭐ Quality Feedback Loop**
   Post-sale insights update supplier trust scores, improving future procurement decisions.

6. **📈 Executive Oversight**
   A conversational BI layer provides real-time insights into operational and financial health.

---

## 🛠️ Tech Stack & Dependencies

### 🚀 Core Technologies

* **Orchestration & Framework**: Python, LangChain, LangChain-Groq
* **LLM Engine**: Groq `llama-3.3-70b-versatile`
* **Database**: MongoDB Atlas (`pymongo`)

### 📊 Data Processing

* **Validation & Parsing**: Pydantic v2
* **Document Processing**: `pypdf`
* **Data Analysis**: `pandas`

### 🖥️ Frontend

* **UI Framework**: Streamlit

---

## 🎯 Key Highlights

* ✅ Fully autonomous supply chain lifecycle
* ✅ Closed-loop learning with feedback integration
* ✅ Real-time margin protection
* ✅ AI-driven procurement optimization
* ✅ Conversational business intelligence

---

## 📌 Future Enhancements

* Real-time IoT integration for warehouse tracking
* Predictive logistics & delivery optimization
* Advanced anomaly detection in procurement
* Multi-language vendor communication support

---

## 🤝 Contributing

Contributions, ideas, and improvements are welcome!
Feel free to fork the repository and submit a pull request.

---

## 📬 Contact

For collaboration or queries, reach out via GitHub or email.

---

> 🚀 *LogiGrid transforms supply chains into intelligent, self-optimizing ecosystems.*
# LogiGrid
