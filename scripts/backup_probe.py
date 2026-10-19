"""Backup/restore acceptance on the dedicated test container, never production."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from chronicle.config import initialize
from chronicle.events import normalize
from chronicle.store import Store


def docker(*args, data=None):
    return subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            os.environ.get("CHRONICLE_TEST_CONTAINER", "chronicle-postgres-probe"),
            *args,
        ],
        input=data,
        capture_output=True,
        check=True,
    ).stdout


if __name__ == "__main__":
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory(prefix="chronicle-backup-") as tmp:
        cfg = initialize(Path(tmp))
        source_db = "backup_source_" + uuid.uuid4().hex
        restored_db = "backup_restored_" + uuid.uuid4().hex
        docker("createdb", "-U", "postgres", source_db)
        docker("createdb", "-U", "postgres", restored_db)
        try:
            parsed = urlsplit(os.environ["CHRONICLE_TEST_POSTGRES"])
            source = Store(urlunsplit(parsed._replace(path="/" + source_db)))
            e = normalize({"hook_event_name": "SessionStart", "session_id": "backup-probe"}, cfg)
            e.update(
                project_id="backup-project",
                worktree_id="backup-tree",
                project={"name": "Backup Probe", "remote": ""},
            )
            source.append([e], True)
            source.set_meta("notion:uncertain:test", True)
            from chronicle.memory_service import MemoryService

            sample = json.loads(
                Path("contracts/fip/v1/examples/bootstrap.request.json").read_text(encoding="utf-8")
            )
            actor = {
                "principal_id": "forge-planner",
                "agent_id": "forge-planner",
                "allow_content": True,
                "scopes": ["read", "write"],
                "projects": ["world-forge-demo"],
            }
            fip_ack = MemoryService(source).execute("append_event", sample, actor)
            dump = docker("pg_dump", "-U", "postgres", "-d", source_db, "-Fc")
            docker("pg_restore", "-U", "postgres", "-d", restored_db, "--exit-on-error", data=dump)
            restored = Store(urlunsplit(parsed._replace(path="/" + restored_db)))
            assert restored.events()[0]["event_id"] == e["event_id"]
            assert restored.get_meta("notion:uncertain:test") is True
            restored.append([e], True)
            assert restored.stats()["total"] == 1
            restored_memory = MemoryService(restored)
            assert restored_memory.execute("append_event", sample, actor) == fip_ack
            assert len(restored_memory.ledger.rows()) == 2
            evidence = {
                "postgres_backup_restore": "passed",
                "events_restored": 1,
                "fip_records_restored": 2,
                "fip_idempotency_restored": True,
                "uncertain_write_fence_restored": True,
                "replay_deduplicated": True,
                "backup_bytes": len(dump),
                "backup_sha256": hashlib.sha256(dump).hexdigest(),
            }
            Path(
                os.environ.get("CHRONICLE_PROBE_EVIDENCE", "evidence/backup-restore.json")
            ).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))
        finally:
            docker("dropdb", "-U", "postgres", source_db)
            docker("dropdb", "-U", "postgres", restored_db)
