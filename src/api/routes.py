"""
============================================================
FastAPI Routes
============================================================
REST API endpoints for the Facilities Maintenance Assistant.

Endpoints:
  POST /work-orders          - Submit a new maintenance request
  GET  /work-orders/{id}     - Get work order details
  GET  /work-orders          - List all work orders
  
  GET  /reviews/pending      - Get work orders pending human review
  POST /reviews/{id}/approve - Approve a pending work order
  POST /reviews/{id}/reject  - Reject a pending work order
  
  GET  /governance/audit-trail/{id} - Full audit trail for a work order
  GET  /governance/dashboard        - Governance overview stats
  
  GET  /assets               - List all assets
  GET  /assets/{id}          - Get asset details
  GET  /assets/{id}/history  - Get asset maintenance history
  
  GET  /health               - Health check
  GET  /stats                - System statistics

Why these endpoints?
  - The work order endpoints handle the core workflow
  - The review endpoints enable human-in-the-loop
  - The governance endpoints provide transparency and auditability
  - The asset endpoints allow CMMS data exploration
  - Health and stats support production monitoring
============================================================
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from datetime import datetime
from typing import Optional

from src.models.schemas import WorkOrderCreate, WorkOrder, ReviewStatus
from src.crew import process_work_order
from src.governance.engine import GovernanceEngine
from src.data.database import (
    get_work_order,
    get_pending_reviews,
    get_audit_trail,
    get_asset,
    get_assets_in_building,
    get_asset_maintenance_history,
    get_connection,
    seed_database,
    initialize_database,
)


# ============================================================
# APP INITIALIZATION
# ============================================================

app = FastAPI(
    title="Agentic Facilities Maintenance Assistant",
    description=(
        "AI-powered facilities maintenance system with governance-first design "
        "and human-in-the-loop controls. Submit maintenance requests and let "
        "6 specialized AI agents analyze, plan, and route them with full "
        "audit trail and policy enforcement."
    ),
    version="1.0.0",
)

# Initialize database and seed on startup
initialize_database()
seed_database()

# Governance engine instance
governance_engine = GovernanceEngine()


# ============================================================
# WORK ORDER ENDPOINTS
# ============================================================

@app.post("/work-orders", status_code=202)
async def create_work_order(request: WorkOrderCreate, background_tasks: BackgroundTasks):
    """
    Submit a new maintenance work order.
    
    The request is accepted immediately (202) and processed
    asynchronously by the agent pipeline. This prevents the
    API from timing out during agent processing, which can
    take 30-60 seconds.
    
    The response includes the work_order_id so the caller
    can check status via GET /work-orders/{id}.
    """
    # Generate a temporary ID for tracking
    import uuid
    temp_id = f"WO-2026-{uuid.uuid4().hex[:4].upper()}"

    # Process in background so the API responds immediately
    background_tasks.add_task(_process_work_order_background, request)

    return {
        "message": "Work order submitted and processing started",
        "status": "processing",
        "note": "Use GET /work-orders to find your processed work order",
    }


async def _process_work_order_background(request: WorkOrderCreate):
    """Background task that runs the full agent pipeline."""
    try:
        result = process_work_order(request)
        print(f"Work order {result.work_order_id} processed: {result.status}")
    except Exception as e:
        print(f"Error processing work order: {e}")


@app.post("/work-orders/sync")
async def create_work_order_sync(request: WorkOrderCreate):
    """
    Submit and process a work order synchronously.
    
    Unlike the async endpoint above, this waits for the full
    agent pipeline to complete before responding. Useful for
    testing but may timeout in production (agent processing
    can take 30-60 seconds).
    """
    try:
        result = process_work_order(request)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/work-orders/{work_order_id}")
async def get_work_order_details(work_order_id: str):
    """
    Get the full details of a work order.
    
    Returns all agent analysis, governance decisions, and
    current status. This is the primary endpoint for checking
    what happened with a submitted request.
    """
    wo = get_work_order(work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail=f"Work order {work_order_id} not found")
    return wo


@app.get("/work-orders")
async def list_work_orders(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    building: Optional[str] = None,
    limit: int = 50,
):
    """
    List work orders with optional filters.
    
    Supports filtering by status, priority, and building.
    Returns most recent first.
    """
    conn = get_connection()
    query = "SELECT * FROM work_orders WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    if building:
        query += " AND building LIKE ?"
        params.append(f"%{building}%")

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# HUMAN-IN-THE-LOOP REVIEW ENDPOINTS
# ============================================================

@app.get("/reviews/pending")
async def get_pending_review_list():
    """
    Get all work orders waiting for human review.
    
    This is the human reviewer's inbox. Each item includes
    the escalation reason so the reviewer knows why the
    AI couldn't auto-approve it.
    """
    reviews = get_pending_reviews()
    if not reviews:
        return {"message": "No work orders pending review", "count": 0}
    return {"count": len(reviews), "pending_reviews": reviews}


@app.post("/reviews/{work_order_id}/approve")
async def approve_work_order(
    work_order_id: str,
    reviewer_name: str = "Facilities Manager",
    notes: Optional[str] = None,
):
    """
    Approve a work order that was escalated for human review.
    
    This completes the human-in-the-loop cycle. The approval
    is logged in the audit trail with the reviewer's name
    and any notes they provide.
    """
    wo = get_work_order(work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo["status"] != "pending_human_review":
        raise HTTPException(
            status_code=400,
            detail=f"Work order is not pending review (current status: {wo['status']})"
        )

    result = governance_engine.process_human_review(
        work_order_id, approved=True, reviewer_name=reviewer_name, notes=notes
    )
    return {"message": "Work order approved", **result}


@app.post("/reviews/{work_order_id}/reject")
async def reject_work_order(
    work_order_id: str,
    reviewer_name: str = "Facilities Manager",
    notes: Optional[str] = None,
):
    """
    Reject a work order that was escalated for human review.
    
    The rejection is logged with the reviewer's reasoning.
    Rejected work orders can be resubmitted with modifications.
    """
    wo = get_work_order(work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo["status"] != "pending_human_review":
        raise HTTPException(
            status_code=400,
            detail=f"Work order is not pending review (current status: {wo['status']})"
        )

    result = governance_engine.process_human_review(
        work_order_id, approved=False, reviewer_name=reviewer_name, notes=notes
    )
    return {"message": "Work order rejected", **result}


# ============================================================
# GOVERNANCE ENDPOINTS
# ============================================================

@app.get("/governance/audit-trail/{work_order_id}")
async def get_work_order_audit_trail(work_order_id: str):
    """
    Get the complete audit trail for a work order.
    
    Returns every decision made by every agent, every governance
    check, and every human review action. This is the transparency
    endpoint. An auditor can use this to understand exactly how
    and why decisions were made.
    """
    trail = get_audit_trail(work_order_id)
    if not trail:
        raise HTTPException(
            status_code=404,
            detail=f"No audit trail found for {work_order_id}"
        )
    return {"work_order_id": work_order_id, "decisions": trail}


@app.get("/governance/dashboard")
async def governance_dashboard():
    """
    Governance overview dashboard.
    
    Provides summary statistics about the system's operation:
    - Total work orders processed
    - How many were auto-approved vs. escalated
    - Breakdown by escalation reason
    - Average confidence scores
    """
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status = 'pending_human_review'"
    ).fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status = 'approved'"
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status = 'rejected'"
    ).fetchone()[0]
    auto_approved = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE requires_human_review = 0 AND status = 'approved'"
    ).fetchone()[0]

    # Escalation breakdown
    escalations = conn.execute(
        "SELECT escalation_reason, COUNT(*) as count FROM work_orders "
        "WHERE escalation_reason IS NOT NULL GROUP BY escalation_reason"
    ).fetchall()

    # Average confidence
    avg_conf = conn.execute(
        "SELECT AVG(confidence_score) FROM work_orders WHERE confidence_score IS NOT NULL"
    ).fetchone()[0]

    # Total decisions logged
    total_decisions = conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0]

    conn.close()

    return {
        "summary": {
            "total_work_orders": total,
            "pending_human_review": pending,
            "approved": approved,
            "rejected": rejected,
            "auto_approved": auto_approved,
            "human_reviewed": approved + rejected - auto_approved,
        },
        "escalation_breakdown": {row["escalation_reason"]: row["count"] for row in escalations},
        "average_confidence_score": round(avg_conf, 2) if avg_conf else None,
        "total_agent_decisions_logged": total_decisions,
        "governance_policy": {
            "cost_threshold": 5000.00,
            "confidence_threshold": 0.70,
            "auto_approve_priorities": ["low", "medium"],
            "require_review_for_critical": True,
            "require_review_for_replacement": True,
        },
    }


# ============================================================
# ASSET ENDPOINTS
# ============================================================

@app.get("/assets")
async def list_assets(building: Optional[str] = None):
    """List all assets, optionally filtered by building."""
    conn = get_connection()
    if building:
        rows = conn.execute(
            "SELECT * FROM assets WHERE building LIKE ? ORDER BY building, category",
            (f"%{building}%",)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM assets ORDER BY building, category").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/assets/{asset_id}")
async def get_asset_details(asset_id: str):
    """Get detailed information about a specific asset."""
    asset = get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset


@app.get("/assets/{asset_id}/history")
async def get_asset_history(asset_id: str):
    """Get the full maintenance history for an asset."""
    history = get_asset_maintenance_history(asset_id)
    if not history:
        return {"asset_id": asset_id, "message": "No maintenance records found", "records": []}
    
    total_cost = sum(r["cost"] for r in history)
    return {
        "asset_id": asset_id,
        "total_records": len(history),
        "total_cost": total_cost,
        "records": history,
    }


# ============================================================
# SYSTEM ENDPOINTS
# ============================================================

@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.
    Returns system status, database connectivity, and uptime info.
    """
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_status = "connected"
    except Exception:
        db_status = "error"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/stats")
async def system_stats():
    """System statistics for monitoring and dashboards."""
    conn = get_connection()
    stats = {
        "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        "technicians": conn.execute("SELECT COUNT(*) FROM technicians").fetchone()[0],
        "maintenance_records": conn.execute("SELECT COUNT(*) FROM maintenance_records").fetchone()[0],
        "work_orders": conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0],
        "agent_decisions": conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0],
        "pending_reviews": conn.execute(
            "SELECT COUNT(*) FROM work_orders WHERE status = 'pending_human_review'"
        ).fetchone()[0],
    }
    conn.close()
    return stats
