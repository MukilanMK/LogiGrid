"""
main.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Integrated Supply Chain Platform — Entry Point

Usage:
  # Start the FastAPI backend (port 8000)
  python main.py api

  # Start the Streamlit unified dashboard (port 8501)
  python main.py dashboard

  # Run a single end-to-end pipeline programmatically
  python main.py pipeline

  # Show registered routes
  python main.py routes

Running both services simultaneously (two separate terminals):
  Terminal 1:  python main.py api
  Terminal 2:  python main.py dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sys
import os

# Ensure project root is on the path so all imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


def _register_all_agents() -> None:
    """Register all 6 agent services with the Supervisor singleton."""
    from agents.supply_chain    import register_with_supervisor as r1
    from agents.rfq_matcher     import register_with_supervisor as r2
    from agents.quote_evaluator import register_with_supervisor as r3
    from agents.invoice_auditor import register_with_supervisor as r4
    from agents.vendor_quality  import register_with_supervisor as r5
    from agents.bi_analytics    import register_with_supervisor as r6

    r1(); r2(); r3(); r4(); r5(); r6()
    print("[main] All 6 agent services registered with Supervisor.")


def start_api() -> None:
    """Start the FastAPI + Uvicorn server."""
    import uvicorn
    from core.config import settings
    from api.router import app  # noqa: F401 — triggers startup registration

    print(f"[main] Starting FastAPI on {settings.api_host}:{settings.api_port}")
    print(f"[main] Docs available at: http://localhost:{settings.api_port}/docs")

    uvicorn.run(
        "api.router:app",
        host    = settings.api_host,
        port    = settings.api_port,
        reload  = False,
        log_level = "info",
    )


def start_dashboard() -> None:
    """Launch the Streamlit unified dashboard."""
    import subprocess
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard", "app.py")
    print(f"[main] Starting Streamlit dashboard: {dashboard_path}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", dashboard_path,
         "--server.port", "8501",
         "--server.headless", "true"],
        check=True,
    )


def run_pipeline() -> None:
    """
    Programmatic end-to-end pipeline run.
    Registers agents, pings DB, triggers Supervisor pipeline,
    and prints the resulting workflow state.
    """
    from core.db import ping, get_sync_db
    from orchestrator.supervisor import get_supervisor
    from orchestrator.data_contracts import AgentID

    print("[main] Checking MongoDB connection…")
    if not ping():
        print("[main] ERROR: Cannot connect to MongoDB. Check MONGO_URI in .env")
        sys.exit(1)
    print(f"[main] MongoDB connected — db: {get_sync_db().name}")

    _register_all_agents()

    sv    = get_supervisor()
    wf_id = sv.trigger_pipeline(
        initiated_by = AgentID.SUPERVISOR,
        notes        = "main.py programmatic run",
    )
    print(f"[main] Pipeline triggered — workflow_id: {wf_id}")

    wf = sv.get_workflow(wf_id)
    if wf:
        print(f"[main] Workflow status: {wf['status']}")
        for step in wf["steps"]:
            print(f"       [{step['timestamp'][:19]}] {step['status']} — {step['note']}")


def show_routes() -> None:
    """Print all registered FastAPI routes."""
    from api.router import app
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path    = getattr(route, "path", "")
        if methods:
            print(f"  {'|'.join(sorted(methods)):<8} {path}")


def print_help() -> None:
    print(__doc__)


# ─────────────────────────────────────────────────────────────────────────────
# CLI DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

COMMANDS = {
    "api":       start_api,
    "dashboard": start_dashboard,
    "pipeline":  run_pipeline,
    "routes":    show_routes,
    "help":      print_help,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    handler = COMMANDS.get(cmd)
    if handler:
        handler()
    else:
        print(f"Unknown command: '{cmd}'. Valid commands: {list(COMMANDS.keys())}")
        sys.exit(1)
