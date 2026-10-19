import datetime as dt
import json
import os
import random
import time
import uuid
from pathlib import Path

from .config import ProcessLock, atomic_json, load
from .events import now, validate_event
from .privacy import excluded
from .projects import discover, snapshot
from .store import Store
from .transport import TransportError, request, require_https


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg["home"])
        self.store = Store(self.root / "events.db")

    def drain(self):
        count = 0
        discovered = {}
        for path in sorted((self.root / "spool").glob("*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                cwd, e = item["cwd"], item["event"]
                if self.store.contains(e["event_id"]):
                    path.unlink()
                    continue
                if self.cfg["paused"] or excluded(cwd, self.cfg):
                    path.unlink()
                    continue
                if cwd not in discovered:
                    discovered[cwd] = discover(cwd, self.cfg)
                pid, root, worktree = discovered[cwd]
                project = self.cfg["projects"][pid]
                e.update(
                    project_id=pid,
                    project={"name": project["name"], "remote": project["remote"]},
                    worktree_id=worktree,
                )
                # Metadata gathering runs only in worker, never in the hook critical path.
                if e["kind"] in {"SessionStart", "Stop", "PreCompact", "SessionEnd"}:
                    e["payload"].update(snapshot(root))
                self.store.append([e])
                self.store.set_meta("cwd:" + worktree, str(root))
                path.unlink()
                count += 1
            except (ValueError, KeyError, TypeError):
                quarantine = self.root / "quarantine"
                quarantine.mkdir(exist_ok=True, mode=0o700)
                path.replace(quarantine / path.name)
                self.store.set_meta("last_error", {"code": "invalid_spool", "at": now()})
        return count

    def sync(self, force=False):
        if self.cfg["paused"] or not self.cfg["collector_url"]:
            return 0
        url = self.cfg["collector_url"].rstrip("/")
        require_https(url, self.cfg.get("allow_loopback_http", False))
        token = os.environ.get("CHRONICLE_WRITE_TOKEN", "")
        if not token:
            raise RuntimeError("CHRONICLE_WRITE_TOKEN не настроен")
        rows = self.store.pending(
            float("inf") if force else time.time(),
            projects=[
                pid for pid, p in self.cfg["projects"].items() if p.get("policy") == "export"
            ],
        )
        selected = [
            r
            for r in rows
            if self.cfg["projects"].get(json.loads(r["body"])["project_id"], {}).get("policy")
            == "export"
        ]
        if not selected:
            return 0
        bounded, byte_count = [], 32
        for row in selected:
            size = len(row["body"].encode()) + 1
            if byte_count + size > 900_000:
                break
            bounded.append(row)
            byte_count += size
        selected = bounded
        ids = [r["event_id"] for r in selected]
        try:
            result = request(
                "POST",
                url + "/v1/events",
                {"events": [json.loads(r["body"]) for r in selected]},
                {"Authorization": "Bearer " + token},
            )
            acknowledged = result.get("accepted", [])
            if not isinstance(acknowledged, list) or set(acknowledged) - set(ids):
                raise TransportError()
            self.store.ack(acknowledged)
            remaining = set(ids) - set(acknowledged)
            if remaining:
                self.store.retry(remaining, time.time() + 60)
            self.store.set_meta("connection", {"status": "connected", "at": now()})
            return len(acknowledged)
        except TransportError as exc:
            attempts = max(r["attempts"] for r in selected)
            delay = max(
                exc.retry_after, min(3600, 2 ** min(attempts + 1, 12)) * random.uniform(0.8, 1.2)
            )
            self.store.retry(ids, time.time() + delay)
            self.store.set_meta(
                "connection", {"status": "failed", "status_code": exc.status, "at": now()}
            )
            return 0

    def checkpoint(self):
        events = self.store.events()
        latest = {}
        for e in events:
            key = (e["computer_id"], e["session_id"], e["agent_id"])
            if e["kind"] not in {"Checkpoint", "MemoryReport", "GitSnapshot"}:
                if key not in latest or e["occurred_at"] > latest[key]["occurred_at"]:
                    latest[key] = e
        for key, source in latest.items():
            if source["kind"] in {"SessionEnd", "SubagentStop", "Interrupt"}:
                continue
            marker = "checkpoint:" + ":".join(key)
            if time.time() - self.store.get_meta(marker, 0) < self.cfg["checkpoint_seconds"]:
                continue
            e = {k: v for k, v in source.items() if k not in {"global_sequence", "received_at"}}
            idle = (
                dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(e["occurred_at"])
            ).total_seconds()
            e.update(
                event_id=str(uuid.uuid4()),
                kind="Checkpoint",
                occurred_at=now(),
                evidence="derived",
                payload={"source_idle_seconds": round(idle)},
            )
            self.store.append([validate_event(e)])
            self.store.set_meta(marker, time.time())

    def run(self, once=False):
        with ProcessLock(self.root / "worker.lock"):
            next_sync = next_publish = next_checkpoint = next_retention = 0
            while True:
                self.cfg = load(self.root)
                try:
                    if not self.cfg["paused"]:
                        self.drain()
                        if time.time() >= next_checkpoint:
                            next_checkpoint = time.time() + self.cfg["checkpoint_seconds"]
                            self.checkpoint()
                        if time.time() >= next_sync:
                            next_sync = time.time() + self.cfg["sync_seconds"]
                            self.sync()
                        if (
                            self.cfg.get("notion_parent")
                            and not self.cfg["collector_url"]
                            and time.time() >= next_publish
                        ):
                            from .notion import publish_store

                            next_publish = time.time() + self.cfg["publish_seconds"]
                            publish_store(self.store, self.cfg)
                        if time.time() >= next_retention:
                            cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(
                                days=self.cfg["retention_days"]
                            )
                            self.store.purge(before=cutoff.isoformat())
                            next_retention = time.time() + 3600
                    atomic_json(
                        self.root / "agent-health.json",
                        {"at": now(), "pid": os.getpid(), **self.store.stats()},
                    )
                except Exception as e:
                    self.store.set_meta("last_error", {"code": type(e).__name__, "at": now()})
                if once:
                    return
                time.sleep(1)
