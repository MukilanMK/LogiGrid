import os
import math
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import streamlit as st
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# LangChain & Groq Imports
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from streamlit_calendar import calendar

# ---------------------------------------------------------------------
# SETUP & STREAMLIT CONFIG
# ---------------------------------------------------------------------
load_dotenv()
st.set_page_config(
    page_title="Agentic Supply Chain Engine",
    page_icon="🤖",
    layout="wide"
)

COMPACT_CALENDAR_OPTIONS = {
    "initialView": "dayGridMonth",
    "editable": False,
    "selectable": True,
    "height": 420,
    "contentHeight": 380,
    "aspectRatio": 2.0,
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    }
}


# ---------------------------------------------------------------------
# PYDANTIC STRUCTURED SCHEMAS FOR AGENT OUTPUT
# ---------------------------------------------------------------------

class ProductVelocityItem(BaseModel):
    product_id: str = Field(description="Unique ID of the matched product")
    product_name: str = Field(description="Name of the product")
    predicted_velocity: float = Field(description="Predicted sales velocity on this specific event day")


class DailyVelocityList(BaseModel):
    day_number: int = Field(description="1-based index for day within event duration")
    date: str = Field(description="Date string in YYYY-MM-DD format")
    products: List[ProductVelocityItem] = Field(
        description="List of matched products and their predicted daily velocity on this day"
    )


class EventVelocityPredictionOutput(BaseModel):
    event_id: str = Field(description="Unique ID or name of the event")
    event_name: str = Field(description="Name of the event")
    event_days: List[DailyVelocityList] = Field(
        description="List where length equals total event days. Each element contains daily predicted velocities."
    )


# ---------------------------------------------------------------------
# DATABASE LAYER
# ---------------------------------------------------------------------

class SupplyChainDatabase:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.db_name = os.getenv("DB_NAME", "supply_chain_db")
        self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=3000)
        self.db = self.client[self.db_name]

    def fetch_products(self) -> List[Dict[str, Any]]:
        """Fetch product list combined with past 30 days sales velocity."""
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        invoices = list(self.db.sales_invoices.find({"timestamp": {"$gte": thirty_days_ago}}))
        total_sales_map = {}
        daily_breakdown_map = {}

        for inv in invoices:
            inv_date = inv.get("timestamp")
            if isinstance(inv_date, datetime):
                if inv_date.tzinfo is None:
                    inv_date = inv_date.replace(tzinfo=timezone.utc)
                day_offset = (now - inv_date).days
            else:
                day_offset = 0
            
            for item in inv.get("line_items", []):
                p_id = str(item["product_id"])
                qty = int(item["quantity"])
                total_sales_map[p_id] = total_sales_map.get(p_id, 0) + qty
                
                if p_id not in daily_breakdown_map:
                    daily_breakdown_map[p_id] = [0] * 30
                if 0 <= day_offset < 30:
                    daily_breakdown_map[p_id][day_offset] += qty

        products_raw = list(self.db.products.find({}))
        products = []
        for p in products_raw:
            p_id = str(p["_id"])
            units_sold = total_sales_map.get(p_id, 0)
            inventory = p.get("inventory", {})

            products.append({
                "product_id": p_id,
                "name": p.get("name", "Unknown"),
                "category": p.get("category", "General"),
                "cost_price": float(p.get("cost_price", 0.0)),
                "current_stock": int(inventory.get("current_qty", 0)),
                "days_on_hand": int(inventory.get("days_on_hand", 0)),
                "units_sold_30d": units_sold,
                "baseline_daily_velocity": round(units_sold / 30.0, 2),
                "daily_sales_history": daily_breakdown_map.get(p_id, [0] * 30)
            })
        return products

    def fetch_events(self) -> List[Dict[str, Any]]:
        """Fetch all calendar events."""
        events_raw = list(self.db.calendar_context.find({}))
        events = []
        for e in events_raw:
            s_date = e.get("start_date")
            e_date = e.get("end_date")
            notes = e.get("notes", e.get("purpose", ""))

            events.append({
                "_id": str(e.get("_id")),
                "event_name": e.get("event_name", "Event"),
                "notes": str(notes),
                "start_date": s_date.strftime("%Y-%m-%d") if isinstance(s_date, datetime) else str(s_date)[:10],
                "end_date": e_date.strftime("%Y-%m-%d") if isinstance(e_date, datetime) else str(e_date)[:10]
            })
        return events

    def insert_event(self, event_name: str, notes: str, start_date: str, end_date: str) -> str:
        """Insert a newly detected event into MongoDB."""
        s_dt = datetime.strptime(start_date, "%Y-%m-%d") if isinstance(start_date, str) else start_date
        e_dt = datetime.strptime(end_date, "%Y-%m-%d") if isinstance(end_date, str) else end_date
        
        doc = {
            "event_name": event_name,
            "notes": notes,
            "start_date": s_dt,
            "end_date": e_dt
        }
        res = self.db.calendar_context.insert_one(doc)
        return str(res.inserted_id)


