"""Additive append-only FIP ledger, sharing only the Store connection abstraction."""

import json

from .events import fingerprint, now
from .store import ConflictError

ENTITY_FIELDS = {
    "AgentEvent": "event_id",
    "ProjectContext": "project_id",
    "AgentSession": "session_id",
    "KnowledgeRecord": "knowledge_id",
    "DecisionRecord": "decision_id",
    "ArtifactReference": "artifact_id",
    "TestResult": "test_id",
}


class Ledger:
    def __init__(self, store):
        self.store = store
        seq = "BIGSERIAL PRIMARY KEY" if store.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with store.connect() as c:
            c.execute(f"""CREATE TABLE IF NOT EXISTS fip_records (
                seq {seq}, record_id TEXT UNIQUE NOT NULL, project_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                revision INTEGER NOT NULL, body TEXT NOT NULL, received_at TEXT NOT NULL,
                UNIQUE(project_id,kind,entity_id,revision))""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS fip_project_sequence ON fip_records(project_id,seq)"
            )
            c.execute("""CREATE TABLE IF NOT EXISTS fip_operations (
                principal TEXT NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                digest TEXT NOT NULL, response TEXT NOT NULL,
                PRIMARY KEY(principal,operation,idempotency_key))""")

    def rows(self, projects=None, snapshot=None):
        with self.store.connect() as c:
            query, params, terms = "SELECT * FROM fip_records", [], []
            if projects is not None and "*" not in projects:
                if not projects:
                    return []
                terms.append("project_id IN (" + ",".join("?" for _ in projects) + ")")
                params.extend(projects)
            if snapshot is not None:
                terms.append("seq<=?")
                params.append(snapshot)
            if terms:
                query += " WHERE " + " AND ".join(terms)
            query += " ORDER BY seq"
            return [
                {"sequence": r["seq"], "kind": r["kind"], "body": json.loads(r["body"])}
                for r in self.store.sql(c, query, params).fetchall()
            ]

    def append(self, principal, operation, key, original, records, response, guard):
        """Guard, revisions, records and idempotent response commit in one transaction."""
        digest = fingerprint(original)
        with self.store.connect() as c:
            if self.store.postgres:
                c.execute("SELECT pg_advisory_xact_lock(94732043)")
            else:
                c.execute("BEGIN IMMEDIATE")
            old = self.store.sql(
                c,
                "SELECT digest,response FROM fip_operations WHERE principal=? AND operation=? AND idempotency_key=?",
                (principal, operation, key),
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ConflictError("Idempotency key reused with different content")
                return json.loads(old["response"])
            for kind, record in records:
                entity = str(record[ENTITY_FIELDS[kind]])
                if kind == "AgentSession":
                    entity = record["agent_id"] + ":" + entity
                prior = self.store.sql(
                    c,
                    "SELECT body FROM fip_records WHERE project_id=? AND kind=? AND entity_id=? ORDER BY revision DESC LIMIT 1",
                    (record["project_id"], kind, entity),
                ).fetchone()
                prior = json.loads(prior["body"]) if prior else None
                guard(kind, record, prior)
                if prior:
                    if (
                        record["supersedes"] != prior["record_id"]
                        or record["revision"] != prior["revision"] + 1
                    ):
                        raise ConflictError("Revision predecessor changed")
                elif record["revision"] != 1 or record["supersedes"] is not None:
                    raise ConflictError("First revision must be 1 with null supersedes")
                if self.store.sql(
                    c, "SELECT 1 FROM fip_records WHERE record_id=?", (record["record_id"],)
                ).fetchone():
                    raise ConflictError("Immutable record_id already exists")
                self.store.sql(
                    c,
                    "INSERT INTO fip_records(record_id,project_id,agent_id,kind,entity_id,revision,body,received_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        record["record_id"],
                        record["project_id"],
                        record["agent_id"],
                        kind,
                        entity,
                        record["revision"],
                        json.dumps(record, ensure_ascii=False),
                        now(),
                    ),
                )
            row = self.store.sql(
                c, "SELECT seq FROM fip_records WHERE record_id=?", (response["data"]["record_id"],)
            ).fetchone()
            response["data"]["sequence"] = row["seq"]
            self.store.sql(
                c,
                "INSERT INTO fip_operations(principal,operation,idempotency_key,digest,response) VALUES (?,?,?,?,?)",
                (principal, operation, key, digest, json.dumps(response, ensure_ascii=False)),
            )
        return response
