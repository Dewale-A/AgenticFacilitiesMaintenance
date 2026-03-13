"""
============================================================
Governance Engine
============================================================
This is the policy enforcement layer. It sits between the agents
and the final output, evaluating every decision against a set
of configurable rules.

Think of it as the "compliance officer" for the AI system.
Before any work order gets approved, it passes through here.

The engine checks:
  1. Is the estimated cost above the threshold? -> Human review
  2. Is the priority critical? -> Human confirmation
  3. Is the agent confidence too low? -> Human review
  4. Is equipment replacement recommended? -> Human sign-off
  5. Are there compliance/safety flags? -> Mandatory review

This is the GOVERNANCE-FIRST approach in practice:
  - Agents do the analysis
  - The governance engine decides if a human needs to weigh in
  - Nothing leaves the system without passing policy checks

The GovernancePolicy is configurable, so organizations can dial
the level of human involvement up or down based on their risk
tolerance. A new deployment might start conservative (low thresholds)
and gradually increase agent autonomy as trust builds.
============================================================
"""

import uuid
from datetime import datetime
from src.models.schemas import (
    WorkOrder,
    GovernancePolicy,
    AgentDecision,
    HumanReview,
    AuditLogEntry,
    Priority,
    EscalationReason,
    WorkOrderStatus,
    ReviewStatus,
)
from src.data.database import (
    save_agent_decision,
    save_audit_log,
    save_work_order,
    get_connection,
)


