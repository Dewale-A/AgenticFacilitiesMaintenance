"""
============================================================
Crew Orchestration
============================================================
This module ties everything together. It:
  1. Creates all 6 agents with their tools
  2. Creates tasks for a specific work order
  3. Runs the sequential pipeline
  4. Passes results through the Governance Engine
  5. Returns the final work order (approved or pending review)

This is the entry point. The FastAPI endpoints call this
to process work orders.

Sequential Flow:
  Input -> Intake -> Triage -> Planning -> Knowledge -> 
  Compliance -> Reporting -> Governance Check -> Output
============================================================
"""

import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
from crewai import Crew, Process
from crewai.tools import tool

# Load environment variables
load_dotenv()

# Local imports
from src.agents.definitions import (
    create_intake_agent,
    create_triage_agent,
    create_planning_agent,
    create_knowledge_agent,
    create_compliance_agent,
    create_reporting_agent,
)
from src.tasks.definitions import (
    create_intake_task,
    create_triage_task,
    create_planning_task,
    create_knowledge_task,
    create_compliance_task,
    create_reporting_task,
)
from src.tools.cmms_tools import (
    lookup_asset,
    lookup_assets_in_building,
    get_maintenance_history,
    find_available_technicians,
    get_parts_inventory,
    search_work_orders,
)
from src.tools.rag_tools import search_maintenance_docs, get_document_list
from src.governance.engine import GovernanceEngine
from src.models.schemas import WorkOrder, WorkOrderCreate, WorkOrderStatus
from src.data.database import save_work_order, seed_database


# ============================================================
# TOOL WRAPPERS
# ============================================================
# CrewAI needs tools decorated with @tool. These are thin
# wrappers around our tool functions that add the decorator.
# The actual logic stays in the tool modules (separation of concerns).

@tool("Lookup Asset")
def lookup_asset_tool(asset_id: str) -> str:
    """Look up detailed information about a specific asset in the CMMS database.
    Use this when you have an asset ID and need to know its details like
    condition, age, location, and warranty status."""
    return lookup_asset(asset_id)


@tool("Find Assets in Building")
def lookup_assets_in_building_tool(building: str) -> str:
    """Find all assets in a specific building. Use this when a work order
    mentions a building but not a specific asset ID."""
    return lookup_assets_in_building(building)


@tool("Get Maintenance History")
def get_maintenance_history_tool(asset_id: str) -> str:
    """Retrieve the full maintenance history for an asset. Use this to
    check for recurring issues, calculate total repair costs, and
    determine if replacement should be considered."""
    return get_maintenance_history(asset_id)


@tool("Find Available Technicians")
def find_available_technicians_tool(trade: str) -> str:
    """Find available technicians filtered by trade specialty.
    Returns technicians sorted by lowest workload first.
    Trades: hvac, electrical, plumbing, carpentry, painting,
    roofing, janitorial, grounds, elevator, fire_safety, general."""
    return find_available_technicians(trade)


@tool("Check Parts Inventory")
def get_parts_inventory_tool(part_name: str) -> str:
    """Check parts inventory for availability and pricing.
    Use partial names to search (e.g., 'filter' finds all filter types)."""
    return get_parts_inventory(part_name)


@tool("Search Work Orders")
def search_work_orders_tool(building: str) -> str:
    """Search existing work orders by building name to check for
    duplicates or related issues."""
    return search_work_orders(building=building)


@tool("Search Maintenance Documentation")
def search_maintenance_docs_tool(query: str) -> str:
    """Search maintenance manuals, SOPs, and compliance guides using
    semantic search. Use natural language queries like 'HVAC filter
    replacement procedure' or 'elevator safety requirements'."""
    return search_maintenance_docs(query)


@tool("List Available Documents")
def get_document_list_tool() -> str:
    """List all available maintenance documents in the knowledge base."""
    return get_document_list()


# ============================================================
# CREW BUILDER
# ============================================================

