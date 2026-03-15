"""
Tests for the database layer in src/data/database.py.

Validates seed data integrity and query helpers for assets,
technicians, and maintenance records. Uses the session-scoped
seeded database from conftest.py.
"""

import json
import pytest


class TestSeedDatabase:
    """Verify that seed data populates the expected records."""

    def test_assets_populated(self, seeded_db):
        """The database should contain 20 assets after seeding."""
        from src.data.database import get_connection
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        conn.close()
        assert count == 20

    def test_technicians_populated(self, seeded_db):
        """There should be 8 technicians after seeding."""
        from src.data.database import get_connection
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM technicians").fetchone()[0]
        conn.close()
        assert count == 8

    def test_maintenance_records_populated(self, seeded_db):
        """There should be 27 maintenance records after seeding."""
        from src.data.database import get_connection
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM maintenance_records").fetchone()[0]
        conn.close()
        assert count == 27


class TestGetAsset:
    """Verify single-asset lookups."""

    def test_existing_asset(self, seeded_db):
        """Looking up a known asset should return correct data."""
        from src.data.database import get_asset
        asset = get_asset("AHU-B12-01")
        assert asset is not None
        assert asset["name"] == "Air Handling Unit 2"
        assert asset["category"] == "HVAC"
        assert asset["building"] == "Science Building"

    def test_nonexistent_asset(self, seeded_db):
        """Looking up an unknown asset should return None."""
        from src.data.database import get_asset
        assert get_asset("FAKE-999") is None


class TestGetAvailableTechnicians:
    """Verify technician queries with trade filtering."""

    def test_filter_by_hvac(self, seeded_db):
        """Filtering by 'hvac' should return only HVAC-qualified technicians."""
        from src.data.database import get_available_technicians
        techs = get_available_technicians("hvac")
        assert len(techs) > 0
        for t in techs:
            trades = json.loads(t["trades"])
            assert "hvac" in trades

    def test_all_available(self, seeded_db):
        """Calling without a trade filter should return all available technicians."""
        from src.data.database import get_available_technicians
        techs = get_available_technicians()
        # TECH-007 (Robert Wilson) is on leave (available=0), so 7 of 8
        assert len(techs) == 7

    def test_sorted_by_workload(self, seeded_db):
        """Results should be sorted by current_workload ascending."""
        from src.data.database import get_available_technicians
        techs = get_available_technicians()
        workloads = [t["current_workload"] for t in techs]
        assert workloads == sorted(workloads)


class TestGetAssetMaintenanceHistory:
    """Verify maintenance history queries."""

    def test_returns_records_for_known_asset(self, seeded_db):
        """AHU-B12-01 has 6 maintenance records (recurring failure pattern)."""
        from src.data.database import get_asset_maintenance_history
        history = get_asset_maintenance_history("AHU-B12-01")
        assert len(history) == 6

    def test_empty_for_unknown_asset(self, seeded_db):
        """An unknown asset should return an empty list."""
        from src.data.database import get_asset_maintenance_history
        history = get_asset_maintenance_history("FAKE-999")
        assert history == []


class TestSaveWorkOrder:
    """Verify that saving a work order persists it to the database."""

    def test_round_trip(self, seeded_db):
        """Save a work order and retrieve it by ID."""
        from src.data.database import save_work_order, get_work_order
        wo = {
            "work_order_id": "WO-TEST-DB-0001",
            "title": "Test save",
            "description": "Testing persistence",
            "building": "Admin Building",
            "floor": "1",
            "requester_name": "Tester",
            "status": "submitted",
            "created_at": "2026-03-15T00:00:00",
        }
        save_work_order(wo)
        result = get_work_order("WO-TEST-DB-0001")
        assert result is not None
        assert result["title"] == "Test save"
