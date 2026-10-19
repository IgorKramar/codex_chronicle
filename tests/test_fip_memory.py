import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import event as legacy_event
from fastapi.testclient import TestClient
from fip_helpers import artifact, base, decision, event, grant, knowledge, revision
from fip_helpers import test_result as make_test

from chronicle.collector import create_app
from chronicle.contracts import validate
from chronicle.memory_service import ApiFault, MemoryService
from chronicle.store import Store


@pytest.fixture
def service(tmp_path):
    return MemoryService(Store(tmp_path / "memory.db"))


def write(service, operation, record, actor=None, key=None):
    return service.execute(
        operation, {"record": record, "idempotency_key": key or str(uuid.uuid4())}, actor or grant()
    )


def test_cross_agent_workflow_context_decision_experiment_artifact_evidence(service):
    first = event(
        category="architecture", summary="Fixed tick supports deterministic game simulation"
    )
    first["project_context"] = {
        **base(status="active"),
        "name": "WORLD FORGE Demo",
        "description": "A simulation game",
        "current_goal": "Implement reproducible physics",
        "implemented": [],
        "open_questions": ["Replay accuracy"],
        "llm_summary": "",
        "source_ids": [],
    }
    write(service, "append_event", first)
    d = decision(first["record_id"], status="Accepted")
    write(service, "register_decision", d, grant(scopes=["read", "write", "decide"]))
    reader = grant("b", "agent-b", ["read", "write"])
    state = service.execute("get_project_state", {"project_id": "game-one"}, reader)
    assert state["data"]["name"] == "WORLD FORGE Demo"
    prior = service.execute(
        "get_decisions", {"project_id": "game-one", "status": "Accepted"}, reader
    )
    assert prior["data"]["items"][0]["choice"] == "fixed tick"
    # Agent performs its own real local experiment; memory service does not execute it.
    simulated = [i * 2 for i in range(20)]
    assert simulated == [i + i for i in range(20)]
    result = event(agent="agent-b", summary="Deterministic physics replay experiment passed")
    result["knowledge"] = [knowledge(result["record_id"], "agent-b")]
    result["test_results"] = [make_test(result["record_id"], "agent-b")]
    write(service, "append_event", result, reader)
    link = artifact(result["record_id"], "agent-b")
    write(service, "register_artifact", link, reader)
    final_reader = grant("c", "agent-c", ["read"])
    found = service.execute(
        "search_knowledge",
        {"project_id": "game-one", "query": "deterministic physics"},
        final_reader,
    )
    assert any(r["source_event_ids"] == [result["record_id"]] for r in found["data"]["items"])
    tests = service.execute("get_test_results", {"project_id": "game-one"}, final_reader)
    assert tests["data"]["items"][0]["status"] == "Passed"
    assert tests["data"]["items"][0]["provenance"] == "agent_reported"
    artifacts = service.execute("get_artifacts", {"project_id": "game-one"}, final_reader)
    assert artifacts["data"]["items"][0]["source_event_ids"] == [result["record_id"]]
    history = service.execute("get_project_history", {"project_id": "game-one"}, final_reader)
    assert result["record_id"] in {r["record_id"] for r in history["data"]["items"]}


def test_write_idempotence_conflict_restart_and_parallel(service):
    e = event()
    key = "stable-key"
    result = write(service, "append_event", e, key=key)
    reopened = MemoryService(Store(service.store.location))
    assert write(reopened, "append_event", e, key=key) == result
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: write(service, "append_event", e, key=key), range(20)))
    assert all(r == result for r in results)
    assert len(service.ledger.rows()) == 1
    changed = dict(e, summary="Different outcome")
    with pytest.raises(ApiFault) as error:
        write(service, "append_event", changed, key=key)
    assert error.value.status == 409


def test_revision_permissions_immutable_history_and_optimistic_concurrency(service):
    e = event()
    write(service, "append_event", e)
    proposed = decision(e["record_id"])
    write(service, "register_decision", proposed)
    accepted = revision(proposed)
    accepted["status"] = "Accepted"
    with pytest.raises(ApiFault) as error:
        write(service, "register_decision", accepted)
    assert error.value.status == 403
    privileged = grant(scopes=["read", "write", "decide"])
    write(service, "register_decision", accepted, privileged)
    stale = revision(proposed)
    with pytest.raises(ApiFault) as error:
        write(service, "register_decision", stale, privileged)
    assert error.value.status == 409
    foreign = revision(accepted, "agent-b")
    with pytest.raises(ApiFault):
        write(
            service,
            "register_decision",
            foreign,
            grant("b", "agent-b", ["read", "write", "decide"]),
        )
    history = service.execute("get_decisions", {"project_id": "game-one"}, grant())
    assert [r["status"] for r in history["data"]["items"]] == ["Proposed", "Accepted"]


