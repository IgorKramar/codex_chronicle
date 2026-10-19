from concurrent.futures import ThreadPoolExecutor

from conftest import event, grant
from fastapi.testclient import TestClient

from chronicle.collector import create_app


def setup(cfg, tmp_path):
    app = create_app(
        tmp_path / "collector.db",
        [
            grant("write", ["write"], cfg["computer_id"]),
            grant("read", ["read"]),
            grant("limited", ["read"], projects=["p2"]),
        ],
    )
    return app, TestClient(app)


def test_auth_scopes_and_ingest(cfg, tmp_path):
    app, c = setup(cfg, tmp_path)
    e = event(cfg)
    assert c.post("/v1/events", json={"events": [e]}).status_code == 401
    assert (
        c.post(
            "/v1/events", json={"events": [e]}, headers={"Authorization": "Bearer read"}
        ).status_code
        == 403
    )
    headers = {"Authorization": "Bearer write"}
    assert c.post("/v1/events", json={"events": [e]}, headers=headers).json()["accepted"] == [
        e["event_id"]
    ]
    assert c.post("/v1/events", json={"events": [e]}, headers=headers).status_code == 200
    assert app.state.store.stats()["total"] == 1
    assert c.get("/v1/projects", headers=headers).status_code == 403
    assert (
        c.get("/v1/projects/p1/state", headers={"Authorization": "Bearer limited"}).status_code
        == 404
    )
    e["computer_id"] = "other"
    assert c.post("/v1/events", json={"events": [e]}, headers=headers).status_code == 403


def test_api_contract(cfg, tmp_path):
    app, c = setup(cfg, tmp_path)
    app.state.store.append([event(cfg)], True)
    h = {"Authorization": "Bearer read"}
    schema = c.get("/openapi.json").json()
    names = {
        operation["operationId"]
        for route in schema["paths"].values()
        for operation in route.values()
        if isinstance(operation, dict)
    }
    assert {
        "list_projects",
        "get_project_state",
        "list_active_sessions",
        "get_recent_activity",
        "get_decisions",
        "get_open_issues",
        "get_daily_summary",
    } <= names
    assert c.get("/v1/summaries/daily?date=bad", headers=h).status_code == 422
    assert len(c.get("/v1/projects", headers=h).json()) == 1
    assert len(c.get("/v1/sessions/active", headers=h).json()) == 1
    assert c.get("/v1/activity?limit=0", headers=h).status_code == 422


def test_concurrent_agents_collector(cfg, tmp_path):
    app, c = setup(cfg, tmp_path)
    events = [event(cfg, session=f"s{i}") for i in range(30)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda e: c.post(
                    "/v1/events", json={"events": [e]}, headers={"Authorization": "Bearer write"}
                ),
                events * 2,
            )
        )
    assert all(r.status_code == 200 for r in responses)
    assert app.state.store.stats()["total"] == 30


def test_size_and_bad_payload(cfg, tmp_path):
    app, c = setup(cfg, tmp_path)
    h = {"Authorization": "Bearer write"}
    assert c.post("/v1/events", content=b"x" * 1_000_001, headers=h).status_code == 413
    assert c.post("/v1/events", json={"events": [{}]}, headers=h).status_code == 422
