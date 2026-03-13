"""
============================================================
Database Layer (SQLite)
============================================================
This module simulates a CMMS database like AiM (AssetWorks).

In a real deployment, you'd connect to AiM's REST API instead.
We use SQLite here to keep the project self-contained and
runnable without any external CMMS dependency.

The database stores:
  - Assets (equipment in buildings)
  - Technicians (maintenance staff)
  - Maintenance records (historical work)
  - Work orders (active and past)
  - Agent decisions (audit trail)
  - Human reviews (HITL records)
  - Audit log (chronological event log)

Why SQLite? It's built into Python, needs zero setup, and the
database file can be committed to the repo so anyone can clone
and run immediately. For production, swap with PostgreSQL.
============================================================
"""

import sqlite3
import json
import os
from pathlib import Path


# Database file lives alongside this module
DB_PATH = os.environ.get(
    "DATABASE_PATH",
    str(Path(__file__).parent / "facilities.db")
)


def get_connection() -> sqlite3.Connection:
    """
    Create a database connection with row_factory set to sqlite3.Row.
    
    sqlite3.Row lets you access columns by name (row["asset_id"])
    instead of by index (row[0]). Much more readable.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys (SQLite disables them by default)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    """
    Create all tables if they don't exist.
    
    This is safe to call multiple times. The IF NOT EXISTS clause
    means it won't destroy existing data.
    
    Table design mirrors a simplified CMMS data model:
    - assets: The equipment being maintained
    - technicians: The people doing the work
    - maintenance_records: Historical log of past work
    - work_orders: Current and past work requests
    - agent_decisions: Every AI decision (audit trail)
    - human_reviews: HITL review records
    - audit_log: Chronological event log
    """
    conn = get_connection()
    cursor = conn.cursor()

    # ---- Assets Table ----
    # Central to any CMMS. Every piece of equipment gets tracked.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            building TEXT NOT NULL,
            floor TEXT NOT NULL,
            room TEXT,
            install_date TEXT NOT NULL,
            expected_lifespan_years INTEGER NOT NULL,
            last_service_date TEXT,
            condition TEXT DEFAULT 'operational',
            warranty_expiry TEXT,
            manufacturer TEXT,
            model_number TEXT
        )
    """)

    # ---- Technicians Table ----
    # trades is stored as JSON array (e.g., '["hvac", "electrical"]')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS technicians (
            tech_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            trades TEXT NOT NULL,
            available INTEGER DEFAULT 1,
            current_workload INTEGER DEFAULT 0
        )
    """)

    # ---- Maintenance Records Table ----
    # Historical log. The Planning Agent queries this to spot patterns.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_records (
            record_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            work_order_id TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            cost REAL NOT NULL,
            technician_id TEXT NOT NULL,
            parts_used TEXT DEFAULT '[]',
            FOREIGN KEY (asset_id) REFERENCES assets (asset_id)
        )
    """)

    # ---- Work Orders Table ----
    # The main operational table. Agents enrich this as work flows through.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            work_order_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            building TEXT NOT NULL,
            floor TEXT NOT NULL,
            room TEXT,
            requester_name TEXT NOT NULL,
            requester_email TEXT,
            asset_id TEXT,
            priority TEXT,
            trade_required TEXT,
            triage_reasoning TEXT,
            estimated_cost REAL,
            assigned_technician TEXT,
            scheduled_date TEXT,
            plan TEXT,
            recommendation TEXT,
            relevant_procedures TEXT,
            compliance_notes TEXT,
            safety_requirements TEXT,
            requires_permit INTEGER DEFAULT 0,
            summary TEXT,
            status TEXT DEFAULT 'submitted',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            confidence_score REAL,
            escalation_reason TEXT,
            requires_human_review INTEGER DEFAULT 0
        )
    """)

    # ---- Agent Decisions Table (Audit Trail) ----
    # Every decision by every agent gets recorded here.
    # This is the governance backbone of the system.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_decisions (
            decision_id TEXT PRIMARY KEY,
            work_order_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            decision_value TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            confidence REAL NOT NULL,
            data_sources TEXT DEFAULT '[]',
            timestamp TEXT NOT NULL,
            FOREIGN KEY (work_order_id) REFERENCES work_orders (work_order_id)
        )
    """)

    # ---- Human Reviews Table ----
    # Records of human-in-the-loop decisions.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS human_reviews (
            review_id TEXT PRIMARY KEY,
            work_order_id TEXT NOT NULL,
            escalation_reason TEXT NOT NULL,
            agent_recommendation TEXT NOT NULL,
            reviewer_name TEXT,
            status TEXT DEFAULT 'pending',
            reviewer_notes TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_order_id) REFERENCES work_orders (work_order_id)
        )
    """)

    # ---- Audit Log Table ----
    # Chronological record of every event in the system.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            entry_id TEXT PRIMARY KEY,
            work_order_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_detail TEXT NOT NULL,
            actor TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def seed_database():
    """
    Populate the database with realistic sample data.
    
    This creates a believable facilities environment:
    - A university campus with 5 buildings
    - 20 assets across those buildings (HVAC, elevators, plumbing, etc.)
    - 8 technicians with different specialties
    - 30+ historical maintenance records showing patterns
    
    The historical data is designed so the Planning Agent can
    spot real patterns (e.g., recurring HVAC failures in Building B).
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Check if already seeded (don't duplicate data)
    cursor.execute("SELECT COUNT(*) FROM assets")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # ============================================================
    # ASSETS - Equipment across a university campus
    # ============================================================
    assets = [
        # HVAC Systems
        ("AHU-A01-01", "Air Handling Unit 1", "HVAC", "Admin Building", "1", "Mechanical Room 101",
         "2018-06-15", 20, "2025-11-20", "operational", "2028-06-15", "Carrier", "39HQ580"),
        ("AHU-B12-01", "Air Handling Unit 2", "HVAC", "Science Building", "B1", "Basement Mechanical",
         "2015-03-10", 20, "2025-08-15", "degraded", "2025-03-10", "Trane", "CSAA025"),
        ("RTU-C01-01", "Rooftop Unit 1", "HVAC", "Library", "Roof", None,
         "2019-09-01", 15, "2025-12-01", "operational", "2029-09-01", "Lennox", "LRP14GE"),
        ("BLR-A01-01", "Central Boiler", "HVAC", "Admin Building", "B1", "Boiler Room",
         "2012-11-20", 25, "2025-10-15", "operational", "2027-11-20", "Weil-McLain", "88-200"),
        ("CHL-D01-01", "Campus Chiller", "HVAC", "Central Plant", "1", None,
         "2016-04-22", 25, "2025-09-30", "operational", "2031-04-22", "York", "YCIV0516"),

        # Elevators
        ("ELV-A01-01", "Passenger Elevator 1", "Elevator", "Admin Building", "1-5", "Lobby",
         "2010-08-01", 25, "2025-12-15", "operational", None, "Otis", "Gen2-MRL"),
        ("ELV-B01-01", "Freight Elevator", "Elevator", "Science Building", "1-4", "Service Area",
         "2008-05-15", 30, "2025-06-20", "degraded", None, "Schindler", "5500AP"),

        # Plumbing
        ("PMP-A01-01", "Sump Pump Main", "Plumbing", "Admin Building", "B1", "Utility Room",
         "2020-01-10", 15, "2025-07-22", "operational", "2030-01-10", "Zoeller", "M98"),
        ("HWH-C01-01", "Hot Water Heater", "Plumbing", "Library", "B1", "Mechanical Room",
         "2017-11-05", 12, "2025-09-10", "degraded", "2027-11-05", "A.O. Smith", "BTH-300"),
        ("BFP-D01-01", "Backflow Preventer", "Plumbing", "Central Plant", "1", None,
         "2019-07-15", 20, "2025-11-01", "operational", "2029-07-15", "Watts", "909M1"),

        # Electrical
        ("GEN-A01-01", "Emergency Generator", "Electrical", "Admin Building", "B1", "Generator Room",
         "2014-02-28", 30, "2025-12-01", "operational", "2029-02-28", "Caterpillar", "D150-8"),
        ("UPS-B01-01", "UPS System Lab", "Electrical", "Science Building", "2", "Server Room 204",
         "2021-06-10", 10, "2025-10-20", "operational", "2031-06-10", "APC", "SRT10KXLI"),
        ("PNL-E01-01", "Main Electrical Panel", "Electrical", "Student Center", "1", "Electrical Room",
         "2005-09-01", 40, "2025-05-15", "operational", None, "Square D", "NF430L1"),

        # Fire Safety
        ("SPK-A01-01", "Sprinkler System Admin", "Fire Safety", "Admin Building", "All", None,
         "2010-08-01", 30, "2025-12-20", "operational", None, "Viking", "VK302"),
        ("FAP-E01-01", "Fire Alarm Panel", "Fire Safety", "Student Center", "1", "Security Office",
         "2018-03-15", 20, "2025-11-30", "operational", "2028-03-15", "Honeywell", "NFS2-3030"),

        # General / Structural
        ("ROF-C01-01", "Flat Roof Membrane", "Roofing", "Library", "Roof", None,
         "2013-07-20", 20, "2025-04-10", "degraded", None, "Firestone", "TPO-60"),
        ("DOK-E01-01", "Loading Dock Door", "General", "Student Center", "1", "Receiving",
         "2016-10-05", 15, "2025-08-25", "operational", "2026-10-05", "Overhead Door", "RapidFlex"),

        # Grounds
        ("IRR-F01-01", "Irrigation System Main", "Grounds", "Campus Grounds", "Ext", None,
         "2019-04-01", 15, "2025-10-30", "operational", "2029-04-01", "Rain Bird", "ESP-ME3"),
        ("PKG-F01-01", "Parking Lot Lights", "Electrical", "Parking Structure", "All", None,
         "2017-08-15", 15, "2025-06-10", "operational", "2027-08-15", "Lithonia", "DSX0-LED"),

        # Janitorial
        ("CRP-E01-01", "Carpet System Ballroom", "General", "Student Center", "2", "Ballroom",
         "2020-05-20", 10, "2025-09-15", "degraded", None, "Shaw", "Philadelphia"),
    ]

    cursor.executemany("""
        INSERT INTO assets (asset_id, name, category, building, floor, room,
                          install_date, expected_lifespan_years, last_service_date,
                          condition, warranty_expiry, manufacturer, model_number)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, assets)

    # ============================================================
    # TECHNICIANS - The maintenance team
    # ============================================================
    technicians = [
        ("TECH-001", "James Morrison", json.dumps(["hvac", "general"]), 1, 3),
        ("TECH-002", "Sarah Chen", json.dumps(["electrical", "fire_safety"]), 1, 2),
        ("TECH-003", "Mike Rodriguez", json.dumps(["plumbing", "general"]), 1, 4),
        ("TECH-004", "Emily Thompson", json.dumps(["hvac", "electrical"]), 1, 1),
        ("TECH-005", "David Kim", json.dumps(["elevator"]), 1, 2),
        ("TECH-006", "Lisa Patel", json.dumps(["carpentry", "painting", "general"]), 1, 3),
        ("TECH-007", "Robert Wilson", json.dumps(["roofing", "grounds"]), 0, 0),  # On leave
        ("TECH-008", "Ana Garcia", json.dumps(["janitorial", "general"]), 1, 2),
    ]

    cursor.executemany("""
        INSERT INTO technicians (tech_id, name, trades, available, current_workload)
        VALUES (?, ?, ?, ?, ?)
    """, technicians)

    # ============================================================
    # MAINTENANCE RECORDS - Historical work (for pattern detection)
    # ============================================================
    # Note: AHU-B12-01 has RECURRING failures (3 times in 6 months)
    # This is intentional so the Planning Agent can recommend replacement.
    records = [
        # AHU-B12-01 recurring issues (pattern: failing every 2-3 months)
        ("MR-001", "AHU-B12-01", "WO-2025-0120", "2025-03-15", "Belt replacement and bearing inspection", 850.00, "TECH-001", json.dumps(["V-belt A68", "Bearing grease"])),
        ("MR-002", "AHU-B12-01", "WO-2025-0187", "2025-06-02", "Motor overheating. Replaced fan motor.", 2200.00, "TECH-004", json.dumps(["Fan motor 5HP", "Motor mount bolts"])),
        ("MR-003", "AHU-B12-01", "WO-2025-0234", "2025-08-15", "Compressor failure. Emergency repair.", 3800.00, "TECH-001", json.dumps(["Compressor unit", "Refrigerant R-410A"])),
        ("MR-004", "AHU-B12-01", "WO-2025-0301", "2025-11-10", "Vibration detected. Bearings replaced again.", 1100.00, "TECH-004", json.dumps(["Bearing set", "Alignment shims"])),

        # Normal maintenance on other assets
        ("MR-005", "AHU-A01-01", "WO-2025-0150", "2025-04-20", "Annual filter replacement and coil cleaning", 450.00, "TECH-001", json.dumps(["MERV-13 filters x6"])),
        ("MR-006", "AHU-A01-01", "WO-2025-0280", "2025-11-20", "Semi-annual PM. All systems normal.", 320.00, "TECH-001", json.dumps(["MERV-13 filters x6", "Belt A68"])),

        ("MR-007", "ELV-A01-01", "WO-2025-0200", "2025-06-20", "Annual elevator inspection. Passed.", 1200.00, "TECH-005", json.dumps(["Door operator cable", "Guide shoe inserts"])),
        ("MR-008", "ELV-A01-01", "WO-2025-0310", "2025-12-15", "Door alignment adjustment. Minor fix.", 350.00, "TECH-005", json.dumps([])),

        ("MR-009", "ELV-B01-01", "WO-2025-0155", "2025-04-25", "Hydraulic fluid leak. Seal replacement.", 1800.00, "TECH-005", json.dumps(["Hydraulic seal kit", "Hydraulic fluid 5gal"])),
        ("MR-010", "ELV-B01-01", "WO-2025-0220", "2025-06-20", "Annual inspection. Noted rail wear.", 1200.00, "TECH-005", json.dumps([])),

        ("MR-011", "GEN-A01-01", "WO-2025-0180", "2025-05-15", "Quarterly load bank test. Passed.", 600.00, "TECH-002", json.dumps(["Oil filter", "Fuel filter"])),
        ("MR-012", "GEN-A01-01", "WO-2025-0270", "2025-09-10", "Quarterly test. Battery replaced.", 900.00, "TECH-002", json.dumps(["Starting battery", "Oil filter"])),
        ("MR-013", "GEN-A01-01", "WO-2025-0320", "2025-12-01", "Quarterly test. All normal.", 500.00, "TECH-002", json.dumps(["Oil filter", "Fuel filter"])),

        ("MR-014", "PMP-A01-01", "WO-2025-0210", "2025-07-22", "Float switch replacement.", 280.00, "TECH-003", json.dumps(["Float switch"])),

        ("MR-015", "HWH-C01-01", "WO-2025-0160", "2025-05-10", "Anode rod replacement. Sediment flush.", 420.00, "TECH-003", json.dumps(["Anode rod", "Drain valve"])),
        ("MR-016", "HWH-C01-01", "WO-2025-0250", "2025-09-10", "Thermostat malfunction. Replaced.", 650.00, "TECH-003", json.dumps(["Thermostat assembly"])),

        ("MR-017", "SPK-A01-01", "WO-2025-0330", "2025-12-20", "Annual fire sprinkler inspection. Passed.", 800.00, "TECH-002", json.dumps([])),
        ("MR-018", "FAP-E01-01", "WO-2025-0325", "2025-11-30", "Smoke detector replacement wing C.", 450.00, "TECH-002", json.dumps(["Smoke detectors x12"])),

        ("MR-019", "ROF-C01-01", "WO-2025-0100", "2025-04-10", "Patched 3 areas with membrane tears.", 2800.00, "TECH-007", json.dumps(["TPO membrane 10ft", "Adhesive"])),

        ("MR-020", "BLR-A01-01", "WO-2025-0290", "2025-10-15", "Annual boiler inspection and cleaning.", 1500.00, "TECH-001", json.dumps(["Burner nozzle", "Gasket set"])),

        ("MR-021", "CHL-D01-01", "WO-2025-0260", "2025-09-30", "Chiller annual PM. Condenser cleaning.", 2100.00, "TECH-004", json.dumps(["Refrigerant R-134a", "Condenser coil cleaner"])),

        ("MR-022", "RTU-C01-01", "WO-2025-0315", "2025-12-01", "Economizer calibration and filter change.", 380.00, "TECH-001", json.dumps(["MERV-11 filters x4"])),

        ("MR-023", "IRR-F01-01", "WO-2025-0285", "2025-10-30", "Winterization. Blowout and valve shutoff.", 350.00, "TECH-007", json.dumps([])),

        ("MR-024", "DOK-E01-01", "WO-2025-0240", "2025-08-25", "Dock door spring replacement.", 780.00, "TECH-006", json.dumps(["Torsion spring set"])),

        ("MR-025", "PKG-F01-01", "WO-2025-0170", "2025-06-10", "Replaced 8 failed LED fixtures.", 1600.00, "TECH-002", json.dumps(["LED fixture x8"])),

        # More AHU-B12-01 issues from 2024 (longer pattern)
        ("MR-026", "AHU-B12-01", "WO-2024-0380", "2024-10-05", "Refrigerant leak detected and sealed.", 1500.00, "TECH-001", json.dumps(["Refrigerant R-410A", "Sealant"])),
        ("MR-027", "AHU-B12-01", "WO-2024-0420", "2024-12-18", "Control board failure. Replaced.", 2800.00, "TECH-004", json.dumps(["Control board PCB"])),
    ]

    cursor.executemany("""
        INSERT INTO maintenance_records (record_id, asset_id, work_order_id, date,
                                        description, cost, technician_id, parts_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)

    conn.commit()
    conn.close()
    print(f"Database seeded successfully at {DB_PATH}")


# ============================================================
# QUERY HELPERS - Used by agent tools to read from the database
# ============================================================

def get_asset(asset_id: str) -> dict | None:
    """Look up a single asset by its ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_assets_in_building(building: str) -> list[dict]:
    """Get all assets in a specific building."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM assets WHERE building LIKE ?", (f"%{building}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset_maintenance_history(asset_id: str) -> list[dict]:
    """
    Get all maintenance records for an asset, ordered by date.
    The Planning Agent uses this to detect recurring failure patterns.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM maintenance_records WHERE asset_id = ? ORDER BY date DESC",
        (asset_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_available_technicians(trade: str = None) -> list[dict]:
    """
    Get available technicians, optionally filtered by trade.
    Returns technicians sorted by lowest workload first.
    """
    conn = get_connection()
    if trade:
        # trades is stored as JSON array, so we search within it
        rows = conn.execute(
            "SELECT * FROM technicians WHERE available = 1 AND trades LIKE ? ORDER BY current_workload ASC",
            (f'%"{trade}"%',)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM technicians WHERE available = 1 ORDER BY current_workload ASC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_work_order(work_order: dict):
    """Insert or update a work order in the database."""
    conn = get_connection()
    # Convert lists to JSON strings for storage
    if work_order.get("relevant_procedures"):
        work_order["relevant_procedures"] = json.dumps(work_order["relevant_procedures"])
    if work_order.get("safety_requirements"):
        work_order["safety_requirements"] = json.dumps(work_order["safety_requirements"])

    columns = ", ".join(work_order.keys())
    placeholders = ", ".join(["?" for _ in work_order])
    values = list(work_order.values())

    conn.execute(
        f"INSERT OR REPLACE INTO work_orders ({columns}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()


def save_agent_decision(decision: dict):
    """Record an agent decision in the audit trail."""
    conn = get_connection()
    if isinstance(decision.get("data_sources"), list):
        decision["data_sources"] = json.dumps(decision["data_sources"])

    columns = ", ".join(decision.keys())
    placeholders = ", ".join(["?" for _ in decision])
    values = list(decision.values())

    conn.execute(
        f"INSERT INTO agent_decisions ({columns}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()


def save_audit_log(entry: dict):
    """Add an entry to the chronological audit log."""
    conn = get_connection()
    columns = ", ".join(entry.keys())
    placeholders = ", ".join(["?" for _ in entry])
    values = list(entry.values())

    conn.execute(
        f"INSERT INTO audit_log ({columns}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()


def get_work_order(work_order_id: str) -> dict | None:
    """Retrieve a work order by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_reviews() -> list[dict]:
    """Get all work orders pending human review."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM work_orders WHERE status = 'pending_human_review'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_audit_trail(work_order_id: str) -> list[dict]:
    """Get the full audit trail for a specific work order."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_decisions WHERE work_order_id = ? ORDER BY timestamp ASC",
        (work_order_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize database when this module is imported
initialize_database()