def test_cross_project_scope_bad_evidence_and_test_claims(service):
    private = event(pid="private")
    write(service, "append_event", private, grant(projects=["private"]))
    d = decision(private["record_id"])
    with pytest.raises(ApiFault) as error:
        write(service, "register_decision", d)
    assert error.value.status == 404
    e = event()
    e["test_results"] = [make_test(e["record_id"], execution="started", code=None)]
    with pytest.raises(ApiFault):
        write(service, "append_event", e)
    assert len(service.ledger.rows(["game-one"])) == 0
    with pytest.raises(ApiFault) as error:
        service.execute("get_project_state", {"project_id": "private"}, grant())
    assert error.value.status == 404


def test_snapshot_cursor_byte_cap_and_filter_binding(service):
    for i in range(8):
        write(service, "append_event", event(summary=f"Event {i}"))
    first = service.execute("get_project_history", {"project_id": "game-one", "limit": 3}, grant())
    cursor = first["data"]["next_cursor"]
    write(service, "append_event", event(summary="Newer than snapshot"))
    seen = first["data"]["items"]
    while cursor:
        page = service.execute(
            "get_project_history", {"project_id": "game-one", "limit": 3, "cursor": cursor}, grant()
        )
        seen += page["data"]["items"]
        cursor = page["data"]["next_cursor"]
    assert len(seen) == 8 and len({r["record_id"] for r in seen}) == 8
    with pytest.raises(ApiFault):
        service.execute(
            "get_project_history",
            {
                "project_id": "game-one",
                "category": "failure",
                "cursor": first["data"]["next_cursor"],
            },
            grant(),
        )
    large = event(summary="a" * 3900)
    large["knowledge"] = [knowledge(large["record_id"], text="b" * 12000)]
    write(service, "append_event", large)
    page = service.execute(
        "get_project_history",
        {"project_id": "game-one", "limit": 100, "max_response_bytes": 8192},
        grant(),
    )
    assert len(json.dumps(page).encode()) <= 8192 and page["data"]["has_more"]


def test_search_semantics_and_secret_redaction(service):
    e = event(summary="Physics DETERMINISTIC experiment password=hunter2")
    write(service, "append_event", e)
    found = service.execute("search_knowledge", {"query": "physics deterministic"}, grant())
    assert found["data"]["items"]
    assert "hunter2" not in json.dumps(service.ledger.rows())
    assert not service.execute("search_knowledge", {"query": "physics unrelated"}, grant())["data"][
        "items"
    ]
    with pytest.raises(ApiFault):
        service.execute("search_knowledge", {"query": "a"}, grant())


def test_legacy_hooks_project_to_fip_without_migration(service, cfg):
    e = legacy_event(
        cfg, "PostToolUse", tool_input={"command": "pytest -q"}, tool_response={"exit_code": 0}
    )
    service.store.append([e], True)
    reader = grant(projects=["p1"])
    page = service.execute("get_test_results", {"project_id": "p1"}, reader)
    assert page["data"]["items"][0]["status"] == "Passed"
    assert page["data"]["items"][0]["provenance"] == "observed"
    sessions = service.execute("list_sessions", {}, reader)
    assert sessions["data"]["items"][0]["session_id"] == e["session_id"]


def test_http_errors_openapi_and_evidence_resolution(tmp_path):
    app = create_app(tmp_path / "db", [grant()])
    c = TestClient(app)
    headers = {"Authorization": "Bearer agent-a", "Idempotency-Key": "event-one"}
    e = event()
    reply = c.post("/v1/memory/events", json=e, headers=headers)
    assert reply.status_code == 200, reply.text
    validate("append_eventResponse", reply.json())
    assert c.get("/v1/memory/projects").status_code == 401
    validate("ApiError", c.get("/v1/memory/projects").json())
    cap = c.get("/v1/capabilities", headers=headers)
    validate("CapabilityDescriptor", cap.json())
    bad = c.get("/v1/capabilities", headers={**headers, "FIP-Version": "v2"})
    assert bad.status_code == 426
    validate("ApiError", bad.json())
    detail = c.get("/v1/memory/projects/game-one/records/" + e["record_id"], headers=headers)
    assert detail.status_code == 200, detail.text
    validate("RecordLookupResponse", detail.json())
    schema = c.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.1")
    assert "ProjectContext" in schema["components"]["schemas"]
    assert "/v1/projects" in schema["paths"]  # existing clients keep their route
    assert (
        c.post("/v1/memory/events", json=e, headers={"Authorization": "Bearer agent-a"}).status_code
        == 422
    )


