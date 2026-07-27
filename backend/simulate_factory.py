# backend/simulate_factory.py
import sqlite3
import random
import time
import asyncio
import os
from typing import Dict, Any

DB_PATH = "./dynamic_datacore.sqlite"

def init_simulator_db(db_path: str = DB_PATH):
    """Ensures dynamic_datacore.sqlite exists with seeded inventory and shipments tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create inventory telemetry table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT UNIQUE,
            category TEXT,
            quantity INTEGER,
            reorder_threshold INTEGER,
            unit_price REAL
        )
    """)
    
    # Create supply chain shipments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE,
            supplier TEXT,
            status TEXT,
            estimated_days INTEGER
        )
    """)
    
    # Seed initial rows if inventory is empty
    cursor.execute("SELECT COUNT(*) FROM inventory")
    if cursor.fetchone()[0] == 0:
        sample_inventory = [
            ("Thermal Sensor Pack v2", "Electronics", 150, 30, 45.00),
            ("Microcontroller Board X1", "Semiconductors", 200, 40, 120.50),
            ("Industrial Display Unit 10inch", "Displays", 85, 20, 210.00),
            ("Lithium Battery Module 24V", "Power", 40, 15, 350.00),
            ("Precision Stepper Motor", "Actuators", 300, 50, 65.00)
        ]
        cursor.executemany("""
            INSERT INTO inventory (item_name, category, quantity, reorder_threshold, unit_price)
            VALUES (?, ?, ?, ?, ?)
        """, sample_inventory)
        
    # Seed initial rows if shipments is empty
    cursor.execute("SELECT COUNT(*) FROM shipments")
    if cursor.fetchone()[0] == 0:
        sample_shipments = [
            ("TRK-8821-ALPHA", "Apex Supply Corp", "On-Time", 3),
            ("TRK-9942-BETA", "Global Electronics Hub", "On-Time", 5),
            ("TRK-1044-GAMMA", "Nordic Component Logistics", "On-Time", 2)
        ]
        cursor.executemany("""
            INSERT INTO shipments (tracking_code, supplier, status, estimated_days)
            VALUES (?, ?, ?, ?)
        """, sample_shipments)
        
    conn.commit()
    conn.close()

def inject_random_anomaly(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Randomly injects an inventory depletion, shipment delay, or pricing anomaly into SQLite."""
    init_simulator_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    anomaly_type = random.choice(["stock_depletion", "shipment_delay", "price_spike"])
    anomaly_summary = {}
    
    if anomaly_type == "stock_depletion":
        cursor.execute("SELECT id, item_name, quantity FROM inventory ORDER BY RANDOM() LIMIT 1")
        item = cursor.fetchone()
        if item:
            item_id, item_name, current_qty = item
            new_qty = random.randint(2, 8)
            cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, item_id))
            anomaly_summary = {
                "type": "Low Stock Anomaly",
                "table": "inventory",
                "item": item_name,
                "old_quantity": current_qty,
                "new_quantity": new_qty,
                "message": f"Critical stock depletion: '{item_name}' dropped from {current_qty} to {new_qty} units."
            }
            
    elif anomaly_type == "shipment_delay":
        cursor.execute("SELECT id, tracking_code, supplier FROM shipments ORDER BY RANDOM() LIMIT 1")
        shipment = cursor.fetchone()
        if shipment:
            s_id, tracking, supplier = shipment
            new_days = random.randint(14, 30)
            cursor.execute("UPDATE shipments SET status = 'Delayed', estimated_days = ? WHERE id = ?", (new_days, s_id))
            anomaly_summary = {
                "type": "Shipment Delay Anomaly",
                "table": "shipments",
                "tracking_code": tracking,
                "supplier": supplier,
                "delay_days": new_days,
                "message": f"Supply chain disruption: Shipment '{tracking}' from {supplier} delayed by {new_days} days."
            }
            
    else: # price_spike
        cursor.execute("SELECT id, item_name, unit_price FROM inventory ORDER BY RANDOM() LIMIT 1")
        item = cursor.fetchone()
        if item:
            item_id, item_name, current_price = item
            new_price = round(current_price * random.uniform(1.3, 1.8), 2)
            cursor.execute("UPDATE inventory SET unit_price = ? WHERE id = ?", (new_price, item_id))
            anomaly_summary = {
                "type": "Price Spike Anomaly",
                "table": "inventory",
                "item": item_name,
                "old_price": current_price,
                "new_price": new_price,
                "message": f"Market price volatility: '{item_name}' unit price spiked from ${current_price} to ${new_price}."
            }
            
    conn.commit()
    conn.close()
    print(f" [Factory Simulator] Telemetry Anomaly Injected: {anomaly_summary.get('message')}")
    return anomaly_summary


async def run_factory_simulation_loop(interval_seconds: int = 40):
    """
    Background asynchronous loop running on `interval_seconds` cycle.
    Injects a live anomaly into the datacore database automatically.
    """
    print(f" [Factory Simulator] Event-driven anomaly generator active (Cycle: {interval_seconds}s)...")
    init_simulator_db()
    
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            inject_random_anomaly()
        except Exception as e:
            print(f" [Factory Simulator] Error in simulation loop: {e}")

if __name__ == "__main__":
    print("Running Factory Simulator standalone test...")
    init_simulator_db()
    inject_random_anomaly()

