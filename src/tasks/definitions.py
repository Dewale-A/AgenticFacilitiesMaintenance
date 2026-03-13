"""
============================================================
Task Definitions
============================================================
Tasks define WHAT each agent should do with a specific work order.
While agents define WHO does the work (role, goal, backstory),
tasks define the specific instructions for THIS work order.

Each task includes:
  - description: Detailed instructions including the work order data
  - expected_output: What format the agent should return
  - agent: Which agent performs this task

The tasks are created dynamically for each work order because
the instructions need to include the specific work order details.

Sequential Flow:
  intake_task -> triage_task -> planning_task -> knowledge_task 
              -> compliance_task -> reporting_task
============================================================
"""

from crewai import Task


def create_intake_task(agent, work_order_data: dict) -> Task:
    """
    Task: Validate and register the incoming maintenance request.
    
    The intake task receives the raw request from the API and:
      1. Assigns a work order ID
      2. Identifies the related asset (if possible)
      3. Validates that the description is actionable
      4. Formats the data for downstream agents
    """
    return Task(
        description=f"""
        Process this incoming maintenance request:
        
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Building: {work_order_data.get('building', 'N/A')}
        Floor: {work_order_data.get('floor', 'N/A')}
        Room: {work_order_data.get('room', 'N/A')}
        Requester: {work_order_data.get('requester_name', 'N/A')}
        Asset ID (if provided): {work_order_data.get('asset_id', 'Not specified')}
        
        Your tasks:
        1. If no asset_id was provided, use the building/floor/room info to identify
           the most likely related asset from the CMMS database
        2. Validate that the description contains enough detail to act on
        3. Assign a work order ID in format WO-2026-XXXX (use a random 4-digit number)
        4. Summarize the request in a standardized format
        
        Use the lookup_assets_in_building tool to find assets if needed.
        """,
        expected_output="""
        A JSON-formatted response with:
        - work_order_id: The assigned ID
        - asset_id: The identified or provided asset ID
        - validated_description: The standardized request description
        - intake_notes: Any observations about the request
        """,
        agent=agent,
    )


def create_triage_task(agent, work_order_data: dict) -> Task:
    """
    Task: Classify priority and required trade.
    
    The triage task must provide REASONING for every decision
    because this feeds directly into the governance audit trail.
    A priority decision without reasoning is useless for auditing.
    """
    return Task(
        description=f"""
        Triage this maintenance work order:
        
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Building: {work_order_data.get('building', 'N/A')}
        Asset ID: {work_order_data.get('asset_id', 'N/A')}
        
        Classify the work order:
        1. PRIORITY: Assign one of: critical, high, medium, low
           - critical: Safety hazard or building unusable
           - high: Significant impact, needs attention within 24 hours
           - medium: Standard maintenance, can be scheduled within a week
           - low: Cosmetic or minor, schedule at convenience
        
        2. TRADE REQUIRED: Identify the maintenance trade needed:
           hvac, electrical, plumbing, carpentry, painting, roofing,
           janitorial, grounds, elevator, fire_safety, general
        
        3. REASONING: Explain WHY you assigned this priority. This is
           mandatory because it feeds into the governance audit trail.
        
        4. CONFIDENCE: Rate your confidence in this classification (0.0 to 1.0).
           If below 0.7, the system will escalate to human review.
        
        Use the lookup_asset tool to get asset details if an asset_id is provided.
        """,
        expected_output="""
        A JSON-formatted response with:
        - priority: The assigned priority level
        - trade_required: The maintenance trade needed
        - triage_reasoning: Detailed explanation of the classification
        - confidence: Confidence score between 0.0 and 1.0
        """,
        agent=agent,
    )


def create_planning_task(agent, work_order_data: dict) -> Task:
    """
    Task: Create the maintenance execution plan.
    
    This is the most complex task. The agent needs to:
      - Analyze maintenance history for patterns
      - Estimate costs
      - Make repair vs. replace recommendations
      - Assign a technician
      - Schedule the work
      
    All of these decisions get logged to the audit trail.
    """
    return Task(
        description=f"""
        Create a maintenance plan for this work order:
        
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Building: {work_order_data.get('building', 'N/A')}
        Asset ID: {work_order_data.get('asset_id', 'N/A')}
        Priority: {work_order_data.get('priority', 'N/A')}
        Trade Required: {work_order_data.get('trade_required', 'N/A')}
        
        Your tasks:
        1. HISTORY ANALYSIS: Look up the maintenance history for this asset.
           Check for recurring issues. If there have been 3+ repairs in the
           last 12 months, seriously consider recommending replacement.
        
        2. COST ESTIMATE: Estimate the total cost including:
           - Labor (hours x $75/hr for standard, $120/hr for specialized)
           - Parts (check inventory for availability and pricing)
           - Contractor costs if needed
        
        3. RECOMMENDATION: Should this be repaired or replaced?
           Consider: asset age, remaining lifespan, repair frequency,
           cumulative repair costs vs. replacement cost.
        
        4. TECHNICIAN ASSIGNMENT: Find an available technician with the
           right trade skills. Prefer the one with lowest workload.
        
        5. SCHEDULING: Suggest a date based on priority:
           - Critical: Today
           - High: Within 24 hours
           - Medium: Within 1 week
           - Low: Within 2 weeks
        
        6. CONFIDENCE: Rate your overall confidence in this plan (0.0 to 1.0).
        
        Use these tools:
        - get_maintenance_history: To analyze past repairs
        - find_available_technicians: To find the right person
        - get_parts_inventory: To check parts availability
        - lookup_asset: To get asset details (age, lifespan, condition)
        """,
        expected_output="""
        A JSON-formatted response with:
        - estimated_cost: Dollar amount
        - plan: Step-by-step maintenance plan
        - recommendation: "repair" or "replace" with justification
        - assigned_technician: Technician ID
        - scheduled_date: Planned date (YYYY-MM-DD)
        - confidence: Overall confidence score (0.0 to 1.0)
        - cost_breakdown: Labor, parts, and other costs itemized
        """,
        agent=agent,
    )