# ---------------------------------------------------------------------
# LANGCHAIN AGENT CONTROLLER
# ---------------------------------------------------------------------

class LangChainSupplyChainAgent:
    def __init__(self):
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            st.error("🔑 GROQ_API_KEY missing from environment (.env file).")
            st.stop()
        
        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            groq_api_key=groq_api_key,
            temperature=0.1
        )

    def predict_event_velocities(
        self,
        event: Dict[str, Any],
        products: List[Dict[str, Any]]
    ) -> EventVelocityPredictionOutput:
        """Predict day-by-day velocity impact using LLM structured output."""
        system_prompt = (
            "You are an expert AI supply chain planner.\n"
            "Analyze event details against product catalog mapping.\n\n"
            "Task:\n"
            "1. Read event notes.\n"
            "2. Identify products affected by the event.\n"
            "3. For EACH day from start_date to end_date (inclusive), predict the daily velocity for affected products.\n"
            "4. Omit unaffected products.\n"
            "5. Format output matching required schema."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", (
                "Event Details:\n"
                "- Event ID: {event_id}\n"
                "- Name: {event_name}\n"
                "- Notes: {notes}\n"
                "- Start Date: {start_date}\n"
                "- End Date: {end_date}\n\n"
                "Products Catalog JSON:\n{products_json}\n"
            ))
        ])

        structured_llm = self.llm.with_structured_output(EventVelocityPredictionOutput)
        chain = prompt | structured_llm

        catalog_summary = [
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "category": p["category"],
                "baseline_daily_velocity": p["baseline_daily_velocity"]
            }
            for p in products
        ]

        return chain.invoke({
            "event_id": event["_id"],
            "event_name": event["event_name"],
            "notes": event["notes"],
            "start_date": event["start_date"],
            "end_date": event["end_date"],
            "products_json": str(catalog_summary)
        })


# ---------------------------------------------------------------------
# DETERMINISTIC SIMULATION ENGINE
# ---------------------------------------------------------------------

class DeterministicMathEngine:
    @staticmethod
    def simulate_30_days(
        products: List[Dict[str, Any]],
        llm_event_outputs: List[EventVelocityPredictionOutput]
    ) -> Dict[str, Any]:
        """Calculates 30-day stock depletion based on baseline and event spikes."""
        today = datetime.now()
        dates_30_days = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]

        event_velocity_lookup: Dict[str, Dict[str, tuple]] = {}
        
        for ev_out in llm_event_outputs:
            ev_name = ev_out.event_name
            for day_data in ev_out.event_days:
                d_str = day_data.date
                if d_str not in event_velocity_lookup:
                    event_velocity_lookup[d_str] = {}
                
                for p_item in day_data.products:
                    pid = p_item.product_id
                    pred_vel = float(p_item.predicted_velocity)
                    if pid not in event_velocity_lookup[d_str] or pred_vel > event_velocity_lookup[d_str][pid][0]:
                        event_velocity_lookup[d_str][pid] = (pred_vel, ev_name)

        needed_products = []
        not_selling_products = []
        product_timelines = []

        for p in products:
            prod_id = p["product_id"]
            name = p["name"]
            category = p["category"]
            current_stock = p["current_stock"]
            days_on_hand = p["days_on_hand"]
            cost_price = p["cost_price"]
            baseline_vel = p["baseline_daily_velocity"]

            running_stock = float(current_stock)
            total_30d_demand = 0.0
            stockout_date = None
            daily_timeline = []

            for d_str in dates_30_days:
                if d_str in event_velocity_lookup and prod_id in event_velocity_lookup[d_str]:
                    daily_vel, active_event_name = event_velocity_lookup[d_str][prod_id]
                else:
                    daily_vel = baseline_vel
                    active_event_name = "Normal"

                total_30d_demand += daily_vel
                running_stock = max(0.0, running_stock - daily_vel)

                if running_stock == 0.0 and stockout_date is None and current_stock > 0 and daily_vel > 0:
                    stockout_date = d_str

                daily_timeline.append({
                    "date": d_str,
                    "applied_event": active_event_name,
                    "daily_velocity": daily_vel,
                    "remaining_stock": math.floor(running_stock)
                })

            if baseline_vel == 0.0 and days_on_hand > 90 and total_30d_demand == 0.0:
                not_selling_products.append({
                    "product_id": prod_id,
                    "name": name,
                    "category": category,
                    "current_stock": current_stock,
                    "days_on_hand": days_on_hand,
                    "capital_tied_up": round(current_stock * cost_price, 2),
                    "reason": f"No sales for past {days_on_hand} days and 0 projected demand."
                })
            elif current_stock < math.ceil(total_30d_demand) or stockout_date is not None:
                reorder_qty = max(0, math.ceil(total_30d_demand - current_stock))
                needed_products.append({
                    "product_id": prod_id,
                    "name": name,
                    "category": category,
                    "current_stock": current_stock,
                    "projected_30d_demand": math.ceil(total_30d_demand),
                    "reorder_quantity": reorder_qty,
                    "estimated_reorder_cost": round(reorder_qty * cost_price, 2),
                    "stockout_warning_date": stockout_date or "N/A (Sufficient Stock)"
                })

            product_timelines.append({
                "product_id": prod_id,
                "product_name": name,
                "category": category,
                "daily_timeline": daily_timeline,
                "baseline_velocity": baseline_vel,
                "current_stock": current_stock
            })

        return {
            "needed_products": needed_products,
            "not_selling_products": not_selling_products,
            "product_timelines": product_timelines
        }


