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
