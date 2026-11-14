"""Storage backends for AERO-HUB.

The API only talks to the :class:`Store` interface. Three implementations are
provided:

* :class:`MongoStore`  - MongoDB Atlas (cloud mode). Uses change streams.
* :class:`FileStore`   - append-only JSONL file (direct / Raspberry Pi mode).
* :class:`MemoryStore` - ephemeral store for tests and quick local runs.

Keeping the database behind this interface means the dashboard API is identical
in both deployment modes.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from app.defaults import DEFAULT_THRESHOLDS, LEGACY_MQ135_THRESHOLDS
from app.estimates import derived_estimates
from app.timeutil import as_utc, utc_now

logger = logging.getLogger("aerohub.store")


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialise {type(value)!r}")


def _parse_datetime(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _normalise_reading(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    for field in ("timestamp", "created_at"):
        result[field] = as_utc(_parse_datetime(result.get(field)))
    return result


def _normalise_alert(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    result["timestamp"] = as_utc(_parse_datetime(result.get("timestamp")))
    if result.get("reading_id") is not None:
        result["reading_id"] = str(result["reading_id"])
    return result


class Store(ABC):
    backend: str

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def ensure_ready(self) -> None:
        ...

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def insert_reading(self, values: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_latest(self) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def list_readings(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def statistics(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        ...

    @abstractmethod
    async def list_locations(self, limit: int = 1000) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def area_candidates(
        self,
        *,
        start: datetime,
        end: datetime,
        south: float,
        north: float,
        longitude_ranges: list[tuple[float, float]],
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def statuses(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def mark_sensors_seen(self, sensor_names: list[str], seen: datetime) -> None:
        ...

    @abstractmethod
    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def insert_alerts(self, alerts: list[dict[str, Any]]) -> None:
        ...

    @abstractmethod
    async def claim_reading_for_alerts(self, reading_id: str | int) -> bool:
        ...

    @abstractmethod
    async def get_thresholds(self) -> dict[str, dict[str, float]]:
        ...

    @abstractmethod
    async def set_threshold(self, name: str, warning: float, critical: float) -> dict[str, float]:
        ...

    @abstractmethod
    async def get_setting(self, key: str, default: Any) -> Any:
        ...

    @abstractmethod
    async def set_setting(self, key: str, value: Any) -> None:
        ...

    async def watch_readings(self) -> AsyncIterator[dict[str, Any]]:
        """Yield inserted readings until cancelled. Only MongoDB supports this."""
        raise NotImplementedError
        yield  # pragma: no cover


class MemoryStore(Store):
    """Small in-process store, optionally persisted as an append-only JSONL file."""

    backend = "memory"

    def __init__(self, path: str | None = None, max_readings: int = 100000) -> None:
        self.path = Path(path).expanduser() if path else None
        self.max_readings = max(1000, max_readings)
        if self.path:
            self.backend = "file"
        self.readings: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.statuses_by_name: dict[str, dict[str, Any]] = {}
        self.threshold_rows: dict[str, dict[str, float]] = {}
        self.settings: dict[str, Any] = {}
        self._next_reading_id = 1
        self._next_alert_id = 1
        self._lock = asyncio.Lock()
        if self.path and self.path.exists():
            self._load()

    # ------------------------------------------------------------------ lifecycle
    async def connect(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        return None

    async def ensure_ready(self) -> None:
        old_warning, old_critical = LEGACY_MQ135_THRESHOLDS
        current_mq135 = self.threshold_rows.get("mq135")
        if current_mq135 and (
            current_mq135.get("warning_threshold") == old_warning
            and current_mq135.get("critical_threshold") == old_critical
        ):
            self.threshold_rows["mq135"] = {
                "warning_threshold": DEFAULT_THRESHOLDS["mq135"][0],
                "critical_threshold": DEFAULT_THRESHOLDS["mq135"][1],
            }
            self._append("threshold", {"sensor_name": "mq135", **self.threshold_rows["mq135"]})
        for name, (warning, critical) in DEFAULT_THRESHOLDS.items():
            if name not in self.threshold_rows:
                self.threshold_rows[name] = {
                    "warning_threshold": warning,
                    "critical_threshold": critical,
                }
                self._append("threshold", {"sensor_name": name, **self.threshold_rows[name]})

    async def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "ok": True,
            "readings": len(self.readings),
            "path": str(self.path) if self.path else None,
        }

    # ------------------------------------------------------------------ persistence
    def _append(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"kind": kind, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=_json_default) + "\n")

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        pending_alert_claims: list[str] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = record.pop("kind", "")
                    if kind == "reading":
                        record["timestamp"] = _parse_datetime(record.get("timestamp"))
                        record["created_at"] = _parse_datetime(record.get("created_at"))
                        self.readings.append(record)
                        self._next_reading_id = max(self._next_reading_id, int(record.get("id", 0)) + 1)
                    elif kind == "reading_alerts":
                        pending_alert_claims.append(str(record.get("id")))
                    elif kind == "alert":
                        record["timestamp"] = _parse_datetime(record.get("timestamp"))
                        self.alerts.append(record)
                        self._next_alert_id = max(self._next_alert_id, int(record.get("id", 0)) + 1)
                    elif kind == "status":
                        record["last_seen"] = _parse_datetime(record.get("last_seen"))
                        self.statuses_by_name[record["sensor_name"]] = record
                    elif kind == "threshold":
                        name = record.pop("sensor_name")
                        self.threshold_rows[name] = {
                            "warning_threshold": record.get("warning_threshold"),
                            "critical_threshold": record.get("critical_threshold"),
                        }
                    elif kind == "setting":
                        self.settings[record["key"]] = record.get("value")
        except OSError:
            logger.exception("Could not read the local AERO-HUB data file %s", self.path)
            return

        claimed = set(pending_alert_claims)
        for reading in self.readings:
            if str(reading.get("id")) in claimed:
                reading["alerts_processed"] = True
        self.readings.sort(
            key=lambda item: (
                item.get("timestamp") or datetime.min.replace(tzinfo=timezone.utc),
                item.get("id") or 0,
            )
        )
        if len(self.readings) > self.max_readings:
            # Keep the newest window in RAM. The JSONL file still contains the
            # older samples, so nothing is deleted from disk.
            self.readings = self.readings[-self.max_readings :]

    # ------------------------------------------------------------------ readings
    async def insert_reading(self, values: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            document = dict(values)
            document["timestamp"] = as_utc(document.get("timestamp")) or utc_now()
            document["created_at"] = as_utc(document.get("created_at")) or utc_now()
            document["alerts_processed"] = False
            document["id"] = self._next_reading_id
            self._next_reading_id += 1
            self.readings.append(document)
            self._append("reading", document)
            # Trim in batches; deleting from the front of a list on every sample
            # would be needlessly expensive.
            if len(self.readings) > self.max_readings + 1000:
                del self.readings[: len(self.readings) - self.max_readings]
            return dict(document)

    async def get_latest(self) -> dict[str, Any] | None:
        if not self.readings:
            return None
        return dict(max(self.readings, key=lambda item: (item.get("timestamp"), item.get("id"))))

    async def list_readings(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        start, end = as_utc(start), as_utc(end)
        rows = [
            row
            for row in self.readings
            if (start is None or (row.get("timestamp") and row["timestamp"] >= start))
            and (end is None or (row.get("timestamp") and row["timestamp"] <= end))
            and (source is None or row.get("source") == source)
        ]
        rows.sort(key=lambda item: (item.get("timestamp"), item.get("id")))
        return [dict(row) for row in rows[-limit:]]

    async def statistics(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        from app.defaults import STATISTICS_FIELDS

        start, end = as_utc(start), as_utc(end)
        rows = [
            derived_estimates(row)
            for row in self.readings
            if (start is None or (row.get("timestamp") and row["timestamp"] >= start))
            and (end is None or (row.get("timestamp") and row["timestamp"] <= end))
        ]
        result: dict[str, dict[str, Any]] = {}
        for field in STATISTICS_FIELDS:
            values = [row[field] for row in rows if isinstance(row.get(field), (int, float))]
            result[field] = {
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "average": (sum(values) / len(values)) if values else None,
                "count": len(values),
            }
        return result

    async def list_locations(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = sorted(
            (
                row
                for row in self.readings
                if row.get("latitude") is not None and row.get("longitude") is not None
            ),
            key=lambda item: (item.get("timestamp"), item.get("id")),
            reverse=True,
        )
        sites: dict[tuple[str, float, float], dict[str, Any]] = {}
        for row in rows:
            key = (
                row.get("location_name") or "Unnamed site",
                round(float(row["latitude"]), 5),
                round(float(row["longitude"]), 5),
            )
            sites.setdefault(key, row)
            if len(sites) >= limit:
                break
        return [dict(row) for row in sites.values()]

    async def area_candidates(
        self,
        *,
        start: datetime,
        end: datetime,
        south: float,
        north: float,
        longitude_ranges: list[tuple[float, float]],
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        start, end = as_utc(start), as_utc(end)
        rows = [
            row
            for row in self.readings
            if row.get("latitude") is not None
            and row.get("longitude") is not None
            and row.get("timestamp")
            and start <= row["timestamp"] <= end
            and south <= float(row["latitude"]) <= north
            and any(west <= float(row["longitude"]) <= east for west, east in longitude_ranges)
        ]
        rows.sort(key=lambda item: (item.get("timestamp"), item.get("id")), reverse=True)
        return [dict(row) for row in rows[:limit]]

    # ------------------------------------------------------------------ status
    async def statuses(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.statuses_by_name.values()]

    async def mark_sensors_seen(self, sensor_names: list[str], seen: datetime) -> None:
        async with self._lock:
            for name in sensor_names:
                row = self.statuses_by_name.setdefault(
                    name,
                    {"sensor_name": name, "status": "online", "calibration_status": "not calibrated"},
                )
                row["status"] = "online"
                row["last_seen"] = as_utc(seen)
                # Status is derived from the latest reading on reload; persisting it
                # would add several redundant lines to the JSONL file every sample.

    # ------------------------------------------------------------------ alerts
    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = sorted(
            self.alerts,
            key=lambda item: (item.get("timestamp"), item.get("id")),
            reverse=True,
        )
        return [dict(row) for row in rows[:limit]]

    async def insert_alerts(self, alerts: list[dict[str, Any]]) -> None:
        if not alerts:
            return
        async with self._lock:
            for alert in alerts:
                document = dict(alert)
                document["timestamp"] = as_utc(document.get("timestamp")) or utc_now()
                document["id"] = self._next_alert_id
                self._next_alert_id += 1
                self.alerts.append(document)
                self._append("alert", document)

    async def claim_reading_for_alerts(self, reading_id: str | int) -> bool:
        async with self._lock:
            for reading in self.readings:
                if str(reading.get("id")) == str(reading_id):
                    if reading.get("alerts_processed"):
                        return False
                    reading["alerts_processed"] = True
                    self._append("reading_alerts", {"id": reading.get("id")})
                    return True
            return False

    # ------------------------------------------------------------------ config
    async def get_thresholds(self) -> dict[str, dict[str, float]]:
        return copy.deepcopy(self.threshold_rows)

    async def set_threshold(self, name: str, warning: float, critical: float) -> dict[str, float]:
        async with self._lock:
            self.threshold_rows[name] = {
                "warning_threshold": warning,
                "critical_threshold": critical,
            }
            self._append("threshold", {"sensor_name": name, **self.threshold_rows[name]})
            return dict(self.threshold_rows[name])

    async def get_setting(self, key: str, default: Any) -> Any:
        return copy.deepcopy(self.settings.get(key, default))

    async def set_setting(self, key: str, value: Any) -> None:
        async with self._lock:
            self.settings[key] = copy.deepcopy(value)
            self._append("setting", {"key": key, "value": value})


class MongoStore(Store):
    """MongoDB Atlas / MongoDB replica-set store with change streams."""

    backend = "mongodb"

    def __init__(
        self,
        uri: str,
        database: str,
        *,
        change_stream: bool = True,
        timeout_ms: int = 10000,
        retention_days: int = 0,
    ) -> None:
        if not uri:
            raise RuntimeError(
                "MONGODB_URI is empty. Set it in backend/.env, or use "
                "STORAGE_BACKEND=memory for a quick local run."
            )
        self.uri = uri
        self.database_name = database
        self.change_stream = change_stream
        self.timeout_ms = timeout_ms
        self.retention_days = retention_days
        self.client: Any = None
        self.db: Any = None
        self.readings: Any = None
        self.alerts_collection: Any = None
        self.statuses_collection: Any = None
        self.thresholds_collection: Any = None
        self.settings_collection: Any = None

    async def connect(self) -> None:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "The 'motor' package is required for MongoDB mode. "
                "Run: pip install -r requirements.txt"
            ) from exc

        self.client = AsyncIOMotorClient(
            self.uri,
            tz_aware=True,
            serverSelectionTimeoutMS=self.timeout_ms,
            appname="aero-hub",
        )
        self.db = self.client[self.database_name]
        self.readings = self.db["readings"]
        self.alerts_collection = self.db["alerts"]
        self.statuses_collection = self.db["sensor_status"]
        self.thresholds_collection = self.db["thresholds"]
        self.settings_collection = self.db["settings"]
        await self.client.admin.command("ping")

    async def close(self) -> None:
        if self.client is not None:
            self.client.close()

    async def ensure_ready(self) -> None:
        # Reading indexes. A TTL index is optional and useful on the 512 MB
        # Atlas free tier; set READING_RETENTION_DAYS=30 to enable it.
        try:
            if self.retention_days:
                await self.readings.create_index(
                    [("timestamp", 1)],
                    name="timestamp_ttl",
                    expireAfterSeconds=self.retention_days * 86400,
                )
            else:
                await self.readings.create_index(
                    [("timestamp", -1)], name="timestamp_desc"
                )
        except Exception:  # an existing timestamp index with different options
            logger.warning(
                "Could not create the timestamp index; an existing index probably "
                "has different options. Drop the old timestamp index in Atlas and "
                "restart if you want to change retention."
            )
        await self.readings.create_index([("source", 1)], name="source")
        await self.readings.create_index(
            [("latitude", 1), ("longitude", 1)], name="location"
        )
        await self.alerts_collection.create_index([("timestamp", -1)], name="timestamp_desc")
        await self.alerts_collection.create_index([("severity", 1)], name="severity")

        for name, (warning, critical) in DEFAULT_THRESHOLDS.items():
            await self.thresholds_collection.update_one(
                {"_id": name},
                {
                    "$setOnInsert": {
                        "warning_threshold": warning,
                        "critical_threshold": critical,
                    }
                },
                upsert=True,
            )

        # Older versions used raw volts for the MQ-135 alert threshold. Convert
        # only the exact old defaults, leaving a user's custom value untouched.
        old_warning, old_critical = LEGACY_MQ135_THRESHOLDS
        await self.thresholds_collection.update_one(
            {
                "_id": "mq135",
                "warning_threshold": old_warning,
                "critical_threshold": old_critical,
            },
            {
                "$set": {
                    "warning_threshold": DEFAULT_THRESHOLDS["mq135"][0],
                    "critical_threshold": DEFAULT_THRESHOLDS["mq135"][1],
                }
            },
        )

        await self._backfill_estimates()

    async def _backfill_estimates(self) -> None:
        """Add ppm/dust estimates to old rows that only have raw voltages.

        This is a one-time migration guarded by a settings flag. It makes the
        statistics endpoint and long-range charts useful for data recorded
        before the estimate fields existed. Failure is non-fatal: the API still
        works and will retry on the next startup.
        """
        flag = "derived_estimates_backfill_v1"
        try:
            if await self.get_setting(flag, False):
                return
        except Exception as exc:
            logger.warning("Could not read the estimate backfill flag: %s", exc)
            return

        from pymongo import UpdateOne

        query = {
            "$or": [
                {
                    "mq135_raw": {"$exists": True, "$ne": None},
                    "mq135_estimated_ppm": None,
                },
                {
                    "dust_voltage": {"$exists": True, "$ne": None},
                    "dust_ug_m3": None,
                },
            ]
        }
        projection = {
            "mq135_raw": 1,
            "mq135_estimated_ppm": 1,
            "dust_voltage": 1,
            "dust_ug_m3": 1,
        }
        operations = []
        updated = 0
        try:
            async for row in self.readings.find(query, projection):
                derived = derived_estimates(row)
                changes = {}
                if (
                    row.get("mq135_estimated_ppm") is None
                    and derived.get("mq135_estimated_ppm") is not None
                ):
                    changes["mq135_estimated_ppm"] = derived["mq135_estimated_ppm"]
                if row.get("dust_ug_m3") is None and derived.get("dust_ug_m3") is not None:
                    changes["dust_ug_m3"] = derived["dust_ug_m3"]
                if changes:
                    operations.append(UpdateOne({"_id": row["_id"]}, {"$set": changes}))
                if len(operations) >= 500:
                    await self.readings.bulk_write(operations, ordered=False)
                    updated += len(operations)
                    operations.clear()
            if operations:
                await self.readings.bulk_write(operations, ordered=False)
                updated += len(operations)
            await self.set_setting(flag, True)
            if updated:
                logger.info("Backfilled ppm/dust estimates for %s old readings", updated)
        except Exception as exc:
            logger.warning("Could not backfill old ppm/dust estimates: %s", exc)

    async def health(self) -> dict[str, Any]:
        await self.client.admin.command("ping")
        return {
            "backend": "mongodb",
            "ok": True,
            "database": self.database_name,
            "change_stream": self.change_stream,
            "readings": await self.readings.estimated_document_count(),
        }

    # ------------------------------------------------------------------ readings
    async def insert_reading(self, values: dict[str, Any]) -> dict[str, Any]:
        document = {key: value for key, value in values.items() if value is not None}
        document["timestamp"] = as_utc(document.get("timestamp")) or utc_now()
        document["created_at"] = as_utc(document.get("created_at")) or utc_now()
        document["alerts_processed"] = False
        result = await self.readings.insert_one(document)
        document["_id"] = result.inserted_id
        return _normalise_reading(document)

    async def get_latest(self) -> dict[str, Any] | None:
        document = await self.readings.find_one(sort=[("timestamp", -1), ("_id", -1)])
        return _normalise_reading(document) if document else None

    async def list_readings(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if start or end:
            timestamp: dict[str, Any] = {}
            if start:
                timestamp["$gte"] = as_utc(start)
            if end:
                timestamp["$lte"] = as_utc(end)
            query["timestamp"] = timestamp
        if source:
            query["source"] = source
        cursor = self.readings.find(query).sort([("timestamp", -1), ("_id", -1)]).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [_normalise_reading(row) for row in reversed(rows)]

    async def statistics(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        from app.defaults import STATISTICS_FIELDS

        base_query: dict[str, Any] = {}
        if start or end:
            timestamp: dict[str, Any] = {}
            if start:
                timestamp["$gte"] = as_utc(start)
            if end:
                timestamp["$lte"] = as_utc(end)
            base_query["timestamp"] = timestamp

        result: dict[str, dict[str, Any]] = {}
        for field in STATISTICS_FIELDS:
            pipeline = [
                {"$match": {**base_query, field: {"$exists": True, "$ne": None}}},
                {
                    "$group": {
                        "_id": None,
                        "min": {"$min": f"${field}"},
                        "max": {"$max": f"${field}"},
                        "average": {"$avg": f"${field}"},
                        "count": {"$sum": 1},
                    }
                },
            ]
            rows = await self.readings.aggregate(pipeline).to_list(length=1)
            row = rows[0] if rows else {}
            result[field] = {
                "min": row.get("min"),
                "max": row.get("max"),
                "average": row.get("average"),
                "count": row.get("count", 0),
            }
        return result

    async def list_locations(self, limit: int = 1000) -> list[dict[str, Any]]:
        pipeline = [
            {
                "$match": {
                    "latitude": {"$exists": True, "$ne": None},
                    "longitude": {"$exists": True, "$ne": None},
                }
            },
            {"$sort": {"timestamp": -1, "_id": -1}},
            {
                "$group": {
                    "_id": {
                        "name": "$location_name",
                        "latitude": "$latitude",
                        "longitude": "$longitude",
                    },
                    "document": {"$first": "$$ROOT"},
                }
            },
            {"$replaceRoot": {"newRoot": "$document"}},
            {"$sort": {"timestamp": -1, "_id": -1}},
            {"$limit": limit},
        ]
        rows = await self.readings.aggregate(pipeline).to_list(length=limit)
        return [_normalise_reading(row) for row in rows]

    async def area_candidates(
        self,
        *,
        start: datetime,
        end: datetime,
        south: float,
        north: float,
        longitude_ranges: list[tuple[float, float]],
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        longitude_filter = [
            {"longitude": {"$gte": west, "$lte": east}}
            for west, east in longitude_ranges
        ]
        query = {
            "timestamp": {"$gte": as_utc(start), "$lte": as_utc(end)},
            "latitude": {"$gte": south, "$lte": north},
            "$or": longitude_filter,
        }
        cursor = (
            self.readings.find(query)
            .sort([("timestamp", -1), ("_id", -1)])
            .limit(limit)
        )
        rows = await cursor.to_list(length=limit)
        return [_normalise_reading(row) for row in rows]

    # ------------------------------------------------------------------ status
    async def statuses(self) -> list[dict[str, Any]]:
        rows = await self.statuses_collection.find({}).to_list(length=100)
        return [
            {
                "sensor_name": row.get("_id"),
                "status": row.get("status", "offline"),
                "last_seen": row.get("last_seen"),
                "calibration_status": row.get("calibration_status", "not calibrated"),
            }
            for row in rows
        ]

    async def mark_sensors_seen(self, sensor_names: list[str], seen: datetime) -> None:
        if not sensor_names:
            return
        from pymongo import UpdateOne

        operations = [
            UpdateOne(
                {"_id": name},
                {
                    "$set": {"status": "online", "last_seen": as_utc(seen)},
                    "$setOnInsert": {"calibration_status": "not calibrated"},
                },
                upsert=True,
            )
            for name in sensor_names
        ]
        await self.statuses_collection.bulk_write(operations, ordered=False)

    # ------------------------------------------------------------------ alerts
    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self.alerts_collection.find({}).sort([("timestamp", -1), ("_id", -1)]).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [_normalise_alert(row) for row in rows]

    async def insert_alerts(self, alerts: list[dict[str, Any]]) -> None:
        if not alerts:
            return
        documents = []
        for alert in alerts:
            document = dict(alert)
            document["timestamp"] = as_utc(document.get("timestamp")) or utc_now()
            documents.append(document)
        await self.alerts_collection.insert_many(documents, ordered=False)

    async def claim_reading_for_alerts(self, reading_id: str | int) -> bool:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            object_id = ObjectId(str(reading_id))
        except (InvalidId, TypeError):
            return False
        result = await self.readings.find_one_and_update(
            {"_id": object_id, "alerts_processed": {"$ne": True}},
            {"$set": {"alerts_processed": True}},
        )
        return result is not None

    # ------------------------------------------------------------------ config
    async def get_thresholds(self) -> dict[str, dict[str, float]]:
        rows = await self.thresholds_collection.find({}).to_list(length=20)
        result = {
            row["_id"]: {
                "warning_threshold": row.get("warning_threshold"),
                "critical_threshold": row.get("critical_threshold"),
            }
            for row in rows
        }
        for name, (warning, critical) in DEFAULT_THRESHOLDS.items():
            result.setdefault(
                name,
                {"warning_threshold": warning, "critical_threshold": critical},
            )
        return result

    async def set_threshold(self, name: str, warning: float, critical: float) -> dict[str, float]:
        await self.thresholds_collection.update_one(
            {"_id": name},
            {"$set": {"warning_threshold": warning, "critical_threshold": critical}},
            upsert=True,
        )
        return {"warning_threshold": warning, "critical_threshold": critical}

    async def get_setting(self, key: str, default: Any) -> Any:
        row = await self.settings_collection.find_one({"_id": key})
        return copy.deepcopy(row["value"]) if row and "value" in row else copy.deepcopy(default)

    async def set_setting(self, key: str, value: Any) -> None:
        await self.settings_collection.update_one(
            {"_id": key}, {"$set": {"value": value}}, upsert=True
        )

    # ------------------------------------------------------------------ change stream
    async def watch_readings(self) -> AsyncIterator[dict[str, Any]]:
        if not self.change_stream:
            return
        resume_token = None
        while True:
            try:
                kwargs: dict[str, Any] = {"full_document": "updateLookup"}
                if resume_token is not None:
                    kwargs["resume_after"] = resume_token
                async with self.readings.watch(
                    [{"$match": {"operationType": "insert"}}], **kwargs
                ) as stream:
                    async for change in stream:
                        resume_token = stream.resume_token
                        document = change.get("fullDocument")
                        if document:
                            yield _normalise_reading(document)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # network error, failover, unsupported change streams
                logger.warning("MongoDB change stream interrupted: %s", exc)
                await asyncio.sleep(3)


def create_store(settings) -> Store:
    if settings.storage_backend == "mongodb":
        return MongoStore(
            settings.mongodb_uri,
            settings.mongodb_db,
            change_stream=settings.mongodb_change_stream,
            timeout_ms=settings.mongodb_timeout_ms,
            retention_days=settings.reading_retention_days,
        )
    if settings.storage_backend == "file":
        return MemoryStore(settings.storage_path, max_readings=settings.file_max_readings)
    return MemoryStore()


__all__ = [
    "MemoryStore",
    "MongoStore",
    "Store",
    "create_store",
]
