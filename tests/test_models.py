"""
Tests for Pydantic schemas defined in src/models/schemas.py.

Validates enums, required fields, and default values for the
facilities maintenance data models.
"""

import pytest
from src.models.schemas import (
    Priority,
    WorkOrderStatus,
    WorkOrderCreate,
    GovernancePolicy,
    TradeType,
    EscalationReason,
)


class TestPriorityEnum:
    """Verify Priority enum contains all expected levels."""

    def test_expected_values(self):
        """All four priority levels should exist."""
        expected = {"critical", "high", "medium", "low"}
        actual = {p.value for p in Priority}
        assert expected == actual

    def test_critical_value(self):
        """CRITICAL should map to 'critical'."""
        assert Priority.CRITICAL.value == "critical"


class TestWorkOrderStatus:
    """Verify WorkOrderStatus enum lifecycle values."""

    def test_expected_statuses(self):
        """All documented statuses should be present."""
        expected = {
            "submitted", "triaged", "planned",
            "pending_human_review", "approved",
            "in_progress", "completed", "rejected",
        }
        actual = {s.value for s in WorkOrderStatus}
        assert expected == actual


class TestWorkOrderCreate:
    """Verify WorkOrderCreate required fields and defaults."""

    def test_missing_required_fields_raises(self):
        """Omitting required fields should raise a validation error."""
        with pytest.raises(Exception):
            WorkOrderCreate()

    def test_valid_create(self):
        """A fully populated create model should succeed."""
        wo = WorkOrderCreate(
            title="Leaking pipe",
            description="Water dripping from ceiling in room 201",
            building="Admin Building",
            floor="2",
            requester_name="John Doe",
        )
        assert wo.title == "Leaking pipe"
        assert wo.room is None  # optional field

    def test_optional_fields_default_none(self):
        """Optional fields (room, email, asset_id) default to None."""
        wo = WorkOrderCreate(
            title="Test",
            description="Test description",
            building="B",
            floor="1",
            requester_name="Tester",
        )
        assert wo.room is None
        assert wo.requester_email is None
        assert wo.asset_id is None


class TestGovernancePolicy:
    """Verify GovernancePolicy default values."""

    def test_default_cost_threshold(self):
        """Default cost threshold should be $5,000."""
        policy = GovernancePolicy()
        assert policy.cost_threshold == 5000.0

    def test_default_confidence_threshold(self):
        """Default confidence threshold should be 0.7."""
        policy = GovernancePolicy()
        assert policy.confidence_threshold == 0.7

    def test_default_auto_approve_priorities(self):
        """LOW and MEDIUM should be auto-approvable by default."""
        policy = GovernancePolicy()
        assert Priority.LOW in policy.auto_approve_priorities
        assert Priority.MEDIUM in policy.auto_approve_priorities
        assert Priority.CRITICAL not in policy.auto_approve_priorities

    def test_require_review_for_critical(self):
        """Critical priority review should be required by default."""
        policy = GovernancePolicy()
        assert policy.require_review_for_critical is True

    def test_require_review_for_replacement(self):
        """Equipment replacement review should be required by default."""
        policy = GovernancePolicy()
        assert policy.require_review_for_replacement is True


class TestTradeType:
    """Verify TradeType enum includes key trades."""

    def test_hvac_exists(self):
        assert TradeType.HVAC.value == "hvac"

    def test_electrical_exists(self):
        assert TradeType.ELECTRICAL.value == "electrical"

    def test_total_trades(self):
        """There should be 11 trade types."""
        assert len(TradeType) == 11
