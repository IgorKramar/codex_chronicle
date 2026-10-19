import datetime as dt
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import event

from chronicle.agent import Agent
from chronicle.config import ProcessLock, load, save
from chronicle.events import normalize, validate_event
from chronicle.hook import capture
from chronicle.memory import record, validate_report
from chronicle.privacy import redact
from chronicle.projects import canonical_remote, discover
from chronicle.state import build_state, period_summary
from chronicle.store import ConflictError, Store
from chronicle.transport import require_https


@pytest.mark.parametrize(
    "kind",
    [
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
        "PreCompact",
        "PostCompact",
        "Stop",
        "Interrupt",
        "SessionEnd",
    ],
)
def test_hook_normalization(cfg, kind):
    e = normalize(
        {
            "hook_event_name": kind,
            "session_id": "s",
            "prompt": "private prompt",
            "last_assistant_message": "private answer",
            "transcript_path": "/secret/file",
            "tool_input": {"command": "cat .env"},
            "tool_response": "secret output",
        },
        cfg,
    )
    blob = json.dumps(e)
    assert all(
        x not in blob
        for x in ["private prompt", "private answer", "secret output", "/secret/file", "cat .env"]
    )
    assert e["kind"] == kind


def test_secret_redaction():
    raw = {
        "api_key": "abc",
        "nested": [
            "password=hunter2",
            "Bearer abc.def.ghi",
            "sk-" + "x" * 30,
            "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate material\n-----END OPENSSH PRIVATE KEY-----",
            "person@example.com",
            "https://user:pass@example.org/repo",
        ],
    }
    blob = json.dumps(redact(raw))
    for secret in [
        "hunter2",
        "abc.def.ghi",
        "x" * 30,
        "private material",
        "person@example.com",
        "user:pass",
    ]:
        assert secret not in blob


@pytest.mark.parametrize(
    "remote",
    [
        "https://user:pass@git.example.org/Team/repo.git?token=x",
        "git@git.example.org:Team/repo.git",
        "ssh://git@git.example.org/Team/repo",
    ],
)
def test_project_remote(remote):
    assert canonical_remote(remote) == "git.example.org/Team/repo"


def test_no_remote_registration_move(cfg, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pid, _, wa = discover(a, cfg)
    assert discover(a, cfg)[0] == pid
    assert discover(b, cfg)[0] != pid
    cfg["bindings"][str(b)] = pid
    save(cfg)
    assert discover(b, cfg)[0] == pid
    assert discover(b, cfg)[2] != wa


def test_hook_persistence_pause_exclude(cfg, tmp_path):
    cfg["exclude"] = [str(tmp_path / "excluded")]
    assert capture({"cwd": str(tmp_path / "excluded" / "child")}, cfg) is None
    cfg["paused"] = True
    assert capture({}, cfg) is None
    cfg["paused"] = False
    capture({"cwd": str(tmp_path), "hook_event_name": "Stop", "session_id": "s"}, cfg)
    assert len(list((Path(cfg["home"]) / "spool").glob("*.json"))) == 1
    assert Agent(load(cfg["home"])).drain() == 1
    assert Agent(load(cfg["home"])).store.stats()["total"] == 1


def test_hook_always_fail_open(cfg):
    result = subprocess.run(
        [sys.executable, "-m", "chronicle.hook"],
        input=b"not JSON",
        capture_output=True,
        env={**os.environ, "CHRONICLE_HOME": cfg["home"]},
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
    assert b"Traceback" not in result.stderr


def test_dedup_conflicts_atomic(cfg, tmp_path):
    store = Store(tmp_path / "e.db")
    e = event(cfg)
    assert store.append([e, e]) == [e["event_id"], e["event_id"]]
    assert store.stats()["total"] == 1
    changed = dict(e, kind="Stop")
    with pytest.raises(ConflictError):
        store.append([event(cfg, session="s2"), changed])
    assert store.stats()["total"] == 1


def test_parallel_writes(cfg, tmp_path):
    store = Store(tmp_path / "e.db")
    events = [event(cfg, session=f"s{i}") for i in range(100)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda e: store.append([e]), events * 2))
    assert store.stats()["total"] == 100
    assert len({e["global_sequence"] for e in store.events()}) == 100


def test_tool_started_does_not_imply_success(cfg):
    e = event(cfg, "PostToolUse", tool_response={"exit_code": 0, "session_id": 1234})
    assert "exit_code" not in e["payload"]
    e = event(cfg, "PostToolUse", tool_response={"exit_code": 0})
    assert e["payload"]["test_status"] == "Unknown"
    assert build_state([e])["tool_results"][0]["test_status"] == "Unknown"


def test_stop_end_stale_late(cfg):
    start = event(cfg)
    stop = event(cfg, "Stop")
    assert build_state([start, stop])["sessions"][0]["status"] == "Running"
    end = event(cfg, "SessionEnd")
    assert build_state([start, end, stop])["sessions"][0]["status"] == "Unknown"
    assert (
        build_state([start], clock=dt.datetime.now(dt.UTC) + dt.timedelta(hours=13))["sessions"][0][
            "status"
        ]
        == "Stale"
    )
    interrupted = event(cfg, "Interrupt")
    assert build_state([start, interrupted])["sessions"][0]["status"] == "Interrupted"


def test_checkpoint_does_not_claim_liveness(cfg):
    agent = Agent(cfg)
    old = event(cfg)
    old["occurred_at"] = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=13)).isoformat()
    agent.store.append([old])
    agent.checkpoint()
    assert agent.store.events()[-1]["kind"] == "Checkpoint"
    assert build_state(agent.store.events())["sessions"][0]["status"] == "Stale"
    agent.checkpoint()
    assert agent.store.stats()["total"] == 2


