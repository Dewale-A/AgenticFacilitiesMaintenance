"""
============================================================
CMMS Tools (Simulated AiM API)
============================================================
These tools simulate what you'd get from the AiM CMMS REST API.
In a real deployment, each function would make an HTTP request
to the AiM API endpoints instead of querying SQLite.

The tools are designed as plain functions that agents call.
Each tool:
  1. Takes simple string inputs (agent-friendly)
  2. Queries the database
  3. Returns formatted text that agents can reason about

Why plain functions instead of CrewAI @tool decorators?
  - More portable across CrewAI versions
  - Easier to test independently
  - Can be wrapped as CrewAI tools at the crew level
============================================================
"""

import json
from src.data.database import (
    get_asset,
    get_assets_in_building,
    get_asset_maintenance_history,
    get_available_technicians,
    get_connection,
)


def lookup_asset(asset_id: str) -> str:
    """
    Look up detailed information about a specific asset.
    
    This is what a maintenance planner does when they receive a work
    order: "Let me check what equipment this is, when it was installed,
    what condition it's in, and when it was last serviced."
    
    Args:
        asset_id: The unique identifier for the asset (e.g., "AHU-B12-01")
        
    Returns:
        Formatted string with asset details, or "not found" message
    """
    asset = get_asset(asset_id)
    if not asset:
        return f"Asset {asset_id} not found in CMMS database."

    # Calculate age for the agent to reason about
    from datetime import datetime
    install_year = int(asset["install_date"][:4])
    current_year = datetime.now().year
    age = current_year - install_year
    remaining_life = asset["expected_lifespan_years"] - age

    # Format warranty status
    warranty_status = "No warranty on file"
    if asset["warranty_expiry"]:
        expiry = datetime.strptime(asset["warranty_expiry"], "%Y-%m-%d")
        if expiry > datetime.now():
            warranty_status = f"Under warranty until {asset['warranty_expiry']}"
        else:
            warranty_status = f"Warranty expired on {asset['warranty_expiry']}"

    return f"""
ASSET DETAILS:
  ID: {asset['asset_id']}
  Name: {asset['name']}
  Category: {asset['category']}
  Location: {asset['building']}, Floor {asset['floor']}, {asset.get('room', 'N/A')}
  Manufacturer: {asset.get('manufacturer', 'N/A')} | Model: {asset.get('model_number', 'N/A')}
  Installed: {asset['install_date']} (Age: {age} years)
  Expected Lifespan: {asset['expected_lifespan_years']} years (Remaining: {remaining_life} years)
  Current Condition: {asset['condition']}
  Last Serviced: {asset.get('last_service_date', 'No records')}
  Warranty: {warranty_status}
""".strip()


def lookup_assets_in_building(building: str) -> str:
    """
    Find all assets in a specific building.
    
    Useful when a work order doesn't specify an asset ID but mentions
    a building. The agent can search for relevant equipment.
    
    Args:
        building: Building name or partial name (e.g., "Science" or "Admin Building")
        
    Returns:
        List of assets in the building
    """
    assets = get_assets_in_building(building)
    if not assets:
        return f"No assets found in building matching '{building}'."

    result = f"ASSETS IN '{building}':\n"
    for a in assets:
        result += f"  - {a['asset_id']}: {a['name']} ({a['category']}) | "
        result += f"Floor {a['floor']} | Condition: {a['condition']}\n"

    return result.strip()


def get_maintenance_history(asset_id: str) -> str:
    """
    Retrieve the full maintenance history for an asset.
    
    This is critical for the Planning Agent. Patterns in maintenance
    history reveal whether an asset should be repaired or replaced.
    
    For example, if an HVAC unit has had 4 repairs in 6 months totaling
    $8,000, it's probably cheaper to replace it than keep patching it.
    
    Args:
        asset_id: The asset to look up history for
        
    Returns:
        Formatted maintenance history with cost totals
    """
    records = get_asset_maintenance_history(asset_id)
    if not records:
        return f"No maintenance records found for asset {asset_id}."

    # Calculate summary statistics for the agent
    total_cost = sum(r["cost"] for r in records)
    record_count = len(records)

    # Check for patterns: multiple repairs in last 12 months
    from datetime import datetime, timedelta
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_records = [r for r in records if r["date"] >= one_year_ago]
    recent_cost = sum(r["cost"] for r in recent_records)
    recent_count = len(recent_records)

    result = f"MAINTENANCE HISTORY FOR {asset_id}:\n"
    result += f"  Total Records: {record_count} | Total Cost: ${total_cost:,.2f}\n"
    result += f"  Last 12 Months: {recent_count} repairs | ${recent_cost:,.2f}\n"

    # Flag if there's a concerning pattern
    if recent_count >= 3:
        result += f"  *** WARNING: {recent_count} repairs in the last 12 months suggests recurring issues ***\n"
    if recent_cost > 5000:
        result += f"  *** WARNING: ${recent_cost:,.2f} spent in last 12 months. Consider replacement analysis. ***\n"

    result += "\n  RECORDS (most recent first):\n"
    for r in records:
        parts = json.loads(r["parts_used"]) if isinstance(r["parts_used"], str) else r["parts_used"]
        parts_str = ", ".join(parts) if parts else "None"
        result += f"    [{r['date']}] {r['description']}\n"
        result += f"      Cost: ${r['cost']:,.2f} | Tech: {r['technician_id']} | Parts: {parts_str}\n"

    return result.strip()


