import json
import time

import pytest
from conftest import event, serve
from mock_notion import MockNotion

from chronicle.agent import Agent
from chronicle.memory import record
from chronicle.notion import COLLECTIONS, Publisher, UncertainWrite
from chronicle.transport import TransportError


def publisher(cfg, store, url):
    cfg.update(notion_parent="parent", allow_loopback_http=True)
    return Publisher(store, cfg, "test-notion", url + "/v1", interval=0)


def test_full_notion_projection_and_idempotence(cfg, report):
    a = Agent(cfg)
    cfg["projects"]["p1"] = {"name": "Первый", "remote": "git.example/one", "policy": "export"}
    a.store.append([event(cfg), event(cfg, "Stop", turn_id="t1")])
    record(a.store, cfg, "p1", "s1", report)
    mock = MockNotion()
    with serve(mock.app) as url:
        p = publisher(cfg, a.store, url)
        assert p.publish()["projects"] == 1
        assert set(p.sources) == set(COLLECTIONS)
        count = len(mock.pages)
        stable = a.store.get_meta("notion:page:project:p1")["id"]
        p.publish()
        assert len(mock.pages) == count
        assert a.store.get_meta("notion:page:project:p1")["id"] == stable
        # New observed event updates stable state, does not create another project.
        a.store.append([event(cfg, "Interrupt", turn_id="t1")])
        p.publish()
        assert a.store.get_meta("notion:page:project:p1")["id"] == stable
    rows = [p for p in mock.pages.values() if "Chronicle Key" in p["properties"]]
    assert any("Unknown" in json.dumps(row, ensure_ascii=False) for row in rows)
    assert all("prompt" not in json.dumps(row) for row in rows)


def test_ambiguous_create_reconciles_after_restart(cfg):
    a = Agent(cfg)
    mock = MockNotion()
    mock.fail_after_create = True
    with serve(mock.app) as url:
        p = publisher(cfg, a.store, url)
        with pytest.raises(TransportError):
            p.ensure_root()
        assert len(mock.pages) == 1
        p = publisher(cfg, a.store, url)
        p.ensure_root()
        assert len(mock.pages) == 1
        assert len(mock.databases) == 7


def test_uncertain_absent_never_blindly_recreates(cfg):
    a = Agent(cfg)
    a.store.set_meta("notion:uncertain:root:parent", True)
    mock = MockNotion()
    with serve(mock.app) as url:
        with pytest.raises(UncertainWrite):
            publisher(cfg, a.store, url).ensure_root()
    assert not mock.pages


def test_notion_retry_after_is_persistent(cfg):
    a = Agent(cfg)
    mock = MockNotion()
    mock.rate_limit = True
    with serve(mock.app) as url:
        p = publisher(cfg, a.store, url)
        with pytest.raises(TransportError) as exc:
            p.ensure_root()
        assert exc.value.retry_after == 120
        assert a.store.get_meta("notion:retry_at") > time.time() + 110
        before = len(mock.calls)
        with pytest.raises(TransportError):
            publisher(cfg, a.store, url).ensure_root()
        assert len(mock.calls) == before


def test_local_project_is_not_published(cfg):
    a = Agent(cfg)
    cfg["projects"]["p1"] = {"name": "private", "remote": "", "policy": "local"}
    a.store.append([event(cfg)])
    mock = MockNotion()
    with serve(mock.app) as url:
        assert publisher(cfg, a.store, url).publish()["projects"] == 0
    assert len(mock.pages) == 1  # empty observatory only; no project data


@pytest.mark.parametrize("with_legacy", [True, False])
@pytest.mark.parametrize("status", ["Passed", "Failed", "Unknown"])
def test_current_state_unifies_test_sources_without_promoting_claims(cfg, with_legacy, status):
    from fip_helpers import event as external_event
    from fip_helpers import grant, test_result

    from chronicle.memory_service import MemoryService

    a = Agent(cfg)
    cfg["projects"]["game-one"] = {"name": "Synthetic", "remote": "", "policy": "export"}
    cfg["fip_notion_projects"] = ["game-one"]
    if with_legacy:
        legacy = event(cfg, "PostToolUse", project="game-one")
        legacy["payload"].update(
            test_runner="pytest", test_status="Passed", execution_status="completed", exit_code=0
        )
        a.store.append([legacy])
    memory = MemoryService(a.store)
    source = external_event()
    memory.execute("append_event", {"record": source, "idempotency_key": "source"}, grant())
    result = test_result(
        source["record_id"],
        status=status,
        execution="started" if status == "Unknown" else "completed",
        code=None if status == "Unknown" else int(status == "Failed"),
    )
    memory.execute("register_test_result", {"record": result, "idempotency_key": "test"}, grant())
    mock = MockNotion()
    with serve(mock.app) as url:
        p = publisher(cfg, a.store, url)
        p.publish()
        page = a.store.get_meta("notion:page:project:game-one")["id"]
        count = len(mock.pages)
        p.publish()
        assert a.store.get_meta("notion:page:project:game-one")["id"] == page
        assert len(mock.pages) == count
    content = "\n".join(
        t["text"]["content"]
        for b in mock.blocks[page]
        for t in b.get("paragraph", {}).get("rich_text", [])
    )
    assert "## Кратко" in content
    assert f"{status} [agent_reported; FIP]" in content
    assert result["record_id"] in content
    assert "Нет подтверждённых завершённых test runs" not in content
    if with_legacy:
        assert "Passed [observed; legacy]" in content
        assert legacy["event_id"] in content


def test_fip_projection_requires_opt_in_and_preserves_stable_state(cfg):
    from fip_helpers import event as external_event
    from fip_helpers import grant

    from chronicle.memory_service import MemoryService

    a = Agent(cfg)
    memory = MemoryService(a.store)
    e = external_event(summary="WORLD FORGE game design discovery")
    memory.execute("append_event", {"record": e, "idempotency_key": "fip-notion"}, grant())
    cfg["projects"]["game-one"] = {"name": "Forge", "remote": "", "policy": "export"}
    mock = MockNotion()
    with serve(mock.app) as url:
        p = publisher(cfg, a.store, url)
        assert p.publish()["projects"] == 0
        cfg["fip_notion_projects"] = ["game-one"]
        assert p.publish()["projects"] == 1
        before = a.store.get_meta("notion:page:project:game-one")["id"]
        assert p.publish()["projects"] == 1
        assert a.store.get_meta("notion:page:project:game-one")["id"] == before
        assert "WORLD FORGE" in json.dumps(mock.pages)


def test_existing_observatory_preserves_user_content(cfg):
    from chronicle.notion import prop

    a = Agent(cfg)
    mock = MockNotion()
    root = "3fe99aa2-eb7b-815b-a30e-d0a315146484"
    mock.pages[root] = {
        "id": root,
        "properties": {"title": prop("title", "CODEX CHRONICLE — Development Observatory")},
    }
    original = {"id": "user-heading", "type": "heading_2", "heading_2": {"rich_text": []}}
    mock.blocks[root] = [original]
    cfg.update(notion_parent=root, notion_existing_root=True, allow_loopback_http=True)
    with serve(mock.app) as url:
        p = Publisher(a.store, cfg, "test-notion", url + "/v1", interval=0)
        p.ensure_root()
        p.ensure_root()
    assert p.root_id == root
    assert len(mock.pages) == 1
    assert len(mock.databases) == 7
    assert mock.blocks[root][0] == original
    assert not any(method == "PATCH" and path == "pages/" + root for method, path, _ in mock.calls)