class GovernanceEngine:
    """
    Central governance controller for the maintenance system.
    
    Usage:
        engine = GovernanceEngine()
        
        # Log every agent decision
        engine.log_decision(work_order_id, "Triage Agent", "priority_assignment",
                           "high", "Multiple indicators suggest urgency", 0.85)
        
        # After all agents have processed, evaluate the work order
        work_order = engine.evaluate(work_order)
        
        # If work_order.requires_human_review is True, it's been escalated
        # If False, it's been auto-approved
    """

    def __init__(self, policy: GovernancePolicy = None):
        """
        Initialize with a governance policy.
        If none provided, uses sensible defaults from the GovernancePolicy model.
        """
        self.policy = policy or GovernancePolicy()

    def log_decision(
        self,
        work_order_id: str,
        agent_name: str,
        decision_type: str,
        decision_value: str,
        reasoning: str,
        confidence: float,
        data_sources: list[str] = None,
    ) -> AgentDecision:
        """
        Record an agent's decision in the audit trail.
        
        This should be called by each agent after it makes a decision.
        It creates a permanent, queryable record of:
          - Who decided (agent_name)
          - What they decided (decision_type + decision_value)
          - Why they decided it (reasoning)
          - How confident they were (confidence)
          - What data they used (data_sources)
        
        Args:
            work_order_id: The work order this decision relates to
            agent_name: Name of the agent making the decision
            decision_type: Category of decision (e.g., "priority_assignment")
            decision_value: The actual decision (e.g., "high")
            reasoning: Natural language explanation
            confidence: Float between 0.0 and 1.0
            data_sources: List of data sources consulted
            
        Returns:
            The created AgentDecision record
        """
        decision = AgentDecision(
            decision_id=f"DEC-{uuid.uuid4().hex[:8]}",
            work_order_id=work_order_id,
            agent_name=agent_name,
            decision_type=decision_type,
            decision_value=decision_value,
            reasoning=reasoning,
            confidence=confidence,
            data_sources=data_sources or [],
        )

        # Persist to database
        save_agent_decision(decision.model_dump())

        # Also log to the chronological audit log
        self._log_event(
            work_order_id=work_order_id,
            event_type="agent_decision",
            event_detail=f"{agent_name} decided {decision_type}={decision_value} (confidence: {confidence:.2f})",
            actor=agent_name,
        )

        return decision

    def evaluate(self, work_order: WorkOrder) -> WorkOrder:
        """
        Evaluate a completed work order against governance policies.
        
        This is the main governance check. After all agents have
        processed the work order, this method determines whether
        it can be auto-approved or needs human review.
        
        The evaluation checks policies IN ORDER OF SEVERITY:
          1. Critical priority -> always escalate
          2. High cost -> escalate for budget approval
          3. Equipment replacement -> escalate for sign-off
          4. Low confidence -> escalate for verification
          5. Compliance flags -> escalate for safety review
        
        If ANY check triggers, the work order is escalated.
        Multiple triggers are recorded (worst one becomes primary reason).
        
        Args:
            work_order: The fully processed work order
            
        Returns:
            Updated work order with governance fields set
        """
        escalation_reasons = []

        # ---- Check 1: Critical Priority ----
        # Safety-related work always needs a human to confirm.
        # An AI misclassifying something as "medium" when it's actually
        # dangerous could have real consequences.
        if (
            self.policy.require_review_for_critical
            and work_order.priority == Priority.CRITICAL
        ):
            escalation_reasons.append(EscalationReason.CRITICAL_PRIORITY)
            self._log_event(
                work_order.work_order_id,
                "governance_check",
                "Critical priority detected. Human confirmation required.",
                "Governance Engine",
            )

        # ---- Check 2: Cost Threshold ----
        # High-cost work needs budget approval. The threshold is
        # configurable so organizations can set their own comfort level.
        if (
            work_order.estimated_cost
            and work_order.estimated_cost > self.policy.cost_threshold
        ):
            escalation_reasons.append(EscalationReason.HIGH_COST)
            self._log_event(
                work_order.work_order_id,
                "governance_check",
                f"Estimated cost ${work_order.estimated_cost:.2f} exceeds threshold ${self.policy.cost_threshold:.2f}",
                "Governance Engine",
            )

        # ---- Check 3: Equipment Replacement ----
        # Recommending replacement of a major asset is a significant
        # capital decision that should involve human judgment.
        if (
            self.policy.require_review_for_replacement
            and work_order.recommendation
            and "replace" in work_order.recommendation.lower()
        ):
            escalation_reasons.append(EscalationReason.EQUIPMENT_REPLACEMENT)
            self._log_event(
                work_order.work_order_id,
                "governance_check",
                "Equipment replacement recommended. Human sign-off required.",
                "Governance Engine",
            )

        # ---- Check 4: Low Confidence ----
        # If the agents weren't confident in their analysis,
        # a human should verify before proceeding.
        if (
            work_order.confidence_score
            and work_order.confidence_score < self.policy.confidence_threshold
        ):
            escalation_reasons.append(EscalationReason.LOW_CONFIDENCE)
            self._log_event(
                work_order.work_order_id,
                "governance_check",
                f"Confidence score {work_order.confidence_score:.2f} below threshold {self.policy.confidence_threshold:.2f}",
                "Governance Engine",
            )

        # ---- Check 5: Compliance Flags ----
        # Any compliance or safety notes trigger review.
        if work_order.requires_permit or (
            work_order.safety_requirements and len(work_order.safety_requirements) > 0
        ):
            escalation_reasons.append(EscalationReason.COMPLIANCE_FLAG)
            self._log_event(
                work_order.work_order_id,
                "governance_check",
                "Compliance or safety requirements detected. Review required.",
                "Governance Engine",
            )

        # ---- Apply Governance Decision ----
        if escalation_reasons:
            # Escalate: set the primary reason (first/most severe)
            work_order.requires_human_review = True
            work_order.escalation_reason = escalation_reasons[0]
            work_order.status = WorkOrderStatus.PENDING_HUMAN_REVIEW

            # Create a human review record
            self._create_review(work_order, escalation_reasons[0])

            self._log_event(
                work_order.work_order_id,
                "governance_escalation",
                f"Escalated for human review. Reasons: {[r.value for r in escalation_reasons]}",
                "Governance Engine",
            )
        else:
            # Auto-approve: all checks passed
            work_order.requires_human_review = False
            work_order.status = WorkOrderStatus.APPROVED

            self._log_event(
                work_order.work_order_id,
                "governance_auto_approve",
                "All governance checks passed. Work order auto-approved.",
                "Governance Engine",
            )

        return work_order

    def process_human_review(
        self,
        work_order_id: str,
        approved: bool,
        reviewer_name: str,
        notes: str = None,
    ) -> dict:
        """
        Process a human reviewer's decision on an escalated work order.
        
        This completes the human-in-the-loop cycle:
          1. Agent recommended something
          2. Governance engine escalated it
          3. Human reviews and approves/rejects
          4. This method records the decision and updates the work order
        
        Args:
            work_order_id: The work order being reviewed
            approved: True if human approves, False if rejected
            reviewer_name: Who made the decision
            notes: Optional explanation of the decision
            
        Returns:
            Updated review record
        """
        conn = get_connection()
        now = datetime.now().isoformat()

        # Update the review record
        status = "approved" if approved else "rejected"
        conn.execute(
            """UPDATE human_reviews 
               SET status = ?, reviewer_name = ?, reviewer_notes = ?, reviewed_at = ?
               WHERE work_order_id = ? AND status = 'pending'""",
            (status, reviewer_name, notes, now, work_order_id)
        )

        # Update the work order status
        wo_status = WorkOrderStatus.APPROVED.value if approved else WorkOrderStatus.REJECTED.value
        conn.execute(
            "UPDATE work_orders SET status = ?, updated_at = ? WHERE work_order_id = ?",
            (wo_status, now, work_order_id)
        )

        conn.commit()
        conn.close()

        # Log the human decision
        action = "approved" if approved else "rejected"
        self._log_event(
            work_order_id,
            "human_review",
            f"Work order {action} by {reviewer_name}. Notes: {notes or 'None'}",
            reviewer_name,
        )

        return {"work_order_id": work_order_id, "status": status, "reviewer": reviewer_name}

    def _create_review(self, work_order: WorkOrder, reason: EscalationReason):
        """Create a pending human review record in the database."""
        conn = get_connection()
        review_id = f"REV-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO human_reviews 
               (review_id, work_order_id, escalation_reason, agent_recommendation, 
                status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (
                review_id,
                work_order.work_order_id,
                reason.value,
                work_order.plan or work_order.recommendation or "See work order details",
                datetime.now().isoformat(),
            )
        )
        conn.commit()
        conn.close()

    def _log_event(self, work_order_id: str, event_type: str, event_detail: str, actor: str):
        """Add an entry to the audit log."""
        entry = {
            "entry_id": f"LOG-{uuid.uuid4().hex[:8]}",
            "work_order_id": work_order_id,
            "event_type": event_type,
            "event_detail": event_detail,
            "actor": actor,
            "timestamp": datetime.now().isoformat(),
        }
        save_audit_log(entry)