def test_replay_cannot_bypass_agent_identity(service):
    e = event()
    write(service, "append_event", e, key="one")
    mismatched = {**grant(), "agent_id": "different-agent"}
    with pytest.raises(ApiFault) as error:
        write(service, "append_event", e, mismatched, key="one")
    assert error.value.status == 403


def test_private_and_read_only_boundaries_do_not_expose_records(service):
    e = event()
    write(service, "append_event", e)
    reader = grant("r", "reader", ["read"])
    with pytest.raises(ApiFault) as error:
        write(service, "append_event", event(agent="reader"), reader)
    assert error.value.status == 403
    foreign = grant("foreign", "foreign", ["read"], ["work-project"])
    assert service.execute("search_knowledge", {"query": "physics"}, foreign)["data"]["items"] == []
    assert service.execute("list_projects", {}, foreign)["data"]["items"] == []


def test_rejected_decision_search_and_failures(service):
    e = event()
    e["test_results"] = [make_test(e["record_id"], status="Failed", code=1)]
    write(service, "append_event", e)
    d = decision(e["record_id"], status="Rejected")
    d["rationale"] = "Variable simulation creates unstable gameplay"
    write(service, "register_decision", d)
    found = service.execute("search_knowledge", {"query": "unstable gameplay"}, grant())
    assert any(d["rationale"] in r["text"] for r in found["data"]["items"])
    failures = service.execute("get_failures", {"project_id": "game-one"}, grant())
    assert (
        failures["data"]["items"][0]["evidence"][0]["target_id"]
        == e["test_results"][0]["record_id"]
    )


def test_session_discovery_and_filters_for_external_events(service):
    e = event()
    write(service, "append_event", e)
    sessions = service.execute(
        "list_sessions", {"project_id": "game-one", "agent_id": "agent-a"}, grant()
    )
    assert sessions["data"]["items"][0]["status"] == "Unknown"
    detail = service.execute(
        "get_session_details",
        {"project_id": "game-one", "session_id": "session-agent-a", "agent_id": "agent-a"},
        grant(),
    )
    assert detail["data"]["evidence"][0]["target_id"] == e["record_id"]


def test_invalid_write_shapes_and_observation_spoofing(tmp_path):
    app = create_app(tmp_path / "db", [grant()])
    c = TestClient(app)
    headers = {"Authorization": "Bearer agent-a", "Idempotency-Key": "spoof"}
    for body in [[], {"api_version": "v2"}, {"api_version": "v1"}]:
        response = c.post("/v1/memory/events", json=body, headers=headers)
        assert response.status_code in {422, 426}
        validate("ApiError", response.json())
    e = event()
    e["provenance"] = "observed"
    response = c.post("/v1/memory/events", json=e, headers=headers)
    assert response.status_code == 403
    assert app.state.memory.ledger.rows() == []


def test_notion_outage_never_blocks_fip_reads_or_writes(tmp_path, monkeypatch):
    from chronicle.transport import TransportError

    def unavailable(*args):
        raise TransportError(503)

    monkeypatch.setattr("chronicle.notion.publish_store", unavailable)
    app = create_app(
        tmp_path / "db",
        [grant()],
        publisher_cfg={"home": str(tmp_path), "notion_parent": "unused", "publish_seconds": 1},
    )
    with TestClient(app) as c:
        e = event()
        headers = {"Authorization": "Bearer agent-a", "Idempotency-Key": "outage"}
        assert c.post("/v1/memory/events", json=e, headers=headers).status_code == 200
        assert c.get("/v1/memory/projects/game-one/state", headers=headers).status_code == 200
        assert c.get("/v1/memory/projects/game-one/history", headers=headers).json()["data"][
            "items"
        ]
    assert app.state.store.get_meta("publisher_error")["code"] == "TransportError"


def test_current_state_honours_archived_context_and_retracted_knowledge(service):
    first = event()
    context = {
        **base(),
        "name": "Game",
        "description": "Game context",
        "current_goal": "Replay",
        "implemented": [],
        "open_questions": [],
        "llm_summary": "",
        "source_ids": [],
    }
    mechanic = knowledge(first["record_id"])
    first["project_context"] = context
    first["knowledge"] = [mechanic]
    write(service, "append_event", first)
    assert service.execute("get_project_state", {"project_id": "game-one"}, grant())["data"][
        "implemented"
    ]
    second = event()
    second["project_context"] = {**revision(context), "status": "archived"}
    second["knowledge"] = [{**revision(mechanic), "status": "retracted"}]
    write(service, "append_event", second)
    current = service.execute("get_project_state", {"project_id": "game-one"}, grant())["data"]
    assert current["status"] == "archived"
    assert current["implemented"] == []
    assert len(service.ledger.rows()) == 6  # revisions preserved, never overwritten