def process_work_order(request: WorkOrderCreate) -> WorkOrder:
    """
    Process a maintenance work order through the full agent pipeline.
    
    This is the main function. It:
      1. Seeds the database (first run only)
      2. Creates a WorkOrder from the request
      3. Builds agents with appropriate tools
      4. Creates tasks with the work order data
      5. Runs the crew (sequential processing)
      6. Parses agent outputs to update the work order
      7. Runs governance evaluation
      8. Saves to database
      9. Returns the final work order
    
    Args:
        request: The incoming work order request from the API
        
    Returns:
        Complete WorkOrder with all agent analysis and governance status
    """
    # Ensure database is seeded
    seed_database()

    # Initialize governance engine
    governance = GovernanceEngine()

    # Create initial work order
    work_order_id = f"WO-2026-{uuid.uuid4().hex[:4].upper()}"
    work_order = WorkOrder(
        work_order_id=work_order_id,
        title=request.title,
        description=request.description,
        building=request.building,
        floor=request.floor,
        room=request.room,
        requester_name=request.requester_name,
        requester_email=request.requester_email,
        asset_id=request.asset_id,
        status=WorkOrderStatus.SUBMITTED,
        created_at=datetime.now().isoformat(),
    )

    # ---- Configure LLM ----
    # Using the model specified in environment variables
    model_name = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")

    # ---- Create Agents ----
    # Each agent gets only the tools it needs (principle of least privilege)
    intake_agent = create_intake_agent(llm=model_name)
    intake_agent.tools = [lookup_assets_in_building_tool, lookup_asset_tool]

    triage_agent = create_triage_agent(llm=model_name)
    triage_agent.tools = [lookup_asset_tool]

    planning_agent = create_planning_agent(llm=model_name)
    planning_agent.tools = [
        get_maintenance_history_tool,
        find_available_technicians_tool,
        get_parts_inventory_tool,
        lookup_asset_tool,
    ]

    knowledge_agent = create_knowledge_agent(llm=model_name)
    knowledge_agent.tools = [search_maintenance_docs_tool, get_document_list_tool]

    compliance_agent = create_compliance_agent(llm=model_name)
    compliance_agent.tools = [search_maintenance_docs_tool]

    reporting_agent = create_reporting_agent(llm=model_name)
    # Reporting agent doesn't need tools. It synthesizes from context.

    # ---- Create Tasks ----
    # Tasks are created with the current work order data
    # Each task builds on what previous agents determined
    wo_data = work_order.model_dump()

    intake_task = create_intake_task(intake_agent, wo_data)
    triage_task = create_triage_task(triage_agent, wo_data)
    planning_task = create_planning_task(planning_agent, wo_data)
    knowledge_task = create_knowledge_task(knowledge_agent, wo_data)
    compliance_task = create_compliance_task(compliance_agent, wo_data)
    reporting_task = create_reporting_task(reporting_agent, wo_data)

    # ---- Build and Run Crew ----
    # Sequential process: each task runs after the previous one completes
    # The output of each task is available to subsequent agents as context
    crew = Crew(
        agents=[
            intake_agent,
            triage_agent,
            planning_agent,
            knowledge_agent,
            compliance_agent,
            reporting_agent,
        ],
        tasks=[
            intake_task,
            triage_task,
            planning_task,
            knowledge_task,
            compliance_task,
            reporting_task,
        ],
        process=Process.sequential,
        verbose=True,
    )

    print(f"\n{'='*60}")
    print(f"Processing Work Order: {work_order_id}")
    print(f"Title: {work_order.title}")
    print(f"{'='*60}\n")

    # Run the crew
    result = crew.kickoff()

    # ---- Parse Results and Update Work Order ----
    # The crew result contains the combined output of all agents.
    # We parse key fields and update the work order.
    result_text = str(result)

    # Update work order with parsed results
    # In production, you'd use structured outputs from each agent.
    # For this demo, we extract key information from the combined output.
    work_order = _parse_crew_output(work_order, result_text, governance)

    # ---- Governance Evaluation ----
    # This is where the governance-first approach kicks in.
    # The engine evaluates all agent decisions and determines
    # if human review is needed.
    work_order = governance.evaluate(work_order)

    # ---- Save to Database ----
    save_work_order(work_order.model_dump())

    print(f"\n{'='*60}")
    print(f"Work Order {work_order_id} Processing Complete")
    print(f"Status: {work_order.status}")
    print(f"Requires Human Review: {work_order.requires_human_review}")
    if work_order.escalation_reason:
        print(f"Escalation Reason: {work_order.escalation_reason}")
    print(f"{'='*60}\n")

    return work_order


