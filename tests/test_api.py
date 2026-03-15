"""
Tests for FastAPI endpoints in src/api/routes.py.

Uses the TestClient fixture from conftest.py. These tests hit real
endpoints against the seeded SQLite database, so no OpenAI API key
is needed.
"""

import pytest


class TestHealthEndpoint:
    """Verify the /health endpoint reports system status."""

    def test_healthy_status(self, client):
        """GET /health should return 200 with status 'healthy'."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


class TestAssetsList:
    """Verify the /assets list endpoint."""

    def test_returns_all_assets(self, client):
        """GET /assets should return the 20 seeded assets."""
        resp = client.get("/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 20


class TestAssetDetail:
    """Verify the /assets/{id} detail endpoint."""

    def test_existing_asset(self, client):
        """GET /assets/{id} for a known asset should return its data."""
        resp = client.get("/assets/AHU-B12-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Air Handling Unit 2"

    def test_nonexistent_asset_returns_404(self, client):
        """GET /assets/{id} for an unknown asset should return 404."""
        resp = client.get("/assets/FAKE-999")
        assert resp.status_code == 404


class TestGovernanceDashboard:
    """Verify the /governance/dashboard endpoint."""

    def test_returns_stats(self, client):
        """GET /governance/dashboard should return governance summary."""
        resp = client.get("/governance/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "governance_policy" in data
        assert data["governance_policy"]["cost_threshold"] == 5000.0


class TestPendingReviews:
    """Verify the /reviews/pending endpoint."""

    def test_returns_list(self, client):
        """GET /reviews/pending should return a count (possibly zero)."""
        resp = client.get("/reviews/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
