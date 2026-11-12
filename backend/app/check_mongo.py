"""Verify the MongoDB Atlas connection.

Run from the backend directory:

    python -m app.check_mongo

It pings the cluster, creates the required indexes and seeds default
thresholds, then prints a short summary. It does not insert test data.
"""

from __future__ import annotations

import asyncio
import re

from app.config import get_settings
from app.store import MongoStore, create_store


def redact_uri(uri: str) -> str:
    # mongodb+srv://user:password@host/... -> mongodb+srv://user:***@host/...
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", uri)


async def main() -> int:
    settings = get_settings()
    if settings.storage_backend != "mongodb":
        print(
            f"Current STORAGE_BACKEND is '{settings.storage_backend}'. "
            "Set STORAGE_BACKEND=mongodb in backend/.env to check Atlas."
        )
        return 1
    if not settings.mongodb_uri:
        print(
            "MONGODB_URI is empty.\n"
            "Paste the Atlas connection string into backend/.env first.\n"
            "See docs/MONGODB_SETUP.md for the steps."
        )
        return 1

    print(f"Connecting to {redact_uri(settings.mongodb_uri)} ...")
    store = create_store(settings)
    assert isinstance(store, MongoStore)
    try:
        await store.connect()
        await store.ensure_ready()
        health = await store.health()
        indexes = await store.readings.index_information()
        print("MongoDB is ready.")
        print(f"  database      : {health.get('database')}")
        print(f"  readings      : {health.get('readings')} documents")
        print(f"  change stream : {health.get('change_stream')}")
        print(f"  indexes       : {', '.join(sorted(indexes))}")
        print(
            "If change streams are enabled, the API will broadcast inserts made "
            "by any writer, including the Raspberry Pi."
        )
        return 0
    except Exception as exc:
        print("Could not connect to MongoDB Atlas.")
        print(f"  {type(exc).__name__}: {exc}")
        print(
            "Check the username/password, URL encoding, Network Access IP list, "
            "and that the cluster is active. See docs/MONGODB_SETUP.md."
        )
        return 2
    finally:
        await store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
