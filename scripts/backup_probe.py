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
        ["docker", "exec", "-i", "chronicle-postgres-probe", *args],
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
            dump = docker("pg_dump", "-U", "postgres", "-d", source_db, "-Fc")
            docker("pg_restore", "-U", "postgres", "-d", restored_db, "--exit-on-error", data=dump)
            restored = Store(urlunsplit(parsed._replace(path="/" + restored_db)))
            assert restored.events()[0]["event_id"] == e["event_id"]
            assert restored.get_meta("notion:uncertain:test") is True
            restored.append([e], True)
            assert restored.stats()["total"] == 1
            evidence = {
                "postgres_backup_restore": "passed",
                "events_restored": 1,
                "uncertain_write_fence_restored": True,
                "replay_deduplicated": True,
                "backup_bytes": len(dump),
                "backup_sha256": hashlib.sha256(dump).hexdigest(),
            }
            Path("evidence/backup-restore.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps(evidence))
        finally:
            docker("dropdb", "-U", "postgres", source_db)
            docker("dropdb", "-U", "postgres", restored_db)