def test_queue_local_cannot_starve_export(cfg):
    agent = Agent(cfg)
    agent.store.append(
        [event(cfg, project="local") for _ in range(110)] + [event(cfg, project="allowed")]
    )
    assert len(agent.store.pending(time.time(), projects=["allowed"])) == 1


def test_memory_and_revision_history(cfg, report):
    agent = Agent(cfg)
    cfg["projects"]["p1"] = {"name": "test", "remote": "", "policy": "local"}
    first = record(agent.store, cfg, "p1", "s", report)
    report["Decisions"][0]["status"] = "Accepted"
    second = record(agent.store, cfg, "p1", "s", report)
    state = build_state(agent.store.events())
    assert [r["status"] for r in state["decisions"]["ADR-1"]] == ["Proposed", "Accepted"]
    assert state["latest_report"]["evidence"] == "agent_reported"
    assert first != second
    report["Decisions"][0]["status"] = "Probably"
    with pytest.raises(ValueError):
        validate_report(report)


def test_schema_rejects_arbitrary_payload(cfg):
    e = event(cfg)
    e["payload"]["source_code"] = "private"
    with pytest.raises(ValueError):
        validate_event(e)


def test_https_no_credentials_redirect_config():
    for url in [
        "http://example.org",
        "https://user:pass@example.org",
        "https://example.org?token=abc",
    ]:
        with pytest.raises(ValueError):
            require_https(url)
    require_https("http://127.0.0.1:1234", True)


def test_worker_lock_releases_after_exit(tmp_path):
    with ProcessLock(tmp_path / "lock"):
        with pytest.raises(RuntimeError), ProcessLock(tmp_path / "lock"):
            pass
    with ProcessLock(tmp_path / "lock"):
        pass


def test_period_compare_not_completion_count(cfg):
    e = event(cfg)
    date = e["occurred_at"][:10]
    summary = period_summary([e], date)
    assert summary["event_count"] == 1
    assert summary["previous_event_count"] == 0


def test_recognized_test_runner_requires_completed_result(cfg):
    e = event(
        cfg,
        "PostToolUse",
        tool_input={"command": "python -m pytest -q"},
        tool_response={"exit_code": 0},
    )
    assert e["payload"]["test_status"] == "Passed"
    e = event(
        cfg, "PostToolUse", tool_input={"command": "pytest -q"}, tool_response={"session_id": 2}
    )
    assert e["payload"]["test_status"] == "Unknown"
    e = event(
        cfg,
        "PostToolUse",
        tool_input={"command": "pytest; echo success"},
        tool_response={"exit_code": 0},
    )
    assert e["payload"]["test_status"] == "Unknown"


