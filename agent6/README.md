# Agent 5 - Profit Analytics & Conversational BI Engine

## Overview

**Agent 5** is an Executive Profit Analytics dashboard and Conversational BI Engine. Unlike traditional chat-based BI tools, Agent 5 functions as a **Dynamic BI Visualizer**. It translates natural language user queries into MongoDB aggregation pipelines, executes them securely, and automatically determines the optimal visualization (Bar, Line, Pie, Scatter, Heatmap, or Box plot) based on the data shape. The results are presented in a sleek, "Obsidian Dark" themed executive dashboard built with Streamlit.

The application leverages the **Groq API** running the ultra-fast `llama-3.3-70b-versatile` model to interpret user intent, write dynamic MQL (MongoDB Query Language), and generate actionable analytical summaries.

## System Architecture & Flow

The system consists of a **FastAPI backend**, a **MongoDB database**, and a **Streamlit frontend**. 

### 1. User Input (Streamlit Frontend)
The user enters a natural language query in the Streamlit web interface (e.g., *"What is our total profit margin breakdown by product category?"*).

### 2. FastAPI Backend Processing
The request is routed to the `POST /api/query` endpoint in `backend/main.py`. The backend executes a **two-pass LLM pipeline**:

#### Pass 1: Dynamic Text-to-MQL Generation
- The backend fetches the live product catalog from MongoDB.
- It sends the user query, the product catalog, and the database schema to the Groq LLM.
- The LLM generates a valid **MongoDB aggregation pipeline** as a JSON array.
- A regex cleaner strips any markdown formatting from the response, and the backend parses it into a Python list.

#### Execution & Serialization
- The generated pipeline is verified against a strict allow-list of read-only MongoDB aggregation stages (e.g., `$match`, `$group`, `$lookup`, `$project`) to ensure absolute security.
- The pipeline is executed against the `sales_invoices` MongoDB collection using the async `motor` driver.
- The raw BSON results are passed through a custom recursive serializer (`serialize_bson()`) which safely converts `ObjectId` and native MongoDB `datetime` objects into JSON-compatible formats.

#### Pass 2: Dynamic Insights & Chart Configuration
- The original user query and the retrieved MongoDB dataset are sent back to the Groq LLM.
- The LLM analyzes the data and returns:
  - A concise, 1-2 sentence **analytical summary** of the key findings.
  - An optimal **chart configuration** (e.g., `{"type": "bar", "x_axis": "category", "y_axis": "total_profit"}`) dynamically chosen based on the data shape.

### 3. Frontend Visualization (Streamlit)
The JSON payload containing the MQL pipeline, table data, insights, and chart config is returned to the Streamlit app (`streamlit_app.py`). The frontend renders:
- High-level **KPI metrics** (Total Revenue, Net Profit, Average Margin).
- A **dynamic visualization** generated via Seaborn & Matplotlib, styled with a custom Obsidian Dark theme.
- The **AI Executive Insight** summary.
- An **Enhanced Profit Data Grid** featuring in-cell visual progress bars and dynamic margin indicator badges.

---

## Directory Structure

```text
.
├── backend/
│   ├── .env               # Environment configuration (API Keys & DB URL)
│   ├── main.py            # FastAPI backend (Two-pass LLM pipeline)
│   ├── requirements.txt   # Python dependencies
│   └── seed_db.py         # Script to populate MongoDB with initial data
├── streamlit_app.py       # Streamlit frontend dashboard
└── docker-compose.yml     # Docker compose file (if applicable)
```

## Prerequisites

- **Python 3.11+**
- **MongoDB**: A running local or remote instance (default: `mongodb://localhost:27017/`)
- **Groq API Key**: You must have a valid API key from [Groq](https://console.groq.com/keys)

## Setup & Installation

### 1. Configure the Environment
Navigate to the `backend` directory and edit the `.env` file to include your actual Groq API key:

```ini
# backend/.env
DATABASE_URL=mongodb://localhost:27017/
GROQ_API_KEY=your_actual_groq_api_key_here
```

### 2. Install Dependencies
Create a virtual environment and install the required Python packages:

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Seed the Database
Ensure your MongoDB server is running, then populate it with the starter products and sales invoices:

```bash
python seed_db.py
```

## Running the Application

To run the application, you need to start both the FastAPI backend and the Streamlit frontend.

### Terminal 1: Start the FastAPI Backend
Ensure your virtual environment is active.
```bash
cd backend
uvicorn main:app --reload
```
The backend will run on `http://127.0.0.1:8000`.

### Terminal 2: Start the Streamlit Frontend
In a new terminal window (ensure the same virtual environment is active):
```bash
streamlit run streamlit_app.py
```
The executive dashboard will automatically open in your browser at `http://localhost:8501`.

## Technologies Used
- **Backend Framework:** FastAPI, Uvicorn
- **Frontend Framework:** Streamlit
- **Database:** MongoDB (Async Motor driver)
- **AI / LLM:** Groq API (`llama-3.3-70b-versatile`)
- **Visualizations:** Seaborn, Matplotlib, Plotly (Legacy support)
- **Data Manipulation:** Pandas
