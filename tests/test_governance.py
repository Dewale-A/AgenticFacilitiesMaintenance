"""
Tests for the GovernanceEngine in src/governance/engine.py.

Validates policy-based escalation, auto-approval logic, audit trail
logging, and human review processing. The governance engine is the
core policy enforcement layer, so these tests are critical.
"""

import pytest
from datetime import datetime
from src.models.schemas import (
    WorkOrder,
    WorkOrderStatus,
    Priority,
    EscalationReason,
    GovernancePolicy,
)
from src.governance.engine import GovernanceEngine


def _make_work_order(
    priority=Priority.MEDIUM,
    estimated_cost=1000.0,
    confidence=0.9,
    recommendation="Repair the unit",
    requires_permit=False,
    safety_requirements=None,
):
    """Helper: build a WorkOrder for testing the evaluate method."""
    return WorkOrder(
        work_order_id=f"WO-TEST-{datetime.now().strftime('%H%M%S%f')[:10]}",
        title="Test work order",
        description="Test description",
        building="Admin Building",
        floor="1",
        requester_name="Test User",
        priority=priority,
        trade_required="general",
        estimated_cost=estimated_cost,
        assigned_technician="TECH-001",
        scheduled_date="2026-03-20",
        plan="Step 1: Inspect. Step 2: Fix.",
        recommendation=recommendation,
        confidence_score=confidence,
        requires_permit=requires_permit,
        safety_requirements=safety_requirements,
        status=WorkOrderStatus.PLANNED,
    )


class TestEvaluateCostThreshold:
    """Verify that cost above the threshold triggers HITL."""

    def test_high_cost_triggers_hitl(self, governance_engine):
        """A work order with cost > $5,000 should be escalated."""
        wo = _make_work_order(estimated_cost=7500.0)
        result = governance_engine.evaluate(wo)
        assert result.requires_human_review is True
        assert result.status == WorkOrderStatus.PENDING_HUMAN_REVIEW
        assert result.escalation_reason == EscalationReason.HIGH_COST

    def test_below_cost_not_escalated(self, governance_engine):
        """A work order with cost < $5,000 should not trigger cost escalation."""
        wo = _make_work_order(estimated_cost=3000.0)
        result = governance_engine.evaluate(wo)
        # May still auto-approve if no other triggers
        assert result.escalation_reason != EscalationReason.HIGH_COST or result.escalation_reason is None


class TestEvaluateCriticalPriority:
    """Verify that critical priority always triggers HITL."""

    def test_critical_triggers_hitl(self, governance_engine):
        """A critical priority work order should always be escalated."""
        wo = _make_work_order(priority=Priority.CRITICAL, estimated_cost=100.0)
        result = governance_engine.evaluate(wo)
        assert result.requires_human_review is True
        assert result.status == WorkOrderStatus.PENDING_HUMAN_REVIEW


class TestEvaluateAutoApprove:
    """Verify auto-approval when all governance checks pass."""

    def test_auto_approves_clean_order(self, governance_engine):
        """A low-cost, medium-priority, high-confidence order should auto-approve."""
        wo = _make_work_order(
            priority=Priority.MEDIUM,
            estimated_cost=500.0,
            confidence=0.95,
            recommendation="Repair the unit",
            requires_permit=False,
            safety_requirements=None,
        )
        result = governance_engine.evaluate(wo)
        assert result.requires_human_review is False
        assert result.status == WorkOrderStatus.APPROVED


class TestLogDecision:
    """Verify that log_decision creates an audit trail entry."""

    def test_creates_decision_record(self, governance_engine):
        """log_decision should return a valid AgentDecision with all fields."""
        decision = governance_engine.log_decision(
            work_order_id="WO-TEST-LOG",
            agent_name="Triage Agent",
            decision_type="priority_assignment",
            decision_value="high",
            reasoning="Multiple indicators suggest urgency",
            confidence=0.85,
            data_sources=["asset_history", "maintenance_records"],
        )
        assert decision.decision_id.startswith("DEC-")
        assert decision.agent_name == "Triage Agent"
        assert decision.confidence == 0.85


class TestProcessHumanReview:
    """Verify human review approval and rejection flows."""

    def test_approve_flow(self, governance_engine, seeded_db):
        """Approving a pending work order should set status to approved."""
        from src.data.database import save_work_order, get_connection

        # Create and save a work order in pending_human_review status
        wo = _make_work_order(priority=Priority.CRITICAL, estimated_cost=100.0)
        result = governance_engine.evaluate(wo)
        # Save to DB
        wo_dict = result.model_dump()
        wo_dict["requires_human_review"] = 1 if wo_dict["requires_human_review"] else 0
        if wo_dict.get("safety_requirements"):
            import json
            wo_dict["safety_requirements"] = json.dumps(wo_dict["safety_requirements"])
        if wo_dict.get("relevant_procedures"):
            import json
            wo_dict["relevant_procedures"] = json.dumps(wo_dict["relevant_procedures"])
        save_work_order(wo_dict)

        # Process approval
        review_result = governance_engine.process_human_review(
            work_order_id=result.work_order_id,
            approved=True,
            reviewer_name="Facilities Manager",
            notes="Looks good, proceed.",
        )
        assert review_result["status"] == "approved"

    def test_reject_flow(self, governance_engine, seeded_db):
        """Rejecting a pending work order should set status to rejected."""
        from src.data.database import save_work_order

        wo = _make_work_order(priority=Priority.CRITICAL, estimated_cost=200.0)
        result = governance_engine.evaluate(wo)
        wo_dict = result.model_dump()
        wo_dict["requires_human_review"] = 1 if wo_dict["requires_human_review"] else 0
        if wo_dict.get("safety_requirements"):
            import json
            wo_dict["safety_requirements"] = json.dumps(wo_dict["safety_requirements"])
        if wo_dict.get("relevant_procedures"):
            import json
            wo_dict["relevant_procedures"] = json.dumps(wo_dict["relevant_procedures"])
        save_work_order(wo_dict)

        review_result = governance_engine.process_human_review(
            work_order_id=result.work_order_id,
            approved=False,
            reviewer_name="Facilities Manager",
            notes="Need more information.",
        )
        assert review_result["status"] == "rejected"