# ---------------------------------------------------------------------
# UI MAIN APPLICATION
# ---------------------------------------------------------------------

db = SupplyChainDatabase()
st.title("🤖 Agentic Supply Chain Engine")

# 1. CATALOG
st.header("1. Product Catalog & Baseline Daily Velocity")
products = db.fetch_products()
if products:
    df_products = pd.DataFrame(products)
    st.dataframe(
        df_products[["product_id", "name", "category", "cost_price", "current_stock", "days_on_hand", "baseline_daily_velocity"]],
        use_container_width=True
    )

st.divider()

# 2. EVENTS
st.header("2. Events Table (`calendar_context`)")
events = db.fetch_events()

with st.expander("➕ Add / Insert New Event to Database"):
    with st.form("add_event_form"):
        new_ev_name = st.text_input("Event Name", value="Monsoon Festival")
        new_ev_notes = st.text_area("Notes", value="This event will cause the increase in the electronics categories.")
        col_s, col_e = st.columns(2)
        today_date = datetime.now()
        new_start = col_s.date_input("Start Date", value=today_date)
        new_end = col_e.date_input("End Date", value=today_date + timedelta(days=3))
        
        submitted = st.form_submit_button("Save Event to MongoDB")
        if submitted:
            inserted_id = db.insert_event(
                event_name=new_ev_name,
                notes=new_ev_notes,
                start_date=new_start.strftime("%Y-%m-%d"),
                end_date=new_end.strftime("%Y-%m-%d")
            )
            st.success(f"✅ Saved event '{new_ev_name}' with ID: {inserted_id}")
            st.rerun()

if events:
    st.dataframe(pd.DataFrame(events)[["_id", "event_name", "notes", "start_date", "end_date"]], use_container_width=True)

st.divider()

# 3. PIPELINE TRIGGER
if st.button("🚀 Run Agent Event Intelligence & Simulation", type="primary"):
    agent = LangChainSupplyChainAgent()
    
    today_dt = datetime.now()
    window_end_dt = today_dt + timedelta(days=30)
    today_str = today_dt.strftime("%Y-%m-%d")
    window_end_str = window_end_dt.strftime("%Y-%m-%d")

    events_in_window = [
        ev for ev in events
        if ev["start_date"] <= window_end_str and ev["end_date"] >= today_str
    ]

    llm_predictions: List[EventVelocityPredictionOutput] = []

    if events_in_window:
        st.info(f"🔍 Analyzing {len(events_in_window)} event(s) in 30-day window...")
        for ev in events_in_window:
            pred_out = agent.predict_event_velocities(ev, products)
            llm_predictions.append(pred_out)

    sim_output = DeterministicMathEngine.simulate_30_days(products, llm_predictions)

    st.session_state["sim_output"] = sim_output
    st.session_state["llm_predictions"] = llm_predictions
    st.session_state["events_in_window"] = events_in_window


