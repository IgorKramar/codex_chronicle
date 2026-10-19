import hashlib
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn

from chronicle.config import initialize, save
from chronicle.events import normalize


@pytest.fixture
def cfg(tmp_path):
    cfg = initialize(tmp_path / "chronicle")
    cfg["autostart"] = False
    save(cfg)
    return cfg


def event(cfg, kind="SessionStart", session="s1", project="p1", **raw):
    e = normalize({"hook_event_name": kind, "session_id": session, **raw}, cfg)
    e.update(
        project_id=project,
        project={"name": project, "remote": "example.com/team/" + project},
        worktree_id="w1",
    )
    return e


def grant(token, scopes, computer=None, projects=None):
    return {
        "sha256": hashlib.sha256(token.encode()).hexdigest(),
        "scopes": scopes,
        "computer_id": computer,
        "projects": projects or ["p1", "p2"],
    }


@contextmanager
def serve(app):
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("Test server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def report():
    return {
        "Task": "Проверить журнал",
        "Actions": ["Запущен эксперимент"],
        "Changes": ["agent"],
        "Decisions": [
            {
                "id": "ADR-1",
                "status": "Proposed",
                "problem": "offline",
                "alternatives": ["sync", "queue"],
                "choice": "queue",
                "rationale": "durable",
                "consequences": "eventual delivery",
            }
        ],
        "Evidence": ["Команда запущена; результат не подтверждён"],
        "Problems": [{"id": "BUG-1", "type": "Bug", "title": "Повтор", "status": "Open"}],
        "Next Steps": ["Проверить real Notion"],
        "Confidence": "Частично проверено",
    }
