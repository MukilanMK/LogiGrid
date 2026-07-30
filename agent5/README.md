# Agent 3 — Vendor Quality Scoring & Complaint Agent

> An AI-powered Streamlit application that collects seller and customer feedback, classifies it using a Groq LLM (LLaMA 3.1), computes deterministic trust-score penalties, and surfaces real-time compliance dashboards for all suppliers.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Technology Stack](#technology-stack)
4. [Project Structure](#project-structure)
5. [Architecture & Data Model](#architecture--data-model)
6. [Detailed Flow Walkthrough](#detailed-flow-walkthrough)
   - [Seller Feedback Flow](#1-seller-feedback-flow)
   - [Customer Feedback Flow](#2-customer-feedback-flow)
   - [Supplier Dashboard Flow](#3-supplier-dashboard-flow)
   - [Reprocess / Recovery Flow](#4-reprocess--recovery-flow)
7. [Scoring Engine Deep-Dive](#scoring-engine-deep-dive)
   - [LLM Classification](#llm-classification)
   - [Penalty Table](#penalty-table)
   - [Source Weight Multipliers](#source-weight-multipliers)
   - [Trust Score Formula](#trust-score-formula)
   - [Compliance Flag](#compliance-flag)
8. [Database Layer](#database-layer)
9. [Seed Data](#seed-data)
10. [Setup & Installation](#setup--installation)
11. [Environment Variables](#environment-variables)
12. [Running the App](#running-the-app)
13. [Sample Suppliers & Invoices](#sample-suppliers--invoices)

---

## Overview

Agent 3 is a **vendor quality management system** designed for B2B supply-chain teams. It captures two types of feedback:

- **Seller feedback** — internal quality inspectors or procurement teams flagging issues directly about a supplier.
- **Customer feedback** — end-customers reporting problems against a sales invoice; the system automatically resolves which supplier is responsible via the invoice → product → purchase-order chain.

Every submitted feedback is sent to a **Groq-hosted LLaMA 3.1 LLM** for zero-shot classification into a category (e.g., manufacturing defect, logistics damage) and severity level (HIGH / MEDIUM / LOW / NONE). A deterministic scoring formula then converts that classification into a numeric **trust score penalty or bonus** that is applied to the responsible supplier in real-time.

A live **Supplier Dashboard** visualises all trust scores, compliance flags, score history trends, and full feedback histories — enabling procurement managers to make data-driven vendor decisions.

---

## Key Features

| Feature | Description |
|---|---|
| 🤖 AI Classification | Groq LLaMA 3.1 classifies every feedback into category + severity in < 1 s |
| 📊 Real-time Scoring | Deterministic penalty/bonus applied atomically after each submission |
| 🔗 Auto Supplier Resolution | Customer invoices traced back to supplier via PO chain automatically |
| 🚨 Compliance Flagging | Suppliers with trust score < 30 are automatically flagged |
| 📈 Score History Chart | Time-series trust score trend for each supplier |
| 🔧 Reprocessor | One-click repair of any feedback rows misclassified during API outages |
| 🎨 Dark-Mode UI | Fully styled Streamlit app with dark theme, badge system, and metric cards |

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Frontend / UI** | Streamlit ≥ 1.35 (dark theme, custom CSS) |
| **AI / LLM** | Groq API — LLaMA 3.1 8B Instant (`llama-3.1-8b-instant`) |
| **Database** | MongoDB (local or Atlas) via PyMongo ≥ 4.7 |
| **Data Processing** | Pandas ≥ 2.2 |
| **Config** | Python-dotenv |
| **Language** | Python 3.10+ |

---

## Project Structure

```
agent 3/
├── app.py              # Streamlit entrypoint — UI pages and routing
├── db.py               # MongoDB connection, collection accessors, all query/write functions
├── scoring_engine.py   # Groq LLM classification + deterministic scoring logic
├── seed_data.py        # One-time DB seeder with sample suppliers, products, invoices & POs
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── .env                # Your local secrets (not committed to source control)
```

---

## Architecture & Data Model

### MongoDB Collections

```
agent3_vendor_quality (database)
│
├── suppliers           — Supplier master with trust_score & compliance_flag
├── products            — Product catalogue (product_id, name, category)
├── sales_invoices      — Customer invoices (invoice_id, timestamp, customer_gstin)
├── sales_line_items    — Invoice line items linking invoice_id → product_id
├── purchase_orders     — PO records linking product_id → supplier_id + order_date
└── supplier_feedback   — All feedback submissions with AI classification results
```

### Supplier Document Schema

```json
{
  "supplier_id":    "SUP-001",
  "supplier_name":  "Apex Electronics Ltd.",
  "gstin":          "27AAPCA1234C1Z5",
  "contact_email":  "procurement@apex-elec.com",
  "trust_score":    85.0,
  "compliance_flag": false
}
```

### Supplier Feedback Document Schema

```json
{
  "feedback_id":        "FB-A1B2C3D4",
  "source_type":        "SELLER",
  "supplier_id":        "SUP-001",
  "invoice_id":         "INV-2026-001",
  "product_id":         "PROD-001",
  "raw_feedback":       "Three LED bulbs stopped working within a week.",
  "additional_details": "No voltage issues in our facility.",
  "ai_category":        "MFG_DEFECT",
  "ai_severity":        "MEDIUM",
  "score_delta":        5.0,
  "created_at":         "2026-02-03T00:00:00Z"
}
```

### Supplier Resolution Chain (Customer Feedback)

```
Sales Invoice (INV-2026-001)
        │
        ▼
Sales Line Items  ──→  product_ids: [PROD-001, PROD-002]
        │
        ▼ (for each product_id)
Purchase Orders   ──→  most recent PO with order_date ≤ invoice.timestamp
        │
        ▼
Supplier ID  ──→  SUP-001 (Apex Electronics Ltd.)
```

---

## Detailed Flow Walkthrough

### 1. Seller Feedback Flow

This page allows an internal seller / procurement team member to submit quality feedback about a supplier.

```
User Action                   System Action
────────────────────────────────────────────────────────────────
1. Open "Seller Feedback" page
2. Select supplier from dropdown  ← db.get_all_suppliers()
3. (Optional) Enter Invoice No.   ← db.get_invoice_by_number()
4. (Optional) Enter Product ID    ← db.get_product_by_id()
5. Enter feedback text
6. Click "Submit Feedback"
        │
        ▼
   scoring_engine.process_feedback(feedback_row)
        │
        ├─ Step 1: classify_feedback(raw_text, "SELLER")
        │         → Groq LLaMA 3.1 API call
        │         → Returns {category, severity}
        │
        ├─ Step 2: compute_score_delta(category, severity, "SELLER")
        │         → base_penalty × 1.2 (seller weight)
        │
        ├─ Step 3: update_supplier_score(supplier_id, delta)
        │         → new_score = current_score - delta (clamped 0–100)
        │         → set compliance_flag = (new_score < 30)
        │         → db.update_supplier_score(...)
        │
        └─ Step 4: db.insert_feedback(complete_row)

7. UI shows result card:
   - Updated Trust Score with delta indicator
   - AI Category badge  (e.g., MFG_DEFECT)
   - AI Severity badge  (e.g., MEDIUM)
   - Compliance alert   (if newly flagged)

8. Reference table below form shows live trust scores for all suppliers
```

---

### 2. Customer Feedback Flow

This page lets an end-customer report a problem by providing only their invoice number. The system automatically traces which supplier is responsible.

```
User Action                   System Action
────────────────────────────────────────────────────────────────
1. Open "Customer Feedback" page
2. Enter Invoice Number            ← db.get_invoice_by_number()
   [If not found → error shown]
3. Enter feedback text
4. Click "Submit Feedback"
        │
        ▼
   Supplier Resolution:
   db.resolve_supplier_from_invoice(invoice_id)
        │
        ├─ Fetch invoice timestamp
        ├─ Fetch products on invoice via sales_line_items
        └─ For each product_id:
             find most recent purchase_order
             with order_date ≤ invoice.timestamp
             → return supplier_id
        │
        ├─ [SUCCESS] Supplier auto-resolved
        │   → Show info banner: "Supplier resolved: Apex Electronics Ltd."
        │
        └─ [FAILURE] No PO found
            → Show warning banner
            → Display manual supplier selectbox

        │
        ▼
   scoring_engine.process_feedback(feedback_row)
   (Same 4-step pipeline as Seller Feedback,
    but source_type = "CUSTOMER" → weight = 1.0)
        │
        ▼
7. UI shows result card identical to Seller Feedback
```

---

### 3. Supplier Dashboard Flow

A read-only monitoring view for procurement managers.

```
Page Load
    │
    ├─ db.get_all_suppliers()
    │
    ├─ Summary Cards (one card per supplier)
    │   Shows: supplier name, trust score (colour-coded), compliance badge
    │   - Green  ≥ 70   → healthy
    │   - Amber  40–69  → at-risk
    │   - Red    < 40   → critical
    │
    ├─ Full Summary Table (all suppliers, GSTIN, email, compliance)
    │
    └─ Drill-Down Section
        │
        ├─ Selectbox: choose supplier
        │
        ├─ KPI Strip (4 metric cards)
        │   Trust Score | Compliance Status | GSTIN | Contact Email
        │
        ├─ Trust Score History Chart
        │   db.get_score_history(supplier_id)
        │   → Rewinds from current score using all stored deltas
        │   → Replays forward to build per-event time series
        │   → Rendered as Streamlit line_chart (colour: #6366F1 indigo)
        │
        └─ Feedback History Table
            db.get_feedback_for_supplier(supplier_id)
            Columns: Date | Source | Category | Severity | Score Delta
                     | Invoice | Product | Feedback (truncated to 120 chars)
```

---

### 4. Reprocess / Recovery Flow

Handles the case where the Groq API was unavailable during earlier submissions, causing feedback to be stored with the fallback values `category=OTHER, severity=LOW, score_delta=0.0`.

```
Dashboard → "Fix historical feedback" expander → "Reprocess All Feedback"
    │
    ▼
scoring_engine.reprocess_all_feedback()
    │
    ├─ For each supplier:
    │     rows = db.get_all_feedback_ids_for_supplier(supplier_id)
    │
    │     For each row:
    │       if ai_category == "OTHER"
    │          AND score_delta == 0.0
    │          AND raw_feedback not empty:
    │             → classify_feedback(raw_feedback, source_type)
    │             → compute_score_delta(new_cat, new_sev, source_type)
    │             → db.update_feedback_classification(...)
    │             → reclassified_count += 1
    │
    │     if reclassified_count > 0:
    │       → db.recompute_supplier_score_from_feedback(supplier_id, seed=100.0)
    │         (replay all deltas oldest-first from 100, clamped to 0–100)
    │       → db.update_supplier_score(supplier_id, new_score, compliance_flag)
    │
    └─ Returns summary: total_reclassified, per-supplier new scores
    │
    ▼
UI shows success banner + per-supplier results table
Page auto-reruns to refresh all data
```

---

## Scoring Engine Deep-Dive

### LLM Classification

Every feedback text is sent to Groq's LLaMA 3.1 8B Instant model with a strict system prompt that instructs it to return **only** a JSON object:

```json
{"category": "MFG_DEFECT", "severity": "HIGH"}
```

**Categories:**

| Code | Meaning |
|---|---|
| `MFG_DEFECT` | Product itself is faulty — manufacturing defect or broken on arrival |
| `LOGISTICS_DAMAGE` | Damaged during shipping or handling |
| `USER_ERROR` | Customer or operator misuse; not supplier's fault |
| `POSITIVE` | Praise or positive satisfaction |
| `OTHER` | Does not fit any of the above |

**Severities:**

| Code | Meaning |
|---|---|
| `HIGH` | Safety risk, major operational impact |
| `MEDIUM` | Moderate issue affecting usability or quality |
| `LOW` | Minor cosmetic or inconvenience issue |
| `NONE` | No severity (used with POSITIVE or benign OTHER) |

On any API failure or JSON parse error, the engine falls back to `{category: "OTHER", severity: "LOW"}` with zero score impact. The reprocessor (Flow 4) can later fix these rows.

---

### Penalty Table

After classification, a **deterministic formula** (no AI randomness) computes the score delta:

| Category | HIGH | MEDIUM | LOW | NONE |
|---|---|---|---|---|
| `MFG_DEFECT` | 8.0 | 5.0 | 2.0 | 0.0 |
| `LOGISTICS_DAMAGE` | 4.0 | 2.0 | 1.0 | 0.0 |
| `USER_ERROR` | 0.0 | 0.0 | 0.0 | 0.0 |
| `POSITIVE` | −2.0 | −2.0 | −2.0 | −2.0 |
| `OTHER` | 0.0 | 0.0 | 0.0 | 0.0 |

> Positive values = penalty (score **decreases**). Negative values = bonus (score **increases**).

---

### Source Weight Multipliers

| Source | Weight |
|---|---|
| `SELLER` | ×1.2 (internal team feedback carries more weight) |
| `CUSTOMER` | ×1.0 (baseline weight) |

```
final_delta = base_penalty × source_weight
```

**Example:** A seller reports a HIGH manufacturing defect:
```
delta = 8.0 × 1.2 = 9.6 points penalty
```

---

### Trust Score Formula

```
new_score = clamp(current_score − delta, 0, 100)
```

- Scores are stored with 4 decimal places.
- Score starts at **100** for all new suppliers.
- Positive feedback gives a **bonus** (score rises, up to 100 max).

---

### Compliance Flag

```python
COMPLIANCE_THRESHOLD = 30.0

compliance_flag = (new_score < COMPLIANCE_THRESHOLD)
```

When a supplier's trust score drops below **30**, their `compliance_flag` is set to `True` and a red alert banner is shown after every subsequent feedback submission.

---

## Database Layer

`db.py` provides a clean service layer over PyMongo. Key functions:

| Function | Description |
|---|---|
| `get_db()` | Lazy-cached MongoClient + creates indexes on first call |
| `get_all_suppliers()` | All suppliers sorted by name |
| `get_supplier_by_id(id)` | Single supplier lookup |
| `update_supplier_score(id, score, flag)` | Atomic trust score + compliance update |
| `get_invoice_by_number(id)` | Invoice lookup by invoice_id string |
| `resolve_supplier_from_invoice(inv_id)` | Full PO-chain resolution → supplier_id |
| `insert_feedback(row)` | Insert completed feedback document |
| `get_feedback_for_supplier(id)` | All feedback for a supplier, newest-first |
| `get_score_history(id)` | Builds time-series score chart data from stored deltas |
| `recompute_supplier_score_from_feedback(id)` | Replay all deltas from seed to get canonical score |
| `update_feedback_classification(id, cat, sev, delta)` | Patch AI fields on existing feedback row |
| `ping()` | Connectivity check — used at Streamlit startup |

**Indexes created automatically on first connect:**
- `suppliers.supplier_id` (unique)
- `products.product_id` (unique)
- `sales_invoices.invoice_id` (unique)
- `purchase_orders.po_id` (unique), `(product_id, order_date DESC)`
- `supplier_feedback.feedback_id` (unique), `supplier_id`, `invoice_id`

---

## Seed Data

`seed_data.py` populates the database with realistic sample data for immediate testing.

**5 Suppliers:**

| ID | Name | Initial Score | Status |
|---|---|---|---|
| SUP-001 | Apex Electronics Ltd. | 85.0 | OK |
| SUP-002 | BrightGear Components | 72.0 | OK |
| SUP-003 | CoreTech Supplies Pvt Ltd | 55.0 | OK |
| SUP-004 | Delta Hardware House | 28.0 | **FLAGGED** |
| SUP-005 | EcoPackage Solutions | 95.0 | OK |

**6 Products:** Industrial LED Bulb, HDMI Cable, Circuit Breaker, Steel Bolt, Corrugated Box, Thermal Paste.

**6 Sales Invoices:** INV-2026-001 through INV-2026-006 (Jan–Jun 2026).

**8 Purchase Orders** linking products to suppliers, enabling automatic invoice-to-supplier resolution.

**6 Pre-seeded Feedback Entries** covering all category types (positive, MFG_DEFECT HIGH/MEDIUM, LOGISTICS_DAMAGE, USER_ERROR).

> Re-running `seed_data.py` is **safe** — it uses upsert operations so existing documents are replaced without duplicating data.

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- MongoDB running locally on port 27017 (or a MongoDB Atlas connection string)
- A [Groq API key](https://console.groq.com/keys) (free tier available)

### Steps

```bash
# 1. Clone / navigate to the project directory
cd "agent 3"

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
copy .env.example .env
# Edit .env and fill in GROQ_API_KEY, MONGO_URI, MONGO_DB

# 5. Seed the database with sample data
python seed_data.py

# 6. Launch the Streamlit app
streamlit run app.py
```

The app will open at **http://localhost:8501**.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
# Groq API key — get yours at https://console.groq.com/keys
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Groq model (llama-3.1-8b-instant is the free-tier fast model)
GROQ_MODEL=llama-3.1-8b-instant

# MongoDB connection string (default: local MongoDB on port 27017)
MONGO_URI=mongodb://localhost:27017

# MongoDB database name
MONGO_DB=agent3_vendor_quality
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | ✅ Yes | — | Groq API key for LLM inference |
| `GROQ_MODEL` | No | `llama-3.1-8b-instant` | Groq model name to use |
| `MONGO_URI` | No | `mongodb://localhost:27017` | MongoDB connection URI |
| `MONGO_DB` | No | `agent3_vendor_quality` | MongoDB database name |

---

## Running the App

```bash
streamlit run app.py
```

**Navigation (Sidebar):**

| Page | Purpose |
|---|---|
| **Seller Feedback** | Submit quality feedback as an internal seller or inspector |
| **Customer Feedback** | Submit feedback linked to a sales invoice |
| **Supplier Dashboard** | Monitor all supplier trust scores, trends, and feedback history |

**Quick test with seed data:**
- Open **Customer Feedback** → enter `INV-2026-001` → write feedback → submit
- System auto-resolves to **Apex Electronics Ltd.** (SUP-001) via the PO chain
- Open **Supplier Dashboard** → select Apex Electronics → see updated score and chart

---

## Sample Suppliers & Invoices

Use these in the app for immediate testing:

**Invoice Numbers:** `INV-2026-001` · `INV-2026-002` · `INV-2026-003` · `INV-2026-004` · `INV-2026-005` · `INV-2026-006`

**Product IDs:** `PROD-001` · `PROD-002` · `PROD-003` · `PROD-004` · `PROD-005` · `PROD-006`

**Invoice → Supplier mapping (via PO chain):**

| Invoice | Products on Invoice | Auto-Resolved Supplier |
|---|---|---|
| INV-2026-001 | PROD-001 (LED), PROD-002 (HDMI) | SUP-001 (Apex Electronics) |
| INV-2026-002 | PROD-003 (Breaker), PROD-004 (Bolt) | SUP-003 (CoreTech) |
| INV-2026-003 | PROD-001 (LED), PROD-005 (Box) | SUP-001 (Apex Electronics) |
| INV-2026-004 | PROD-002 (HDMI), PROD-006 (Paste) | SUP-002 (BrightGear) |
| INV-2026-005 | PROD-003 (Breaker), PROD-004 (Bolt) | SUP-003 (CoreTech) |
| INV-2026-006 | PROD-005 (Box), PROD-006 (Paste) | SUP-005 (EcoPackage) |

---

*Built with Streamlit · Groq · MongoDB*