def _parse_crew_output(
    work_order: WorkOrder,
    result_text: str,
    governance: GovernanceEngine,
) -> WorkOrder:
    """
    Parse the crew's combined output and update the work order.
    
    This function extracts key decisions from the agent outputs
    and logs them to the governance audit trail.
    
    In a production system, you'd use CrewAI's structured output
    feature or Pydantic output models. For this educational demo,
    we use a simpler parsing approach with sensible defaults.
    """
    result_lower = result_text.lower()

    # ---- Parse Priority ----
    if "critical" in result_lower:
        work_order.priority = "critical"
    elif "high" in result_lower:
        work_order.priority = "high"
    elif "medium" in result_lower:
        work_order.priority = "medium"
    else:
        work_order.priority = "low"

    governance.log_decision(
        work_order.work_order_id,
        "Triage Agent",
        "priority_assignment",
        work_order.priority,
        f"Assigned based on crew analysis of: {work_order.title}",
        0.8,
        ["work_order_description", "asset_data"],
    )

    # ---- Parse Trade ----
    trades = ["hvac", "electrical", "plumbing", "elevator", "fire_safety",
              "carpentry", "roofing", "janitorial", "grounds", "painting"]
    for trade in trades:
        if trade in result_lower:
            work_order.trade_required = trade
            break
    if not work_order.trade_required:
        work_order.trade_required = "general"

    # ---- Parse Cost Estimate ----
    import re
    cost_match = re.search(r'\$[\d,]+(?:\.\d{2})?', result_text)
    if cost_match:
        cost_str = cost_match.group().replace('$', '').replace(',', '')
        try:
            work_order.estimated_cost = float(cost_str)
        except ValueError:
            work_order.estimated_cost = 500.0  # Default estimate
    else:
        work_order.estimated_cost = 500.0

    governance.log_decision(
        work_order.work_order_id,
        "Planning Agent",
        "cost_estimate",
        f"${work_order.estimated_cost:,.2f}",
        "Cost estimated based on labor, parts, and historical data",
        0.75,
        ["maintenance_history", "parts_inventory"],
    )

    # ---- Parse Recommendation ----
    if "replace" in result_lower and "recommend" in result_lower:
        work_order.recommendation = "Replace: Based on recurring failure patterns and cost analysis"
    else:
        work_order.recommendation = "Repair: Standard maintenance procedure"

    if "replace" in (work_order.recommendation or "").lower():
        governance.log_decision(
            work_order.work_order_id,
            "Planning Agent",
            "replacement_recommendation",
            "replace",
            "Recurring failures suggest replacement is more cost-effective",
            0.7,
            ["maintenance_history", "asset_age", "total_repair_costs"],
        )

    # ---- Parse Safety Requirements ----
    safety_items = []
    if "ppe" in result_lower or "personal protective" in result_lower:
        safety_items.append("Appropriate PPE required")
    if "lockout" in result_lower or "loto" in result_lower:
        safety_items.append("Lockout/Tagout (LOTO) procedures required")
    if "permit" in result_lower:
        work_order.requires_permit = True
        safety_items.append("Work permit required")
    if "confined space" in result_lower:
        safety_items.append("Confined space entry procedures required")
    if "refrigerant" in result_lower:
        safety_items.append("EPA-certified refrigerant handling required")

    work_order.safety_requirements = safety_items if safety_items else None

    # ---- Parse Compliance Notes ----
    if "compliance" in result_lower or "regulation" in result_lower or "code" in result_lower:
        work_order.compliance_notes = "Compliance requirements identified. See detailed analysis."
    
    # ---- Set Summary ----
    # Use the last portion of the result (Reporting Agent output)
    work_order.summary = result_text[-2000:] if len(result_text) > 2000 else result_text

    # ---- Set Confidence Score ----
    # Average confidence based on parsed indicators
    confidence = 0.8
    if "uncertain" in result_lower or "unsure" in result_lower:
        confidence -= 0.2
    if "recurring" in result_lower or "pattern" in result_lower:
        confidence -= 0.05  # Complex cases are inherently less certain
    if work_order.requires_permit:
        confidence -= 0.05  # Permit work adds complexity
    work_order.confidence_score = max(0.3, min(1.0, confidence))

    work_order.status = WorkOrderStatus.PLANNED
    work_order.updated_at = datetime.now().isoformat()

    return work_order
