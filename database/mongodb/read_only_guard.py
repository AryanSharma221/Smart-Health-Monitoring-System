"""
Strict Read-Only Guard and Test Double for MongoDB Atlas.

Enforces:
1. Complete interception and blocking of all write-producing operations:
   - insert_one, insert_many
   - update_one, update_many
   - replace_one
   - delete_one, delete_many
   - bulk_write
   - find_one_and_delete, find_one_and_replace, find_one_and_update
   - create_index, create_indexes, drop_index, drop_indexes, drop
2. Inspection of aggregation pipelines to block write-producing stages ($out, $merge).
3. Zero-risk isolation for tests, clinical audits, and professor demonstrations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)


class MongoWriteViolationError(RuntimeError):
    """Raised when any mutation or write operation is attempted against a read-only MongoDB store."""
    pass


class StrictReadOnlyMongoCollection:
    """
    Transparent decorator/proxy around a PyMongo Collection.
    Delegates read queries (find, count_documents, aggregate, index_information)
    while immediately raising MongoWriteViolationError on any write or mutation attempt.
    """

    WRITE_PRODUCING_STAGES = frozenset({"$out", "$merge"})

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection, name)

    # -------------------------------------------------------------------------
    # Blocked Write Methods
    # -------------------------------------------------------------------------

    def insert_one(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("insert_one is strictly forbidden on read-only MongoDB database.")

    def insert_many(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("insert_many is strictly forbidden on read-only MongoDB database.")

    def update_one(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("update_one is strictly forbidden on read-only MongoDB database.")

    def update_many(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("update_many is strictly forbidden on read-only MongoDB database.")

    def replace_one(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("replace_one is strictly forbidden on read-only MongoDB database.")

    def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("delete_one is strictly forbidden on read-only MongoDB database.")

    def delete_many(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("delete_many is strictly forbidden on read-only MongoDB database.")

    def bulk_write(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("bulk_write is strictly forbidden on read-only MongoDB database.")

    def find_one_and_delete(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("find_one_and_delete is strictly forbidden on read-only MongoDB database.")

    def find_one_and_replace(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("find_one_and_replace is strictly forbidden on read-only MongoDB database.")

    def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("find_one_and_update is strictly forbidden on read-only MongoDB database.")

    def create_index(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("create_index is strictly forbidden on read-only MongoDB database.")

    def create_indexes(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("create_indexes is strictly forbidden on read-only MongoDB database.")

    def drop_index(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("drop_index is strictly forbidden on read-only MongoDB database.")

    def drop_indexes(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("drop_indexes is strictly forbidden on read-only MongoDB database.")

    def drop(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("drop collection is strictly forbidden on read-only MongoDB database.")

    # -------------------------------------------------------------------------
    # Guarded Aggregation Pipeline Inspection
    # -------------------------------------------------------------------------

    def aggregate(self, pipeline: Sequence[Mapping[str, Any]], *args: Any, **kwargs: Any) -> Any:
        """Inspect pipeline stages before delegating to the underlying collection."""
        for stage in pipeline:
            if not isinstance(stage, Mapping):
                continue
            for op in stage.keys():
                if op.lower() in self.WRITE_PRODUCING_STAGES:
                    raise MongoWriteViolationError(
                        f"Write-producing aggregation stage '{op}' is strictly forbidden on read-only MongoDB database."
                    )
        return self._collection.aggregate(pipeline, *args, **kwargs)

    # -------------------------------------------------------------------------
    # Permitted Read Methods
    # -------------------------------------------------------------------------

    def find(self, *args: Any, **kwargs: Any) -> Any:
        return self._collection.find(*args, **kwargs)

    def find_one(self, *args: Any, **kwargs: Any) -> Any:
        return self._collection.find_one(*args, **kwargs)

    def count_documents(self, *args: Any, **kwargs: Any) -> int:
        return self._collection.count_documents(*args, **kwargs)

    def estimated_document_count(self, *args: Any, **kwargs: Any) -> int:
        return self._collection.estimated_document_count(*args, **kwargs)

    def index_information(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._collection.index_information(*args, **kwargs)

    def list_indexes(self, *args: Any, **kwargs: Any) -> Any:
        return self._collection.list_indexes(*args, **kwargs)

    def distinct(self, *args: Any, **kwargs: Any) -> List[Any]:
        return self._collection.distinct(*args, **kwargs)


class StrictReadOnlyMongoDatabase:
    """
    Transparent decorator/proxy around a PyMongo Database.
    Wraps all collection access in StrictReadOnlyMongoCollection.
    """

    def __init__(self, database: Any) -> None:
        self._database = database

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._database, name)
        # If accessing a collection attribute on the database object
        if hasattr(attr, "find") and hasattr(attr, "insert_one"):
            return StrictReadOnlyMongoCollection(attr)
        return attr

    def __getitem__(self, name: str) -> StrictReadOnlyMongoCollection:
        coll = self._database[name]
        return StrictReadOnlyMongoCollection(coll)

    def get_collection(self, name: str, *args: Any, **kwargs: Any) -> StrictReadOnlyMongoCollection:
        coll = self._database.get_collection(name, *args, **kwargs)
        return StrictReadOnlyMongoCollection(coll)

    def list_collection_names(self, *args: Any, **kwargs: Any) -> List[str]:
        return self._database.list_collection_names(*args, **kwargs)

    def list_collections(self, *args: Any, **kwargs: Any) -> Any:
        return self._database.list_collections(*args, **kwargs)

    def create_collection(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("create_collection is strictly forbidden on read-only MongoDB database.")

    def drop_collection(self, *args: Any, **kwargs: Any) -> Any:
        raise MongoWriteViolationError("drop_collection is strictly forbidden on read-only MongoDB database.")
