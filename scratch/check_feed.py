import sys, os
from pathlib import Path
repo_root = str(Path(__file__).resolve().parent.parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import time
import sqlite3
from database.mongodb.client import get_mongo_database

print("Monitoring live data feed...")

# Check MySQL
con = sqlite3.connect('smart_health_local.db')
cur = con.cursor()
my_events = cur.execute("SELECT count(1) FROM ingestion_events WHERE source='smartwatch_simulator'").fetchone()[0]
my_readings = cur.execute("SELECT count(1) FROM vitals_readings").fetchone()[0]
latest_readings = cur.execute("SELECT patient_id, metric_code, value, unit, measured_at FROM vitals_readings ORDER BY reading_id DESC LIMIT 5").fetchall()
print(f"MySQL Simulator Events: {my_events}")
print(f"MySQL Total Vitals Readings: {my_readings}")
print("Latest 5 MySQL Readings:")
for r in latest_readings:
    print("  ", r)

# Check MongoDB
db = get_mongo_database()
if db is not None:
    mongo_count = db['telemetry_events'].count_documents({})
    latest_mongo = list(db['telemetry_events'].find({"is_simulated": True}).sort("measured_at", -1).limit(3))
    print(f"\nMongoDB telemetry_events count: {mongo_count}")
    print("Latest 3 MongoDB Telemetry Documents:")
    for doc in latest_mongo:
        metrics = doc.get("metrics", {})
        print(f"   _id={doc.get('_id')}, patient={doc.get('patient_id')}, metrics={metrics}, measured_at={doc.get('measured_at')}")
else:
    print("MongoDB database handle is None")
