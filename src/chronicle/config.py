import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, cast


def home() -> Path:
    return Path(os.environ.get("CHRONICLE_HOME", Path.home() / ".chronicle"))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            d = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(d)
            finally:
                os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(root=None):
    root = Path(root) if root else home()
    path = root / "config.json"
    if not path.exists():
        raise RuntimeError("Сначала выполните chronicle init")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["home"] = str(root)
    return cfg


def save(cfg):
    root = Path(cfg["home"])
    path = root / "config.json"
    with ProcessLock(root / "config.lock"):
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if current.get("revision", 0) != cfg.get("revision", 0):
            raise RuntimeError("Configuration changed concurrently; reload before retry")
        cfg["revision"] = cfg.get("revision", 0) + 1
        atomic_json(path, {k: v for k, v in cfg.items() if k != "home"})


def initialize(root=None):
    root = Path(root) if root else home()
    if (root / "config.json").exists():
        return load(root)
    cfg = {
        "home": str(root),
        "schema_version": 1,
        "computer_id": str(uuid.uuid4()),
        "mode": "Standard",
        "paused": False,
        "autostart": True,
        "collector_url": "",
        "sync_seconds": 60,
        "checkpoint_seconds": 600,
        "stale_seconds": 1800,
        "publish_seconds": 600,
        "retention_days": 90,
        "projects": {},
        "bindings": {},
        "exclude": [],
        "notion_parent": "",
    }
    save(cfg)
    return cfg


class ProcessLock:
    """OS releases the advisory lock after a crash, unlike lockfile existence."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.f.seek(0)
                self.f.write(b"0")
                self.f.flush()
                self.f.seek(0)
                cast(Any, msvcrt).locking(self.f.fileno(), cast(Any, msvcrt).LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise RuntimeError("Chronicle worker уже запущен") from None
        return self

    def __exit__(self, *_):
        self.f.close()
