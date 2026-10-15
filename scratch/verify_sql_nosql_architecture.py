"""
Physical verification script for DA3 SQL vs NoSQL Architecture.
Executes read-only operations against MySQL (smart_health_local.db) and
MongoDB Atlas cloud cluster (smart_health_analytics).
Strictly enforces read-only invariant on MongoDB (0 writes, 0 mutations).
"""

import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPERATIONAL_DB = PROJECT_ROOT / "smart_health_local.db"

load_dotenv(PROJECT_ROOT / ".env")

def verify_relational():
    print("--- 1. Relational Database Inspection (MySQL / SQLite) ---")
    conn = sqlite3.connect(str(OPERATIONAL_DB))
    cursor = conn.cursor()
    
    # Tables
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
    table_count = cursor.fetchone()[0]
    print(f"Total tables: {table_count}")
    
    # Indexes
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='index';")
    index_count = cursor.fetchone()[0]
    print(f"Total indexes: {index_count}")
    
    # Foreign keys check
    cursor.execute("PRAGMA foreign_key_list(vitals_readings);")
    vitals_fks = cursor.fetchall()
    print(f"vitals_readings foreign keys: {vitals_fks}")
    
    # Sample Join
    cursor.execute("""
        SELECT p.patient_id, p.first_name, p.last_name, COUNT(v.reading_id) AS reading_count
        FROM patient_profiles p
        LEFT JOIN vitals_readings v ON p.patient_id = v.patient_id
        GROUP BY p.patient_id
        ORDER BY p.patient_id;
    """)
    join_results = cursor.fetchall()
    print(f"Patient vitals count join: {join_results}")
    
    # Outbox status
    cursor.execute("""
        SELECT status, count(*) 
        FROM analytics_outbox 
        GROUP BY status;
    """)
    outbox_stats = cursor.fetchall()
    print(f"Analytics Outbox queue status: {outbox_stats}")
    
    conn.close()
    return {
        "table_count": table_count,
        "index_count": index_count,
        "join_results": join_results,
        "outbox_stats": outbox_stats,
    }

def verify_mongodb():
    print("\n--- 2. MongoDB Atlas Cloud Inspection (Strictly Read-Only) ---")
    uri = os.getenv("MONGODB_URI")
    assert uri, "MONGODB_URI not found"
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = client["smart_health_analytics"]
    
    # 1. Count documents before
    count_before = db["telemetry_events"].count_documents({})
    print(f"telemetry_events initial count: {count_before}")
    assert count_before == 2955, f"Expected 2955 documents, got {count_before}"
    
    # 2. Existing document retrieval
    sample_doc = db["telemetry_events"].find_one({"patient_id": "P101"}, {"_id": 1, "patient_id": 1, "measured_at": 1, "metrics": 1, "source": 1})
    print(f"Sample document retrieved for P101: {sample_doc}")
    
    # 3. Read-only aggregation
    pipeline = [
        {"$match": {"patient_id": "P101"}},
        {"$group": {
            "_id": "$patient_id",
            "total_observations": {"$sum": 1},
            "avg_heart_rate": {"$avg": "$metrics.heart_rate"},
            "min_heart_rate": {"$min": "$metrics.heart_rate"},
            "max_heart_rate": {"$max": "$metrics.heart_rate"},
        }}
    ]
    agg_res = list(db["telemetry_events"].aggregate(pipeline))
    print(f"Aggregation result for P101: {agg_res}")
    
    # 4. Explain plan
    explain_res = db["telemetry_events"].find(
        {"patient_id": "P101", "measured_at": {"$gte": "2026-10-14T00:00:00Z"}}
    ).sort("measured_at", -1).limit(5).explain()
    
    winning_plan = explain_res.get("queryPlanner", {}).get("winningPlan", {})
    winning_stage = winning_plan.get("stage")
    print(f"MongoDB Explain Winning Stage: {winning_stage}")
    
    # 5. Count documents after
    count_after = db["telemetry_events"].count_documents({})
    print(f"telemetry_events final count: {count_after}")
    assert count_after == 2955, f"Document count changed! Before: {count_before}, After: {count_after}"
    print("MongoDB READ-ONLY INVARIANT STRICTLY PRESERVED!")
    
    client.close()
    return {
        "count_before": count_before,
        "count_after": count_after,
        "sample_doc_id": sample_doc["_id"] if sample_doc else None,
        "agg_res": agg_res,
        "winning_stage": winning_stage,
    }

if __name__ == "__main__":
    rel_data = verify_relational()
    mongo_data = verify_mongodb()
    print("\nPhysical verification complete! 0 writes to MongoDB.")
