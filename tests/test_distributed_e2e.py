import json
import os
import subprocess
import sys

from conftest import grant, serve
from mock_notion import MockNotion

from chronicle.agent import Agent
from chronicle.collector import create_app
from chronicle.config import initialize, load, save
from chronicle.memory import record
from chronicle.notion import Publisher
from chronicle.state import build_state


def hook(cfg, cwd, kind, session, **extra):
    raw = {"cwd": str(cwd), "session_id": session, "hook_event_name": kind, **extra}
    r = subprocess.run(
        [sys.executable, "-m", "chronicle.hook"],
        input=json.dumps(raw).encode(),
        capture_output=True,
        env={**os.environ, "CHRONICLE_HOME": cfg["home"]},
        check=False,
    )
    assert r.returncode == 0
    assert "decision" not in json.loads(r.stdout)


def test_two_computers_offline_restart_collector_notion(tmp_path, monkeypatch, report):
    configs, pids = [], []
    for i in range(2):
        cwd = tmp_path / f"repo{i}"
        cwd.mkdir()
        subprocess.run(["git", "init", "-q", str(cwd)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "remote",
                "add",
                "origin",
                f"https://example.org/team/repo{i}.git",
            ],
            check=True,
        )
        cfg = initialize(tmp_path / f"computer{i}")
        cfg["autostart"] = False
        save(cfg)
        for kind in ("SessionStart", "UserPromptSubmit"):
            hook(cfg, cwd, kind, f"s{i}", turn_id="t1", prompt="NEVER_EXPORT_THIS_PROMPT")
        (cwd / "component.py").write_text("assert 1 + 1 == 2\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(cwd / "component.py")], check=False)
        assert result.returncode == 0
        hook(
            cfg,
            cwd,
            "PostToolUse",
            f"s{i}",
            turn_id="t1",
            tool_use_id=f"tool{i}",
            tool_name="Bash",
            tool_response={"exit_code": result.returncode},
            tool_input={"command": "python component.py"},
        )
        hook(cfg, cwd, "Stop", f"s{i}", turn_id="t1")
        agent = Agent(cfg)
        assert agent.drain() == 4
        cfg = load(cfg["home"])
        pid = next(iter(cfg["projects"]))
        cfg["projects"][pid]["policy"] = "export"
        cfg["collector_url"] = "http://127.0.0.1:1"
        cfg["allow_loopback_http"] = True
        save(cfg)
        agent = Agent(cfg)
        monkeypatch.setenv("CHRONICLE_WRITE_TOKEN", f"token{i}")
        assert agent.sync() == 0  # real connection failure, queue persists
        assert agent.store.stats()["pending"] == 4
        configs.append(cfg)
        pids.append(pid)
    grants = [
        grant(f"token{i}", ["write"], cfg["computer_id"], pids) for i, cfg in enumerate(configs)
    ]
    app = create_app(tmp_path / "collector.db", grants)
    with serve(app) as collector_url:
        for i, cfg in enumerate(configs):
            cfg["collector_url"] = collector_url
            save(cfg)
            # New Agent object opens the existing SQLite after a simulated process restart.
            agent = Agent(load(cfg["home"]))
            monkeypatch.setenv("CHRONICLE_WRITE_TOKEN", f"token{i}")
            assert agent.sync(force=True) == 4
            assert agent.sync(force=True) == 0
            # Lost ACK replay: explicitly mark queue undelivered, server deduplicates.
            with agent.store.connect() as c:
                c.execute("UPDATE events SET delivered=0")
            assert agent.sync(force=True) == 4
            record(agent.store, cfg, pids[i], f"s{i}", report)
            assert agent.sync(force=True) == 1
            assert agent.store.stats()["pending"] == 0
    assert app.state.store.stats()["total"] == 10
    events = app.state.store.events()
    assert len({e["computer_id"] for e in events}) == 2
    assert len({e["project_id"] for e in events}) == 2
    assert "NEVER_EXPORT_THIS_PROMPT" not in json.dumps(events)
    mock = MockNotion()
    with serve(mock.app) as notion_url:
        cfg = {
            "home": str(tmp_path),
            "notion_parent": "parent",
            "allow_loopback_http": True,
            "projects": {pid: configs[i]["projects"][pid] for i, pid in enumerate(pids)},
        }
        publisher = Publisher(app.state.store, cfg, "test-notion", notion_url + "/v1", interval=0)
        assert publisher.publish()["projects"] == 2
        projects = [p for p in mock.pages.values() if "Current State" in p["properties"]]
        assert len(projects) == 2
        for pid in pids:
            state = build_state(app.state.store.events(pid))
            assert len(state["sessions"]) == 1
            assert state["tool_results"][0]["exit_code"] == 0
            assert state["tool_results"][0]["test_status"] == "Unknown"
            assert app.state.store.get_meta("notion:page:project:" + pid)["url"]
