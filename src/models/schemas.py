"""
============================================================
Data Models (Pydantic Schemas)
============================================================
These models define the shape of every piece of data flowing
through the system. Using Pydantic ensures:
  1. Data validation at every boundary (API input, agent output)
  2. Clear documentation of what each field means
  3. Type safety across the entire application

Think of these as contracts. Agents, tools, and API endpoints
all agree on these structures, so nothing gets lost or misunderstood.
============================================================
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# ENUMS - Fixed categories used throughout the system
# ============================================================
# Enums prevent typos and enforce consistency.
# Instead of passing "high" vs "High" vs "HIGH" around,
# everyone uses Priority.HIGH.

class Priority(str, Enum):
    """
    Work order priority levels.
    CRITICAL = safety hazard or building unusable (triggers HITL review)
    HIGH     = significant impact but not dangerous
    MEDIUM   = standard maintenance, can wait a day or two
    LOW      = cosmetic or minor, scheduled at convenience
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkOrderStatus(str, Enum):
    """
    Lifecycle of a work order through the system.
    
    Flow: submitted -> triaged -> planned -> approved -> in_progress -> completed
                                         \-> pending_human_review (if HITL triggered)
                                         \-> rejected (if human rejects)
    """
    SUBMITTED = "submitted"           # Just received, not yet processed
    TRIAGED = "triaged"               # Priority and trade assigned
    PLANNED = "planned"               # Schedule and approach determined
    PENDING_HUMAN_REVIEW = "pending_human_review"  # Waiting for human approval
    APPROVED = "approved"             # Human approved (or auto-approved)
    IN_PROGRESS = "in_progress"       # Technician working on it
    COMPLETED = "completed"           # Work finished
    REJECTED = "rejected"             # Human rejected the plan


