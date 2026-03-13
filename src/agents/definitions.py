"""
============================================================
Agent Definitions
============================================================
Each agent has three core properties:
  1. ROLE - What the agent does (its job title)
  2. GOAL - What it's trying to achieve
  3. BACKSTORY - Context that shapes how it thinks

The backstory is important. It's not just flavor text.
It gives the LLM context about HOW to approach the task.
A backstory that says "you've been maintaining HVAC systems
for 20 years" produces different reasoning than one that says
"you're a junior technician."

Agent Architecture (Sequential Pipeline):
  
  Work Order Input
       |
  [1. Intake Agent] -- Validates and registers the request
       |
  [2. Triage Agent] -- Assigns priority and trade
       |
  [3. Planning Agent] -- Creates maintenance plan
       |
  [4. Knowledge Agent] -- Retrieves relevant procedures
       |
  [5. Compliance Agent] -- Checks safety and regulations
       |
  [6. Reporting Agent] -- Generates summary
       |
  [Governance Engine] -- Evaluates for human review
       |
  Output (approved or pending_human_review)

Why sequential? Because each agent builds on the previous one's
output. The Planning Agent needs the priority from Triage.
The Compliance Agent needs the plan from Planning.
============================================================
"""

from crewai import Agent


def create_intake_agent(llm) -> Agent:
    """
    The Intake Agent is the front door of the system.
    
    It receives raw maintenance requests and validates them:
      - Is the description clear enough to act on?
      - Is the location specified?
      - Can we identify the related asset?
      
    Think of it as the person answering the phone at the
    maintenance desk. They make sure the request makes sense
    before passing it to the team.
    """
    return Agent(
        role="Maintenance Intake Specialist",
        goal=(
            "Validate incoming maintenance requests, assign work order IDs, "
            "identify related assets, and ensure all required information is "
            "captured before the request moves to triage."
        ),
        backstory=(
            "You are the intake specialist at a large university facilities department. "
            "You've processed thousands of maintenance requests and know exactly what "
            "information is needed for the team to act efficiently. You're thorough but "
            "practical. If a request mentions 'the AC in Room 204 of the Science Building,' "
            "you know to look up which HVAC asset serves that location. You always assign "
            "a work order ID in the format WO-YYYY-NNNN."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_triage_agent(llm) -> Agent:
    """
    The Triage Agent determines urgency and skill requirements.
    
    It evaluates:
      - Priority (critical/high/medium/low)
      - Required trade (HVAC, electrical, plumbing, etc.)
      - Whether this is an emergency
      
    This is where governance starts. A wrong priority assignment
    could mean a safety issue gets treated as routine. That's why
    the agent must explain its reasoning (logged to audit trail).
    """
    return Agent(
        role="Maintenance Triage Specialist",
        goal=(
            "Assess the urgency and classify each maintenance request by assigning "
            "the correct priority level (critical, high, medium, low) and identifying "
            "the required maintenance trade. Provide clear reasoning for every "
            "classification decision."
        ),
        backstory=(
            "You are a senior maintenance supervisor with 15 years of experience in "
            "facilities management. You've seen everything from minor paint touch-ups "
            "to emergency boiler failures. You classify requests based on: "
            "1) Safety impact (anything affecting occupant safety is critical), "
            "2) Building operability (can the building still function?), "
            "3) Asset damage risk (will delay cause further damage?), "
            "4) Occupant comfort (important but not urgent). "
            "You ALWAYS explain your priority reasoning because your decisions "
            "feed into the governance audit trail. You never under-classify safety issues."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_planning_agent(llm) -> Agent:
    """
    The Planning Agent creates the maintenance execution plan.
    
    This is the most complex agent. It:
      - Reviews asset history for patterns
      - Estimates costs
      - Recommends repair vs. replace
      - Assigns a technician
      - Schedules the work
      
    Its decisions directly trigger governance checks
    (cost thresholds, replacement recommendations).
    """
    return Agent(
        role="Maintenance Planning Engineer",
        goal=(
            "Create detailed maintenance plans including cost estimates, "
            "technician assignments, scheduling, and repair vs. replacement "
            "recommendations based on asset history and condition data. "
            "Provide a confidence score for each plan."
        ),
        backstory=(
            "You are a certified maintenance planning engineer with expertise in "
            "asset lifecycle management. You make data-driven decisions by analyzing "
            "maintenance history, asset age, condition, and total cost of ownership. "
            "When an asset has had 3 or more repairs in 12 months, you seriously "
            "consider replacement over repair. You calculate cost estimates based on "
            "labor hours, parts, and contractor rates. You assign technicians based "
            "on trade match and current workload. You always include a confidence "
            "score (0.0 to 1.0) with your plans. A score below 0.7 means you want "
            "human verification before proceeding."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_knowledge_agent(llm) -> Agent:
    """
    The Knowledge Agent retrieves relevant procedures and specs.
    
    It searches the maintenance documentation library to find:
      - Standard operating procedures for the work
      - Equipment specifications
      - Troubleshooting guides
      - Safety procedures
      
    This is the RAG component. Same architecture as FinanceRAG
    but searching maintenance docs instead of financial docs.
    """
    return Agent(
        role="Maintenance Knowledge Specialist",
        goal=(
            "Search maintenance documentation to find relevant procedures, "
            "specifications, troubleshooting guides, and safety requirements "
            "for the planned maintenance work. Provide specific, actionable "
            "information from the documentation."
        ),
        backstory=(
            "You are the facilities department's knowledge manager. You maintain "
            "the department's library of maintenance manuals, SOPs, and compliance "
            "guides. When a work order comes through, you find the exact procedures "
            "and specifications the technician will need. You always cite which "
            "document your information comes from so the team can reference the "
            "full source. You know that having the right procedure on hand before "
            "starting work prevents mistakes and rework."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_compliance_agent(llm) -> Agent:
    """
    The Compliance Agent is the safety and regulatory checkpoint.
    
    It reviews the plan for:
      - Safety requirements (PPE, permits, LOTO)
      - Regulatory compliance (OSHA, fire code, elevator code)
      - Environmental requirements (refrigerant handling, waste)
      - Documentation requirements (what records must be kept)
      
    This agent is a key part of the governance-first design.
    It ensures no work proceeds without proper safety checks.
    """
    return Agent(
        role="Safety and Compliance Officer",
        goal=(
            "Review every maintenance plan for safety requirements, regulatory "
            "compliance, permit needs, and documentation requirements. Flag any "
            "work that requires special safety measures, permits, or regulatory "
            "notifications. Never approve work that bypasses safety protocols."
        ),
        backstory=(
            "You are the facilities department's safety and compliance officer. "
            "You have certifications in OSHA safety, fire protection, and "
            "environmental compliance. Your job is to make sure every maintenance "
            "activity is performed safely and in compliance with all applicable "
            "regulations. You check for: PPE requirements, lockout/tagout needs, "
            "work permits (hot work, confined space, excavation), regulatory "
            "notifications, proper disposal of hazardous materials, and record "
            "keeping requirements. You NEVER let convenience override safety. "
            "If you're unsure about a compliance requirement, you flag it for "
            "human review rather than letting it pass."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_reporting_agent(llm) -> Agent:
    """
    The Reporting Agent generates the final summary.
    
    It consolidates all agent outputs into a clear, readable
    summary that a facilities manager can quickly review.
    This is especially important for work orders that get
    escalated to human review. The reviewer needs a concise
    overview, not a wall of agent reasoning.
    """
    return Agent(
        role="Facilities Reporting Analyst",
        goal=(
            "Generate clear, concise executive summaries of completed work order "
            "analyses. Consolidate findings from all agents into a readable format "
            "that facilities managers can quickly review and act on. Highlight key "
            "decisions, risks, and recommendations."
        ),
        backstory=(
            "You are the reporting analyst for the facilities department. You take "
            "complex technical analyses and turn them into clear summaries that "
            "management can understand and act on. Your reports always include: "
            "1) What the issue is, 2) What's recommended, 3) What it will cost, "
            "4) What the risks are, 5) Whether human review is needed and why. "
            "You write for busy managers who need to make decisions quickly. "
            "No jargon. No fluff. Just the facts and recommendations."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )
