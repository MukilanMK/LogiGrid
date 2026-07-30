"""
agents/supply_chain.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 1 — Supply Chain & Demand Forecasting Engine

Core logic (preserved from original agent1/app.py):
  • SupplyChainDB        — MongoDB I/O (products, sales_invoices, calendar_context)
  • LangChainForecastAgent — LLM structured-output event velocity prediction
  • DeterministicMathEngine — 30-day stock countdown simulation

Integration:
  • Output (StockAlertPayload) is routed through supervisor.route()
  • register_with_supervisor() is called from main.py at startup
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from core.db import col
from core.llm_client import get_langchain_llm
from orchestrator.data_contracts import (
    AgentID,
    DeadstockItem,
    ProductNeed,
    StockAlertPayload,
    WorkflowStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC STRUCTURED SCHEMAS  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

class ProductVelocityItem(BaseModel):
    product_id:         str   = Field(description="Unique ID of the matched product")
    product_name:       str   = Field(description="Name of the product")
    predicted_velocity: float = Field(description="Predicted sales velocity on this specific event day")


class DailyVelocityList(BaseModel):
    day_number: int            = Field(description="1-based index for day within event duration")
    date:       str            = Field(description="Date string in YYYY-MM-DD format")
    products:   List[ProductVelocityItem] = Field(
        description="List of matched products and their predicted daily velocity on this day"
    )


class EventVelocityPredictionOutput(BaseModel):
    event_id:   str                  = Field(description="Unique ID or name of the event")
    event_name: str                  = Field(description="Name of the event")
    event_days: List[DailyVelocityList] = Field(
        description="List where length equals total event days. Each element contains daily predicted velocities."
    )


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE LAYER
# ─────────────────────────────────────────────────────────────────────────────

class SupplyChainDB:
    """All MongoDB reads / writes for Agent 1."""

    def fetch_products(self) -> List[Dict[str, Any]]:
        """Fetch products combined with 30-day sales velocity from unified DB."""
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        invoices = list(col("sales_invoices").find({"timestamp": {"$gte": thirty_days_ago}}))
        total_sales_map: Dict[str, int]       = {}
        daily_breakdown_map: Dict[str, List[int]] = {}

        for inv in invoices:
            inv_date = inv.get("timestamp")
            if isinstance(inv_date, datetime):
                if inv_date.tzinfo is None:
                    inv_date = inv_date.replace(tzinfo=timezone.utc)
                day_offset = (now - inv_date).days
            else:
                day_offset = 0

            for item in inv.get("line_items", []):
                p_id = str(item.get("product_id", ""))
                qty  = int(item.get("quantity", 0))
                total_sales_map[p_id] = total_sales_map.get(p_id, 0) + qty
                if p_id not in daily_breakdown_map:
                    daily_breakdown_map[p_id] = [0] * 30
                if 0 <= day_offset < 30:
                    daily_breakdown_map[p_id][day_offset] += qty

        products_raw = list(col("products").find({}))
        products: List[Dict[str, Any]] = []
        for p in products_raw:
            p_id = str(p.get("product_id", str(p.get("_id", ""))))
            units_sold = total_sales_map.get(p_id, 0)

            # Support both embedded inventory sub-doc and flat inventory collection
            inventory = p.get("inventory", {})
            if not inventory:
                inv_doc = col("inventory").find_one({"product_id": p_id}) or {}
                inventory = inv_doc

            products.append({
                "product_id":              p_id,
                "name":                    p.get("name", "Unknown"),
                "category":                p.get("category", "General"),
                "cost_price":              float(p.get("cost_price", 0.0)),
                "current_stock":           int(inventory.get("current_qty", 0)),
                "days_on_hand":            int(inventory.get("days_on_hand", 0)),
                "units_sold_30d":          units_sold,
                "baseline_daily_velocity": round(units_sold / 30.0, 2),
                "daily_sales_history":     daily_breakdown_map.get(p_id, [0] * 30),
            })
        return products

    def fetch_events(self) -> List[Dict[str, Any]]:
        """Fetch all calendar events."""
        events_raw = list(col("calendar_context").find({}))
        events: List[Dict[str, Any]] = []
        for e in events_raw:
            s_date = e.get("start_date")
            e_date = e.get("end_date")
            notes  = e.get("notes", e.get("purpose", ""))
            events.append({
                "_id":        str(e.get("_id")),
                "event_name": e.get("event_name", "Event"),
                "notes":      str(notes),
                "start_date": s_date.strftime("%Y-%m-%d") if isinstance(s_date, datetime) else str(s_date)[:10],
                "end_date":   e_date.strftime("%Y-%m-%d") if isinstance(e_date, datetime) else str(e_date)[:10],
            })
        return events

    def insert_event(self, event_name: str, notes: str, start_date: str, end_date: str) -> str:
        """Insert a new calendar event."""
        s_dt = datetime.strptime(start_date, "%Y-%m-%d") if isinstance(start_date, str) else start_date
        e_dt = datetime.strptime(end_date,   "%Y-%m-%d") if isinstance(end_date,   str) else end_date
        res = col("calendar_context").insert_one({
            "event_name": event_name,
            "notes":      notes,
            "start_date": s_dt,
            "end_date":   e_dt,
        })
        return str(res.inserted_id)


# ─────────────────────────────────────────────────────────────────────────────
# LLM AGENT CONTROLLER  (preserved from original)
# ─────────────────────────────────────────────────────────────────────────────

class LangChainForecastAgent:
    """LLM structured-output event velocity prediction (original logic preserved)."""

    SYSTEM_PROMPT = (
        "You are an expert AI supply chain planner.\n"
        "Analyze event details against product catalog mapping.\n\n"
        "Task:\n"
        "1. Read event notes.\n"
        "2. Identify products affected by the event.\n"
        "3. For EACH day from start_date to end_date (inclusive), "
        "predict the daily velocity for affected products.\n"
        "4. Omit unaffected products.\n"
        "5. Format output matching required schema."
    )

    def predict_event_velocities(
        self,
        event:    Dict[str, Any],
        products: List[Dict[str, Any]],
    ) -> EventVelocityPredictionOutput:
        llm = get_langchain_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(EventVelocityPredictionOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", self.SYSTEM_PROMPT),
            ("human", (
                "Event Details:\n"
                "- Event ID: {event_id}\n"
                "- Name: {event_name}\n"
                "- Notes: {notes}\n"
                "- Start Date: {start_date}\n"
                "- End Date: {end_date}\n\n"
                "Products Catalog JSON:\n{products_json}\n"
            )),
        ])
        chain = prompt | structured_llm

        catalog_summary = [
            {
                "product_id":              p["product_id"],
                "name":                    p["name"],
                "category":                p["category"],
                "baseline_daily_velocity": p["baseline_daily_velocity"],
            }
            for p in products
        ]
        return chain.invoke({
            "event_id":    event["_id"],
            "event_name":  event["event_name"],
            "notes":       event["notes"],
            "start_date":  event["start_date"],
            "end_date":    event["end_date"],
            "products_json": str(catalog_summary),
        })


# ─────────────────────────────────────────────────────────────────────────────
# DETERMINISTIC MATH ENGINE  (preserved exactly from original)
# ─────────────────────────────────────────────────────────────────────────────

class DeterministicMathEngine:
    """
    30-day stock depletion simulation.
    Applies baseline velocity + LLM event-spike overrides day-by-day.
    Produces:
      needed_products      — List[ProductNeed]
      not_selling_products — List[DeadstockItem]
      product_timelines    — per-product daily breakdown (for calendar widget)
    """

    @staticmethod
    def simulate_30_days(
        products:          List[Dict[str, Any]],
        llm_event_outputs: List[EventVelocityPredictionOutput],
    ) -> Dict[str, Any]:
        today      = datetime.now()
        dates_30d  = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]

        # Build event velocity lookup: {date: {product_id: (velocity, event_name)}}
        event_velocity_lookup: Dict[str, Dict[str, tuple]] = {}
        for ev_out in llm_event_outputs:
            ev_name = ev_out.event_name
            for day_data in ev_out.event_days:
                d_str = day_data.date
                if d_str not in event_velocity_lookup:
                    event_velocity_lookup[d_str] = {}
                for p_item in day_data.products:
                    pid       = p_item.product_id
                    pred_vel  = float(p_item.predicted_velocity)
                    if pid not in event_velocity_lookup[d_str] or pred_vel > event_velocity_lookup[d_str][pid][0]:
                        event_velocity_lookup[d_str][pid] = (pred_vel, ev_name)

        needed_products:      List[Dict[str, Any]] = []
        not_selling_products: List[Dict[str, Any]] = []
        product_timelines:    List[Dict[str, Any]] = []

        for p in products:
            prod_id      = p["product_id"]
            name         = p["name"]
            category     = p["category"]
            current_stock = p["current_stock"]
            days_on_hand  = p["days_on_hand"]
            cost_price    = p["cost_price"]
            baseline_vel  = p["baseline_daily_velocity"]

            running_stock   = float(current_stock)
            total_30d_demand = 0.0
            stockout_date   = None
            daily_timeline: List[Dict[str, Any]] = []

            for d_str in dates_30d:
                if d_str in event_velocity_lookup and prod_id in event_velocity_lookup[d_str]:
                    daily_vel, active_event_name = event_velocity_lookup[d_str][prod_id]
                else:
                    daily_vel          = baseline_vel
                    active_event_name  = "Normal"

                total_30d_demand += daily_vel
                running_stock     = max(0.0, running_stock - daily_vel)

                if (running_stock == 0.0 and stockout_date is None
                        and current_stock > 0 and daily_vel > 0):
                    stockout_date = d_str

                daily_timeline.append({
                    "date":            d_str,
                    "applied_event":   active_event_name,
                    "daily_velocity":  daily_vel,
                    "remaining_stock": math.floor(running_stock),
                })

            # Deadstock detection
            if baseline_vel == 0.0 and days_on_hand > 90 and total_30d_demand == 0.0:
                not_selling_products.append({
                    "product_id":     prod_id,
                    "product_name":   name,             # matches DeadstockItem.product_name
                    "category":       category,
                    "current_stock":  current_stock,
                    "days_on_hand":   days_on_hand,
                    "capital_tied_up": round(current_stock * cost_price, 2),
                    "reason": f"No sales for past {days_on_hand} days and 0 projected demand.",
                })
            elif current_stock < math.ceil(total_30d_demand) or stockout_date is not None:
                reorder_qty = max(0, math.ceil(total_30d_demand - current_stock))
                needed_products.append({
                    "product_id":             prod_id,
                    "product_name":           name,        # matches ProductNeed.product_name
                    "category":               category,
                    "current_stock":          current_stock,
                    "projected_30d_demand":   math.ceil(total_30d_demand),
                    "reorder_quantity":        reorder_qty,
                    "estimated_reorder_cost":  round(reorder_qty * cost_price, 2),
                    "stockout_warning_date":   stockout_date or "N/A (Sufficient Stock)",
                })

            product_timelines.append({
                "product_id":       prod_id,
                "product_name":     name,
                "category":         category,
                "daily_timeline":   daily_timeline,
                "baseline_velocity": baseline_vel,
                "current_stock":    current_stock,
            })

        return {
            "needed_products":      needed_products,
            "not_selling_products": not_selling_products,
            "product_timelines":    product_timelines,
        }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 SERVICE  (Supervisor-integrated wrapper)
# ─────────────────────────────────────────────────────────────────────────────

class SupplyChainService:
    """
    Service class registered with the Supervisor.
    Wraps DB + LLM + Math engine and emits StockAlertPayload via supervisor.route().
    """

    def __init__(self):
        self.db            = SupplyChainDB()
        self.llm_agent     = LangChainForecastAgent()
        self.math_engine   = DeterministicMathEngine()

    def run_pipeline(self, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Full Agent 1 pipeline:
          1. Fetch products + events
          2. Filter events in 30-day window
          3. LLM event velocity prediction
          4. 30-day deterministic simulation
          5. Emit StockAlertPayload → Supervisor
        Returns the simulation output dict for UI rendering.
        """
        from orchestrator.supervisor import get_supervisor

        products = self.db.fetch_products()
        events   = self.db.fetch_events()

        today_dt      = datetime.now()
        window_end_dt = today_dt + timedelta(days=30)
        today_str     = today_dt.strftime("%Y-%m-%d")
        window_end_str = window_end_dt.strftime("%Y-%m-%d")

        events_in_window = [
            ev for ev in events
            if ev["start_date"] <= window_end_str and ev["end_date"] >= today_str
        ]

        llm_predictions: List[EventVelocityPredictionOutput] = []
        for ev in events_in_window:
            pred = self.llm_agent.predict_event_velocities(ev, products)
            llm_predictions.append(pred)

        sim_output = self.math_engine.simulate_30_days(products, llm_predictions)

        # Build Pydantic payload and route through Supervisor
        needed    = [ProductNeed(**p) for p in sim_output["needed_products"]]
        deadstock = [DeadstockItem(**d) for d in sim_output["not_selling_products"]]

        payload = StockAlertPayload(
            workflow_id = workflow_id or f"WF-SC-{today_str}",
            needed_products    = needed,
            deadstock_products = deadstock,
            status = WorkflowStatus.SUCCESS,
        )

        try:
            get_supervisor().route(payload)
        except Exception as exc:
            from orchestrator.logger import logger
            logger.warning("Supervisor routing failed for StockAlertPayload: %s", exc)

        # Attach raw simulation data for UI
        sim_output["llm_predictions"]  = llm_predictions
        sim_output["events_in_window"] = events_in_window
        sim_output["products"]         = products
        sim_output["events"]           = events
        return sim_output


def register_with_supervisor() -> SupplyChainService:
    """Create the service, register it with the Supervisor, return it."""
    from orchestrator.supervisor import get_supervisor
    service = SupplyChainService()
    get_supervisor().register_agent(AgentID.SUPPLY_CHAIN, service)
    return service