class ReviewStatus(str, Enum):
    """Status of a human-in-the-loop review."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TradeType(str, Enum):
    """
    Maintenance trade categories.
    Maps to the type of technician needed for the work.
    """
    HVAC = "hvac"
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    CARPENTRY = "carpentry"
    PAINTING = "painting"
    ROOFING = "roofing"
    JANITORIAL = "janitorial"
    GROUNDS = "grounds"
    ELEVATOR = "elevator"
    FIRE_SAFETY = "fire_safety"
    GENERAL = "general"


class EscalationReason(str, Enum):
    """
    Why a work order was escalated to human review.
    Each reason maps to a governance policy rule.
    """
    HIGH_COST = "high_cost"                       # Estimated cost exceeds threshold
    CRITICAL_PRIORITY = "critical_priority"       # Safety or emergency classification
    COMPLIANCE_FLAG = "compliance_flag"            # Regulatory or safety requirement
    LOW_CONFIDENCE = "low_confidence"              # Agent wasn't sure about its decision
    EQUIPMENT_REPLACEMENT = "equipment_replacement"  # Major asset replacement recommended


# ============================================================
# CORE DATA MODELS - The main entities in the system
# ============================================================

class Asset(BaseModel):
    """
    Represents a physical asset (piece of equipment) in a facility.
    
    In a real CMMS like AiM, assets are the central concept.
    Everything revolves around tracking what equipment exists,
    where it is, what condition it's in, and when it was last serviced.
    """
    asset_id: str = Field(description="Unique identifier (e.g., 'AHU-B12-01')")
    name: str = Field(description="Human-readable name (e.g., 'Air Handling Unit 1')")
    category: str = Field(description="Equipment category (e.g., 'HVAC', 'Elevator')")
    building: str = Field(description="Building where the asset is located")
    floor: str = Field(description="Floor or zone within the building")
    room: Optional[str] = Field(default=None, description="Specific room if applicable")
    install_date: str = Field(description="When the equipment was installed (YYYY-MM-DD)")
    expected_lifespan_years: int = Field(description="Manufacturer's expected lifespan")
    last_service_date: Optional[str] = Field(default=None, description="Last maintenance date")
    condition: str = Field(default="operational", description="Current condition: operational, degraded, failed")
    warranty_expiry: Optional[str] = Field(default=None, description="Warranty expiration date")
    manufacturer: Optional[str] = Field(default=None, description="Equipment manufacturer")
    model_number: Optional[str] = Field(default=None, description="Manufacturer model number")


class Technician(BaseModel):
    """
    Represents a maintenance technician on the facilities team.
    Used by the Planning Agent to assign work based on skills and availability.
    """
    tech_id: str = Field(description="Unique technician ID")
    name: str = Field(description="Technician's full name")
    trades: list[str] = Field(description="List of qualified trades (e.g., ['hvac', 'electrical'])")
    available: bool = Field(default=True, description="Whether currently available for assignment")
    current_workload: int = Field(default=0, description="Number of active work orders assigned")


class MaintenanceRecord(BaseModel):
    """
    Historical record of past maintenance work on an asset.
    The Planning Agent uses these records to identify patterns,
    like recurring failures that suggest replacement over repair.
    """
    record_id: str = Field(description="Unique record ID")
    asset_id: str = Field(description="Which asset was serviced")
    work_order_id: str = Field(description="Related work order")
    date: str = Field(description="When the work was performed (YYYY-MM-DD)")
    description: str = Field(description="What was done")
    cost: float = Field(description="Total cost of the maintenance")
    technician_id: str = Field(description="Who performed the work")
    parts_used: list[str] = Field(default_factory=list, description="Parts consumed")


class WorkOrderCreate(BaseModel):
    """
    Input model for creating a new work order.
    This is what comes in from the API when someone submits a request.
    Notice it has fewer fields than WorkOrder: the agents fill in the rest.
    """
    title: str = Field(description="Brief description of the issue")
    description: str = Field(description="Detailed description of the problem")
    building: str = Field(description="Building where the issue is located")
    floor: str = Field(description="Floor or zone")
    room: Optional[str] = Field(default=None, description="Specific room")
    requester_name: str = Field(description="Who reported the issue")
    requester_email: Optional[str] = Field(default=None, description="Contact email")
    asset_id: Optional[str] = Field(default=None, description="Related asset ID if known")


class WorkOrder(BaseModel):
    """
    Complete work order with all fields populated by agents.
    
    A work order starts as a WorkOrderCreate (user input) and gets
    enriched by each agent in the pipeline:
      - Intake Agent: assigns work_order_id, timestamps
      - Triage Agent: sets priority and trade_required
      - Planning Agent: adds estimated_cost, assigned_technician, scheduled_date, plan
      - Knowledge Agent: adds relevant_procedures
      - Compliance Agent: adds compliance_notes, safety_requirements
      - Reporting Agent: adds summary
    """
    work_order_id: str = Field(description="System-generated unique ID (e.g., 'WO-2026-0001')")
    title: str
    description: str
    building: str
    floor: str
    room: Optional[str] = None
    requester_name: str
    requester_email: Optional[str] = None
    asset_id: Optional[str] = None

    # Populated by Triage Agent
    priority: Optional[Priority] = Field(default=None, description="Assigned by Triage Agent")
    trade_required: Optional[TradeType] = Field(default=None, description="Trade skill needed")
    triage_reasoning: Optional[str] = Field(default=None, description="Why this priority was assigned")

    # Populated by Planning Agent
    estimated_cost: Optional[float] = Field(default=None, description="Estimated cost in dollars")
    assigned_technician: Optional[str] = Field(default=None, description="Technician ID assigned")
    scheduled_date: Optional[str] = Field(default=None, description="Planned execution date")
    plan: Optional[str] = Field(default=None, description="Step-by-step maintenance plan")
    recommendation: Optional[str] = Field(default=None, description="Repair vs replace recommendation")

    # Populated by Knowledge Agent
    relevant_procedures: Optional[list[str]] = Field(default=None, description="Retrieved maintenance procedures")

    # Populated by Compliance Agent
    compliance_notes: Optional[str] = Field(default=None, description="Regulatory or safety notes")
    safety_requirements: Optional[list[str]] = Field(default=None, description="Required safety measures")
    requires_permit: Optional[bool] = Field(default=False, description="Whether a work permit is needed")

    # Populated by Reporting Agent
    summary: Optional[str] = Field(default=None, description="Executive summary of the work order")

    # System fields
    status: WorkOrderStatus = Field(default=WorkOrderStatus.SUBMITTED)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None

    # Governance fields
    confidence_score: Optional[float] = Field(default=None, description="Overall agent confidence (0.0-1.0)")
    escalation_reason: Optional[EscalationReason] = Field(default=None, description="Why it needs human review")
    requires_human_review: bool = Field(default=False, description="Whether HITL was triggered")


# ============================================================
# GOVERNANCE MODELS - Audit trail and human-in-the-loop
# ============================================================
# These models are what make this project different from a demo.
# Every decision is logged. Every escalation is tracked.
# Every human review is recorded with reasoning.

class AgentDecision(BaseModel):
    """
    Records a single decision made by an agent.
    
    This is the core of the audit trail. Every time an agent
    makes a choice (priority assignment, cost estimate, scheduling),
    it gets logged here with its reasoning and confidence level.
    
    Why this matters: In regulated environments, you need to explain
    WHY an AI made a decision, not just WHAT it decided. This model
    captures that provenance.
    """
    decision_id: str = Field(description="Unique decision ID")
    work_order_id: str = Field(description="Which work order this decision relates to")
    agent_name: str = Field(description="Which agent made the decision (e.g., 'Triage Agent')")
    decision_type: str = Field(description="What kind of decision (e.g., 'priority_assignment')")
    decision_value: str = Field(description="The actual decision (e.g., 'high')")
    reasoning: str = Field(description="Agent's explanation of why it made this decision")
    confidence: float = Field(description="How confident the agent is (0.0 to 1.0)")
    data_sources: list[str] = Field(default_factory=list, description="What data informed this decision")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class HumanReview(BaseModel):
    """
    Records a human-in-the-loop review action.
    
    When an agent escalates a decision (high cost, low confidence,
    safety concern), a human must review it. This model captures
    who reviewed it, what they decided, and why.
    """
    review_id: str = Field(description="Unique review ID")
    work_order_id: str = Field(description="Which work order is being reviewed")
    escalation_reason: EscalationReason = Field(description="Why this was escalated")
    agent_recommendation: str = Field(description="What the agent recommended")
    reviewer_name: Optional[str] = Field(default=None, description="Who performed the review")
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    reviewer_notes: Optional[str] = Field(default=None, description="Human's reasoning for their decision")
    reviewed_at: Optional[str] = Field(default=None, description="When the review was completed")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AuditLogEntry(BaseModel):
    """
    A single entry in the governance audit log.
    
    This provides a chronological record of everything that happens
    to a work order. Think of it as a tamper-evident log that an
    auditor could review to understand the full decision chain.
    """
    entry_id: str = Field(description="Unique log entry ID")
    work_order_id: str = Field(description="Related work order")
    event_type: str = Field(description="What happened (e.g., 'agent_decision', 'human_review', 'status_change')")
    event_detail: str = Field(description="Details of the event")
    actor: str = Field(description="Who/what caused the event (agent name or human name)")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class GovernancePolicy(BaseModel):
    """
    Configurable governance rules that control when HITL is triggered.
    
    These policies can be adjusted without changing code.
    A conservative organization might set low thresholds (more human review).
    A mature one might set higher thresholds (more agent autonomy).
    
    This is the "dial" between full automation and full human control.
    """
    cost_threshold: float = Field(
        default=5000.0,
        description="Work orders above this cost require human approval"
    )
    confidence_threshold: float = Field(
        default=0.7,
        description="Agent confidence below this triggers human review"
    )
    auto_approve_priorities: list[Priority] = Field(
        default=[Priority.LOW, Priority.MEDIUM],
        description="These priorities can be auto-approved without human review"
    )
    require_review_for_replacement: bool = Field(
        default=True,
        description="Equipment replacement recommendations always need human review"
    )
    require_review_for_critical: bool = Field(
        default=True,
        description="Critical priority always needs human confirmation"
    )