def test_replayed_hook_tool_id_deduplicates_timestamp(cfg):
    a = event(cfg, "PostToolUse", tool_use_id="call-1", tool_response={"exit_code": 0})
    b = event(cfg, "PostToolUse", tool_use_id="call-1", tool_response={"exit_code": 0})
    store = Agent(cfg).store
    store.append([a, b])
    assert store.stats()["total"] == 1


def test_concurrent_accepted_decisions_show_conflict(cfg, report):
    a = Agent(cfg)
    cfg["projects"]["p1"] = {"name": "test", "remote": "", "policy": "local"}
    report["Decisions"][0]["status"] = "Accepted"
    record(a.store, cfg, "p1", "one", report)
    report["Decisions"][0]["choice"] = "another choice"
    record(a.store, cfg, "p1", "two", report)
    state = build_state(a.store.events())
    assert state["decision_conflicts"]
    assert len(state["latest_reports_by_session"]) == 2


def test_config_concurrent_update_is_not_silently_lost(cfg):
    first, second = load(cfg["home"]), load(cfg["home"])
    first["mode"] = "Verbose"
    save(first)
    second["paused"] = True
    with pytest.raises(RuntimeError):
        save(second)
    assert load(cfg["home"])["mode"] == "Verbose"
    assert not load(cfg["home"])["paused"]


def test_hook_autostarts_worker(cfg, tmp_path):
    cfg["autostart"] = True
    save(cfg)
    raw = {"cwd": str(tmp_path), "hook_event_name": "SessionStart", "session_id": "autostart"}
    result = subprocess.run(
        [sys.executable, "-m", "chronicle.hook"],
        input=json.dumps(raw).encode(),
        capture_output=True,
        env={**os.environ, "CHRONICLE_HOME": cfg["home"]},
        check=True,
    )
    assert result.returncode == 0
    health = Path(cfg["home"]) / "agent-health.json"
    try:
        for _ in range(100):
            if health.exists():
                break
            time.sleep(0.02)
        assert health.exists()
        assert Agent(load(cfg["home"])).store.stats()["total"] >= 1
    finally:
        if health.exists():
            import signal

            os.kill(json.loads(health.read_text())["pid"], signal.SIGTERM)


def test_git_snapshot_tracks_committed_changes(cfg, tmp_path):
    from chronicle.projects import git, snapshot

    cwd = tmp_path / "repo"
    cwd.mkdir()
    subprocess.run(["git", "init", "-q", str(cwd)], check=True)
    (cwd / "a.py").write_text("first\n")
    subprocess.run(["git", "-C", str(cwd), "add", "."], check=True)
    commit = [
        "git",
        "-C",
        str(cwd),
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@localhost",
        "commit",
        "-qm",
    ]
    subprocess.run(commit + ["initial"], check=True)
    previous = git(cwd, "rev-parse", "HEAD")
    (cwd / "a.py").write_text("second\n")
    (cwd / ".env").write_text("TOKEN=private\n")
    subprocess.run(["git", "-C", str(cwd), "add", "a.py"], check=True)
    subprocess.run(commit + ["second"], check=True)
    state = snapshot(cwd, previous)
    assert state["files"] == ["a.py"]
    assert "private" not in json.dumps(state)


def test_issue_closure_requires_explicit_source_reference(cfg, report):
    a = Agent(cfg)
    cfg["projects"]["p1"] = {"name": "test", "remote": "", "policy": "local"}
    source = record(a.store, cfg, "p1", "one", report)
    report["Problems"][0]["status"] = "Resolved"
    record(a.store, cfg, "p1", "two", report)
    assert build_state(a.store.events())["issue_states"]["BUG-1"]["status"] == "Open"
    report["Problems"][0]["resolves"] = [source]
    record(a.store, cfg, "p1", "two", report)
    assert build_state(a.store.events())["issue_states"]["BUG-1"]["status"] == "Resolved"