def find_available_technicians(trade: str = None) -> str:
    """
    Find available technicians, optionally filtered by trade.
    
    The Planning Agent uses this to assign the right person to
    the job. It considers:
      - Matching trade skills
      - Current availability
      - Workload (assigns to least-busy first)
    
    Args:
        trade: Optional trade filter (e.g., "hvac", "electrical", "plumbing")
        
    Returns:
        List of available technicians sorted by workload
    """
    techs = get_available_technicians(trade)
    if not techs:
        trade_msg = f" with trade '{trade}'" if trade else ""
        return f"No available technicians found{trade_msg}."

    result = f"AVAILABLE TECHNICIANS"
    if trade:
        result += f" (Trade: {trade})"
    result += ":\n"

    for t in techs:
        trades = json.loads(t["trades"]) if isinstance(t["trades"], str) else t["trades"]
        result += f"  - {t['tech_id']}: {t['name']}\n"
        result += f"    Trades: {', '.join(trades)} | Current Workload: {t['current_workload']} active orders\n"

    return result.strip()


def search_work_orders(building: str = None, status: str = None, priority: str = None) -> str:
    """
    Search existing work orders with optional filters.
    
    Useful for the Reporting Agent to find patterns, or for the
    Triage Agent to check if there's already a similar work order.
    
    Args:
        building: Filter by building name
        status: Filter by status (submitted, triaged, planned, etc.)
        priority: Filter by priority (critical, high, medium, low)
        
    Returns:
        List of matching work orders
    """
    conn = get_connection()
    query = "SELECT * FROM work_orders WHERE 1=1"
    params = []

    if building:
        query += " AND building LIKE ?"
        params.append(f"%{building}%")
    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)

    query += " ORDER BY created_at DESC LIMIT 20"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return "No work orders found matching the criteria."

    result = f"WORK ORDERS ({len(rows)} found):\n"
    for r in rows:
        result += f"  [{r['work_order_id']}] {r['title']}\n"
        result += f"    Building: {r['building']} | Priority: {r['priority'] or 'Unset'} | Status: {r['status']}\n"

    return result.strip()


def get_parts_inventory(part_name: str = None) -> str:
    """
    Check parts inventory (simulated).
    
    In a real AiM system, this would query the inventory module.
    Here we simulate common parts availability.
    
    Args:
        part_name: Part to search for (partial match)
        
    Returns:
        Available parts matching the search
    """
    # Simulated inventory (in production, this queries AiM inventory API)
    inventory = {
        "MERV-13 filter": {"qty": 48, "unit_cost": 25.00, "location": "Warehouse A"},
        "MERV-11 filter": {"qty": 24, "unit_cost": 18.00, "location": "Warehouse A"},
        "V-belt A68": {"qty": 12, "unit_cost": 35.00, "location": "Warehouse A"},
        "Bearing grease": {"qty": 8, "unit_cost": 15.00, "location": "Warehouse B"},
        "Refrigerant R-410A": {"qty": 6, "unit_cost": 180.00, "location": "Warehouse B"},
        "Refrigerant R-134a": {"qty": 4, "unit_cost": 150.00, "location": "Warehouse B"},
        "Smoke detector": {"qty": 30, "unit_cost": 45.00, "location": "Warehouse A"},
        "LED fixture": {"qty": 20, "unit_cost": 120.00, "location": "Warehouse A"},
        "Float switch": {"qty": 5, "unit_cost": 55.00, "location": "Warehouse B"},
        "Oil filter (generator)": {"qty": 10, "unit_cost": 22.00, "location": "Warehouse A"},
        "Fuel filter (generator)": {"qty": 8, "unit_cost": 28.00, "location": "Warehouse A"},
        "Hydraulic seal kit": {"qty": 3, "unit_cost": 280.00, "location": "Warehouse B"},
        "Door operator cable": {"qty": 4, "unit_cost": 95.00, "location": "Warehouse B"},
        "Thermostat assembly": {"qty": 6, "unit_cost": 110.00, "location": "Warehouse A"},
        "Anode rod": {"qty": 8, "unit_cost": 45.00, "location": "Warehouse B"},
    }

    if part_name:
        matches = {k: v for k, v in inventory.items() if part_name.lower() in k.lower()}
    else:
        matches = inventory

    if not matches:
        return f"No parts found matching '{part_name}'. May need to order."

    result = "PARTS INVENTORY:\n"
    for name, info in matches.items():
        status = "In Stock" if info["qty"] > 0 else "OUT OF STOCK"
        result += f"  - {name}: {info['qty']} units | ${info['unit_cost']:.2f} each | {info['location']} | {status}\n"

    return result.strip()
