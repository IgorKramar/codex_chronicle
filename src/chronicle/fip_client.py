"""HTTP/MCP client boundary with durable write delivery, independent of model turns."""

import json
import random
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from .config import home
from .contracts import validate
from .events import fingerprint
from .fip_routes import ROUTES
from .memory_service import WRITE_TYPES, ApiFault, envelope
from .privacy import redact
from .store import Store
from .transport import TransportError, request, require_https


class FipClient:
    def __init__(self, url, token, outbox=None, client_id=None, allow_loopback_http=False):
        require_https(url, allow_loopback_http)
        if not token:
            raise ValueError("Configure CHRONICLE_API_TOKEN locally")
        self.url, self.token = url.rstrip("/"), token
        self.client_id = client_id
        self.store = Store(Path(outbox) if outbox else home() / "fip-client.db")
        with self.store.connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS fip_outbox (
                endpoint TEXT NOT NULL, client_id TEXT NOT NULL, operation TEXT NOT NULL,
                key TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0, response TEXT,
                PRIMARY KEY(endpoint,client_id,operation,key))""")

    def _send(self, operation, args):
        method, path = ROUTES[operation]
        headers = {"Authorization": "Bearer " + self.token, "FIP-Version": "v1"}
        if operation in WRITE_TYPES:
            headers["Idempotency-Key"] = args["idempotency_key"]
            result = request(method, self.url + path, args["record"], headers)
        else:
            query = dict(args)
            path = re.sub(r"\{(\w+)(?::path)?\}", lambda m: quote(query.pop(m[1]), safe=""), path)
            result = request(
                method, self.url + path + ("?" + urlencode(query) if query else ""), headers=headers
            )
        validate(operation + "Response", result)
        if len(json.dumps(result, ensure_ascii=False).encode()) > args.get(
            "max_response_bytes", 131072
        ):
            raise ApiFault(
                "response_too_large", "Remote response exceeded negotiated byte budget", 413
            )
        return result

    def call(self, operation, args):
        validate(operation + "Arguments", args)
        if operation not in WRITE_TYPES:
            try:
                return self._send(operation, args)
            except TransportError as exc:
                raise ApiFault(
                    "remote_unavailable"
                    if exc.status in {0, 408, 429, 500, 502, 503, 504, 529}
                    else "remote_rejected",
                    "Memory read failed; local Codex work may continue without memory",
                    exc.status or 503,
                    exc.status in {0, 408, 429, 500, 502, 503, 504, 529},
                ) from None
        if not self.client_id:
            raise ApiFault(
                "client_identity_required", "A stable client_id is required for durable writes"
            )
        safe_args = redact(args)
        validate(operation + "Arguments", safe_args)
        if len(json.dumps(safe_args["record"], ensure_ascii=False).encode()) > 64000:
            raise ApiFault("request_too_large", "FIP write exceeds byte budget", 413)
        key = safe_args["idempotency_key"]
        digest = fingerprint(safe_args)
        identity = (self.url, self.client_id, operation, key)
        with self.store.connect() as c:
            c.execute(
                """INSERT INTO fip_outbox(endpoint,client_id,operation,key,digest,body,state)
                         VALUES (?,?,?,?,?,?,'pending') ON CONFLICT DO NOTHING""",
                (*identity, digest, json.dumps(safe_args, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM fip_outbox WHERE endpoint=? AND client_id=? AND operation=? AND key=?",
                identity,
            ).fetchone()
            if row["digest"] != digest:
                raise ApiFault(
                    "idempotency_conflict", "Local key reused with different content", 409
                )
            if row["state"] == "delivered":
                return json.loads(row["response"])
        with self.store.connect() as c:
            head = c.execute(
                "SELECT operation,key FROM fip_outbox WHERE endpoint=? AND client_id=? AND state!='delivered' ORDER BY rowid LIMIT 1",
                (self.url, self.client_id),
            ).fetchone()
        if head and (head["operation"], head["key"]) == (operation, key):
            result = self._deliver(identity)
            if result is not None:
                return result
        queued = {
            **envelope(
                safe_args["record"]["request_id"], safe_args["record"]["project_id"], "queued"
            ),
            "data": {
                "operation": operation,
                "idempotency_key": key,
                "queued": True,
                "accepted": False,
            },
        }
        return validate("QueuedWriteResponse", queued)

    def _deliver(self, identity, force=False):
        with self.store.connect() as c:
            row = c.execute(
                "SELECT * FROM fip_outbox WHERE endpoint=? AND client_id=? AND operation=? AND key=?",
                identity,
            ).fetchone()
        if row["state"] == "blocked":
            raise ApiFault(
                "delivery_blocked",
                "Server rejected queued write; request remains in outbox for operator review",
                409,
            )
        if not force and row["next_attempt"] > time.time():
            return None
        try:
            result = self._send(row["operation"], json.loads(row["body"]))
        except TransportError as exc:
            retryable = exc.status in {0, 408, 429, 500, 502, 503, 504, 529}
            delay = max(
                exc.retry_after,
                min(3600, 2 ** min(row["attempts"] + 1, 12)) * random.uniform(0.8, 1.2),
            )
            with self.store.connect() as c:
                c.execute(
                    "UPDATE fip_outbox SET state=?,attempts=attempts+1,next_attempt=? WHERE endpoint=? AND client_id=? AND operation=? AND key=?",
                    ("pending" if retryable else "blocked", time.time() + delay, *identity),
                )
            if not retryable:
                raise ApiFault(
                    "delivery_blocked",
                    "Server rejected write; retained for operator review",
                    exc.status,
                ) from None
            return None
        with self.store.connect() as c:
            c.execute(
                "UPDATE fip_outbox SET state='delivered',response=? WHERE endpoint=? AND client_id=? AND operation=? AND key=?",
                (json.dumps(result, ensure_ascii=False), *identity),
            )
        return result

    def flush(self, force=False, retry_blocked=False):
        with self.store.connect() as c:
            if retry_blocked:
                c.execute(
                    "UPDATE fip_outbox SET state='pending',next_attempt=0 WHERE endpoint=? AND client_id=? AND state='blocked'",
                    (self.url, self.client_id),
                )
            rows = c.execute(
                "SELECT endpoint,client_id,operation,key FROM fip_outbox WHERE endpoint=? AND client_id=? AND state!='delivered' ORDER BY rowid LIMIT 100",
                (self.url, self.client_id),
            ).fetchall()
        delivered = 0
        for row in rows:
            try:
                if self._deliver(tuple(row), force):
                    delivered += 1
                else:
                    break
            except ApiFault:
                break  # blocked rows are retained, never acknowledged or discarded
        return {"acknowledged": delivered, **self.status()}

    def status(self):
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT state,COUNT(*) AS n FROM fip_outbox WHERE endpoint=? AND client_id=? GROUP BY state",
                (self.url, self.client_id),
            ).fetchall()
        return {r["state"]: r["n"] for r in rows}