# ---------------------------------------------------------------------
# 4. NATIVE STREAMLIT WIDGET PREDICTIONS DISPLAY
# ---------------------------------------------------------------------
if "sim_output" in st.session_state:
    st.header("3. LLM Agent Output Predictions")
    llm_preds: List[EventVelocityPredictionOutput] = st.session_state.get("llm_predictions", [])

    if llm_preds:
        # Display Mode Toggle using Native Streamlit Widget
        display_mode = st.radio(
            "Select Widget View Mode:",
            options=["📊 Interactive Matrix Widget", "🎴 Native Metric Cards"],
            horizontal=True
        )

        for ev_out in llm_preds:
            with st.container(border=True):
                st.subheader(f"🎉 Event: {ev_out.event_name}")

                if display_mode == "📊 Interactive Matrix Widget":
                    # Build structured Pivot Table Dataframe
                    table_dict = {}
                    for day in ev_out.event_days:
                        try:
                            dt_obj = datetime.strptime(day.date, "%Y-%m-%d")
                            col_key = dt_obj.strftime("%d/%m/%Y")
                        except Exception:
                            col_key = day.date
                        
                        table_dict[col_key] = {
                            p.product_name: p.predicted_velocity for p in day.products
                        }

                    df_matrix = pd.DataFrame(table_dict).fillna(0.0)
                    
                    if not df_matrix.empty:
                        # Render Streamlit Configured Dataframe Widget
                        st.dataframe(
                            df_matrix,
                            use_container_width=True,
                            column_config={
                                col: st.column_config.NumberColumn(
                                    col,
                                    help=f"Predicted Daily Sales Velocity on {col}",
                                    format="%.1f units/day"
                                ) for col in df_matrix.columns
                            }
                        )
                    else:
                        st.caption("No affected SKUs identified for this event.")

                else:
                    # Render using native st.columns and st.metric cards
                    if ev_out.event_days:
                        cols = st.columns(len(ev_out.event_days))
                        for idx, day in enumerate(ev_out.event_days):
                            with cols[idx]:
                                try:
                                    dt_obj = datetime.strptime(day.date, "%Y-%m-%d")
                                    date_str = dt_obj.strftime("%d/%m/%Y")
                                except Exception:
                                    date_str = day.date

                                with st.container(border=True):
                                    st.markdown(f"🗓️ **{date_str}**")
                                    if day.products:
                                        for p in day.products:
                                            st.metric(
                                                label=p.product_name,
                                                value=f"{p.predicted_velocity} /day"
                                            )
                                    else:
                                        st.caption("No Impact")

    else:
        st.info("No active events found in the selected 30-day window.")

    st.divider()

    # 5. CALENDAR WIDGET
    st.header("4. Interactive Inventory Calendar View")
    sim_res = st.session_state["sim_output"]

    if "selected_prod" not in st.session_state:
        st.session_state["selected_prod"] = products[0]["name"] if products else None

    cols = st.columns(min(len(products), 6) if products else 1)
    for idx, prod in enumerate(products):
        col_idx = idx % len(cols)
        if cols[col_idx].button(f"📦 {prod['name']}", key=f"btn_p_{prod['product_id']}"):
            st.session_state["selected_prod"] = prod["name"]

    selected_prod_name = st.session_state["selected_prod"]
    cal_events = []

    for ev in st.session_state.get("events_in_window", []):
        cal_events.append({
            "title": f"🎉 {ev['event_name']}: {ev['notes']}",
            "start": ev["start_date"],
            "end": ev["end_date"],
            "color": "#3b82f6",
            "allDay": True
        })

    if selected_prod_name:
        timeline_entry = next((t for t in sim_res["product_timelines"] if t["product_name"] == selected_prod_name), None)
        if timeline_entry:
            st.caption(f"Showing 30-Day Stock Balance for: **{selected_prod_name}** (Baseline Vel: {timeline_entry['baseline_velocity']}/d)")
            for day_data in timeline_entry["daily_timeline"]:
                rem_stock = day_data["remaining_stock"]
                fin_vel = day_data["daily_velocity"]
                ev_tag = day_data["applied_event"]
                color = "#ef4444" if rem_stock <= 0 else ("#f59e0b" if rem_stock <= 5 else "#22c55e")

                cal_events.append({
                    "title": f"Stock: {rem_stock} (Vel: {fin_vel}/d) [{ev_tag}]",
                    "start": day_data["date"],
                    "color": color,
                    "allDay": True
                })

    calendar(events=cal_events, options=COMPACT_CALENDAR_OPTIONS, key="supply_calendar")

    st.divider()

    # 6. RESTOCK & DEADSTOCK LISTS
    st.header("5. Result Lists")
    col_needed, col_dead = st.columns(2)

    with col_needed:
        st.subheader("🛒 List A: Restock Needed")
        needed = sim_res["needed_products"]
        if needed:
            df_needed = pd.DataFrame(needed)
            st.dataframe(df_needed, use_container_width=True)
            st.metric("Total Procurement Cost", f"₹{df_needed['estimated_reorder_cost'].sum():,.2f}")
        else:
            st.success("All products have sufficient stock for the next 30 days.")

    with col_dead:
        st.subheader("⚠️ List B: Deadstock")
        not_moving = sim_res["not_selling_products"]
        if not_moving:
            df_dead = pd.DataFrame(not_moving)
            st.dataframe(df_dead, use_container_width=True)
            st.metric("Total Tied-Up Capital", f"₹{df_dead['capital_tied_up'].sum():,.2f}")
        else:
            st.success("No deadstock identified.")