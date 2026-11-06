import json
from pathlib import Path

import pytest

from chronicle.agent import Agent
from chronicle.cli import main
from chronicle.config import initialize, load, save
from chronicle.hook import capture
from chronicle.projects import discover


def test_new_configuration_defaults_to_local(tmp_path):
    cfg = initialize(tmp_path / "chronicle")
    assert cfg["default_project_policy"] == "local"


def test_legacy_configuration_still_discovers_local_projects(cfg, tmp_path):
    cfg.pop("default_project_policy", None)
    save(cfg)
    project = tmp_path / "legacy-project"
    project.mkdir()
    pid, _, _ = discover(project, load(cfg["home"]))
    assert load(cfg["home"])["projects"][pid]["policy"] == "local"


@pytest.mark.parametrize("policy", ["local", "export", "exclude"])
def test_cli_default_applies_only_to_new_projects(cfg, tmp_path, monkeypatch, capsys, policy):
    monkeypatch.setenv("CHRONICLE_HOME", cfg["home"])
    existing = tmp_path / "existing"
    existing.mkdir()
    pid, _, _ = discover(existing, cfg)
    cfg["projects"][pid]["policy"] = "exclude"
    save(cfg)

    assert main(["config", "--default-project-policy", policy]) == 0
    capsys.readouterr()
    saved = load(cfg["home"])
    assert saved["default_project_policy"] == policy
    assert saved["projects"][pid]["policy"] == "exclude"
    assert discover(existing, saved)[0] == pid
    assert saved["projects"][pid]["policy"] == "exclude"

    new = tmp_path / "new"
    new.mkdir()
    new_pid, _, _ = discover(new, saved)
    assert load(cfg["home"])["projects"][new_pid]["policy"] == policy


def test_init_reports_effective_existing_default(cfg, monkeypatch, capsys):
    monkeypatch.setenv("CHRONICLE_HOME", cfg["home"])
    cfg["default_project_policy"] = "export"
    save(cfg)
    assert main(["init"]) == 0
    assert json.loads(capsys.readouterr().out)["default_policy"] == "export"


@pytest.mark.parametrize("policy, expected_events", [("local", 1), ("export", 1), ("exclude", 0)])
def test_worker_respects_default_on_first_event(cfg, tmp_path, policy, expected_events):
    cfg["default_project_policy"] = policy
    save(cfg)
    project = tmp_path / "first-event"
    project.mkdir()
    capture({"cwd": str(project), "hook_event_name": "Stop", "session_id": "s"}, cfg)
    agent = Agent(load(cfg["home"]))
    assert agent.drain() == expected_events
    assert agent.store.stats()["total"] == expected_events
    assert not list((Path(cfg["home"]) / "spool").glob("*.json"))


@pytest.mark.parametrize("invalid", ["EXPORT", "", None, ["export"]])
def test_invalid_default_is_rejected_without_saving(cfg, invalid):
    path = Path(cfg["home"]) / "config.json"
    before = path.read_bytes()
    cfg["default_project_policy"] = invalid
    with pytest.raises(ValueError, match="default_project_policy"):
        save(cfg)
    assert path.read_bytes() == before


def test_invalid_hand_edited_default_is_rejected_on_load(cfg):
    path = Path(cfg["home"]) / "config.json"
    raw = json.loads(path.read_text())
    raw["default_project_policy"] = "publish-everything"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="default_project_policy"):
        load(cfg["home"])


def test_cli_rejects_unknown_default_without_changing_config(cfg, monkeypatch, capsys):
    monkeypatch.setenv("CHRONICLE_HOME", cfg["home"])
    path = Path(cfg["home"]) / "config.json"
    before = path.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["config", "--default-project-policy", "public"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert path.read_bytes() == before
