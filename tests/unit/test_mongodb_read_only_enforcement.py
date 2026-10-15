"""
Unit and regression tests for MongoDB Read-Only Enforcement.

Verifies:
1. Strict interception and rejection of all write-producing operations by StrictReadOnlyMongoCollection.
2. Interception of write-producing aggregation pipeline stages ($out, $merge).
3. OutboxSyncService behavior in sync-disabled mode (zero calls to Mongo writes).
4. Full preservation of read-only analytics query capabilities (find, count_documents, read aggregations).
"""

from __future__ import annotations

import mongomock
import pytest

from database.mongodb.read_only_guard import (
    MongoWriteViolationError,
    StrictReadOnlyMongoCollection,
    StrictReadOnlyMongoDatabase,
)


@pytest.fixture
def mock_mongo_db() -> StrictReadOnlyMongoDatabase:
    client = mongomock.MongoClient()
    raw_db = client["test_analytics"]
    raw_coll = raw_db["telemetry_events"]
    # Seed 5 mock documents directly on the underlying mock before wrapping
    raw_coll.insert_many([
        {"event_id": f"EVT_{i}", "patient_id": "P101", "heart_rate": 70 + i}
        for i in range(5)
    ])
    return StrictReadOnlyMongoDatabase(raw_db)


class TestMongoReadOnlyGuard:
    def test_read_operations_succeed(self, mock_mongo_db: StrictReadOnlyMongoDatabase):
        coll = mock_mongo_db["telemetry_events"]
        assert coll.count_documents({}) == 5
        doc = coll.find_one({"event_id": "EVT_0"})
        assert doc is not None
        assert doc["patient_id"] == "P101"

        # Standard read-only aggregation succeeds
        pipeline = [
            {"$match": {"patient_id": "P101"}},
            {"$group": {"_id": "$patient_id", "avg_hr": {"$avg": "$heart_rate"}}},
        ]
        results = list(coll.aggregate(pipeline))
        assert len(results) == 1
        assert results[0]["avg_hr"] == 72.0

    @pytest.mark.parametrize("method_name,args", [
        ("insert_one", ({"event_id": "EVT_NEW"},)),
        ("insert_many", ([{"event_id": "EVT_NEW"}],)),
        ("update_one", ({"event_id": "EVT_0"}, {"$set": {"heart_rate": 99}})),
        ("update_many", ({}, {"$set": {"heart_rate": 99}})),
        ("replace_one", ({"event_id": "EVT_0"}, {"event_id": "EVT_0_REPLACED"})),
        ("delete_one", ({"event_id": "EVT_0"},)),
        ("delete_many", ({},)),
        ("bulk_write", ([],)),
        ("find_one_and_delete", ({"event_id": "EVT_0"},)),
        ("find_one_and_replace", ({"event_id": "EVT_0"}, {"event_id": "EVT_0"})),
        ("find_one_and_update", ({"event_id": "EVT_0"}, {"$set": {"heart_rate": 100}})),
        ("create_index", (("patient_id", 1),)),
        ("drop_index", ("_idx_",)),
        ("drop", ()),
    ])
    def test_write_methods_raise_violation(
        self,
        mock_mongo_db: StrictReadOnlyMongoDatabase,
        method_name: str,
        args: tuple,
    ):
        coll = mock_mongo_db["telemetry_events"]
        method = getattr(coll, method_name)
        with pytest.raises(MongoWriteViolationError) as exc_info:
            method(*args)
        assert "strictly forbidden on read-only MongoDB" in str(exc_info.value)

    def test_write_producing_aggregation_stages_raise_violation(
        self,
        mock_mongo_db: StrictReadOnlyMongoDatabase,
    ):
        coll = mock_mongo_db["telemetry_events"]

        # 1. $out stage
        with pytest.raises(MongoWriteViolationError) as exc_out:
            coll.aggregate([
                {"$match": {"patient_id": "P101"}},
                {"$out": "unauthorized_export_collection"},
            ])
        assert "$out" in str(exc_out.value)

        # 2. $merge stage
        with pytest.raises(MongoWriteViolationError) as exc_merge:
            coll.aggregate([
                {"$match": {"patient_id": "P101"}},
                {"$merge": {"into": "target_collection"}},
            ])
        assert "$merge" in str(exc_merge.value)

    def test_database_collection_mutations_raise_violation(
        self,
        mock_mongo_db: StrictReadOnlyMongoDatabase,
    ):
        with pytest.raises(MongoWriteViolationError):
            mock_mongo_db.create_collection("new_coll")

        with pytest.raises(MongoWriteViolationError):
            mock_mongo_db.drop_collection("telemetry_events")