def create_knowledge_task(agent, work_order_data: dict) -> Task:
    """
    Task: Retrieve relevant maintenance procedures.
    
    The Knowledge Agent searches the documentation library
    for procedures, specs, and safety info relevant to this work.
    """
    return Task(
        description=f"""
        Find relevant maintenance documentation for this work order:
        
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Asset Category: {work_order_data.get('asset_category', 'N/A')}
        Trade: {work_order_data.get('trade_required', 'N/A')}
        Plan: {work_order_data.get('plan', 'N/A')}
        
        Your tasks:
        1. Search the maintenance documentation for relevant procedures
        2. Find troubleshooting guides if this is a repair
        3. Identify any specific manufacturer recommendations
        4. Note any safety procedures that apply to this type of work
        
        Use the search_maintenance_docs tool with relevant queries.
        Try multiple searches with different terms to get comprehensive results.
        
        For example, if this is an HVAC issue, search for:
        - The specific symptom or problem
        - General HVAC maintenance procedures
        - Safety requirements for HVAC work
        """,
        expected_output="""
        A list of relevant procedures with:
        - procedure_name: Name of the procedure
        - source_document: Which document it came from
        - key_steps: The relevant steps or information
        - safety_notes: Any safety-related information found
        """,
        agent=agent,
    )


def create_compliance_task(agent, work_order_data: dict) -> Task:
    """
    Task: Check safety and regulatory compliance.
    
    This is the governance gatekeeper. The Compliance Agent must
    flag anything that requires permits, special safety measures,
    or regulatory notifications.
    """
    return Task(
        description=f"""
        Review this maintenance plan for safety and compliance:
        
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Asset Category: {work_order_data.get('asset_category', 'N/A')}
        Trade: {work_order_data.get('trade_required', 'N/A')}
        Plan: {work_order_data.get('plan', 'N/A')}
        Recommendation: {work_order_data.get('recommendation', 'N/A')}
        
        Check for:
        1. SAFETY REQUIREMENTS: What PPE is needed? Is lockout/tagout required?
           Are there confined space concerns? Fall protection needs?
        
        2. PERMITS: Does this work require any permits?
           - Hot work permit (welding, soldering near combustibles)
           - Confined space entry permit
           - Excavation permit
           - Electrical work permit for energized work
        
        3. REGULATORY COMPLIANCE:
           - OSHA requirements for this type of work
           - Fire code requirements (especially for fire safety equipment)
           - Elevator code (ASME A17.1) for elevator work
           - EPA requirements for refrigerant handling
           - Environmental requirements for waste disposal
        
        4. DOCUMENTATION: What records must be kept?
           - Inspection records and retention periods
           - Regulatory filings required
           - Incident reports if applicable
        
        Search the safety and compliance documentation for relevant requirements.
        When in doubt, flag for human review. Safety is never optional.
        """,
        expected_output="""
        A compliance review with:
        - compliance_notes: Summary of compliance requirements
        - safety_requirements: List of specific safety measures needed
        - requires_permit: true/false (and which permits)
        - regulatory_notes: Any regulatory requirements that apply
        - documentation_requirements: What records must be kept
        """,
        agent=agent,
    )


def create_reporting_task(agent, work_order_data: dict) -> Task:
    """
    Task: Generate the executive summary.
    
    The final agent consolidates everything into a readable
    report that a facilities manager can quickly review.
    """
    return Task(
        description=f"""
        Generate an executive summary for this completed work order analysis:
        
        Work Order ID: {work_order_data.get('work_order_id', 'N/A')}
        Title: {work_order_data.get('title', 'N/A')}
        Description: {work_order_data.get('description', 'N/A')}
        Priority: {work_order_data.get('priority', 'N/A')}
        Trade: {work_order_data.get('trade_required', 'N/A')}
        Estimated Cost: ${work_order_data.get('estimated_cost', 0):,.2f}
        Plan: {work_order_data.get('plan', 'N/A')}
        Recommendation: {work_order_data.get('recommendation', 'N/A')}
        Safety Requirements: {work_order_data.get('safety_requirements', 'N/A')}
        Compliance Notes: {work_order_data.get('compliance_notes', 'N/A')}
        Confidence Score: {work_order_data.get('confidence_score', 'N/A')}
        
        Create a clear, concise summary that includes:
        1. ISSUE: What's the problem (one sentence)
        2. RECOMMENDATION: What should be done
        3. COST: Estimated cost and breakdown
        4. RISK: Any safety or compliance concerns
        5. TIMELINE: When the work should be performed
        6. HUMAN REVIEW: Whether this needs human approval and why
        
        Write for a busy facilities manager. No jargon. No fluff.
        """,
        expected_output="""
        A clear executive summary covering all six points above,
        formatted for easy reading by a facilities manager.
        """,
        agent=agent,
    )
