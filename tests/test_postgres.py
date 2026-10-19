"""Opt-in PostgreSQL contract test; creates and drops its own isolated database."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

import pytest
from conftest import event

from chronicle.store import Store


@pytest.mark.skipif(
    not os.environ.get("CHRONICLE_TEST_POSTGRES"), reason="CHRONICLE_TEST_POSTGRES not configured"
)
def test_postgresql_concurrent_store_and_dedupe(cfg):
    import psycopg
    from psycopg import sql

    admin_url = os.environ["CHRONICLE_TEST_POSTGRES"]
    db = "chronicle_test_" + uuid.uuid4().hex
    parsed = urlsplit(admin_url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
    try:
        url = urlunsplit(parsed._replace(path="/" + db))
        store = Store(url)
        events = [event(cfg, session=f"session-{i}") for i in range(100)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda e: store.append([e], True), events * 2))
        assert store.stats()["total"] == 100
        store.set_meta("checkpoint", {"accepted": True})
        assert Store(url).get_meta("checkpoint") == {"accepted": True}
        assert len({e["global_sequence"] for e in store.events()}) == 100
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))


@pytest.mark.skipif(
    not os.environ.get("CHRONICLE_TEST_POSTGRES"), reason="CHRONICLE_TEST_POSTGRES not configured"
)
def test_fip_postgresql_idempotency_and_atomic_nested_records():
    import psycopg
    from fip_helpers import event as external_event
    from fip_helpers import grant, knowledge
    from psycopg import sql

    from chronicle.memory_service import MemoryService

    admin_url = os.environ["CHRONICLE_TEST_POSTGRES"]
    db = "fip_test_" + uuid.uuid4().hex
    parsed = urlsplit(admin_url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
    try:
        service = MemoryService(Store(urlunsplit(parsed._replace(path="/" + db))))
        e = external_event()
        e["knowledge"] = [knowledge(e["record_id"])]
        arguments = {"record": e, "idempotency_key": "pg-fip-same-key"}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda _: service.execute("append_event", arguments, grant()), range(24))
            )
        assert all(r == results[0] for r in results)
        assert len(service.ledger.rows()) == 2
        reopened = MemoryService(Store(service.store.location))
        assert reopened.execute("append_event", arguments, grant()) == results[0]
        assert reopened.execute("search_knowledge", {"query": "deterministic physics"}, grant())[
            "data"
        ]["items"]
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
