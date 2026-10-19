"""Public operations are exercised through HTTP, not internal table access."""

from fastapi.testclient import TestClient
from fip_helpers import event, grant, knowledge
from fip_helpers import test_result as result_record

from chronicle.collector import create_app
from chronicle.contracts import validate


def test_independent_agent_registers_and_discovers_memory(tmp_path):
    app = create_app(
        tmp_path / "collector.db", grants=[grant(), grant("reader", "reader", ["read"])]
    )
    with TestClient(app) as client:
        writer = {"Authorization": "Bearer agent-a", "Idempotency-Key": "source"}
        reader = {"Authorization": "Bearer reader"}
        source = event()
        assert client.post("/v1/memory/events", json=source, headers=writer).status_code == 200
        for operation, path, record in [
            ("register_knowledge", "knowledge", knowledge(source["event_id"])),
            ("register_test_result", "test-results", result_record(source["event_id"])),
        ]:
            writer["Idempotency-Key"] = operation
            first = client.post("/v1/memory/" + path, json=record, headers=writer)
            assert first.status_code == 200, first.text
            validate(operation + "Response", first.json())
            assert (
                client.post("/v1/memory/" + path, json=record, headers=writer).json()
                == first.json()
            )
            assert (
                client.post(
                    "/v1/memory/" + path,
                    json=record,
                    headers={**reader, "Idempotency-Key": "denied"},
                ).status_code
                == 403
            )
        activity = client.get(
            "/v1/memory/activity", headers=reader, params={"project_id": "game-one", "limit": 1}
        ).json()
        validate("get_recent_activityResponse", activity)
        assert activity["data"]["has_more"]
        summary = client.get(
            "/v1/memory/summaries/daily", headers=reader, params={"project_id": "game-one"}
        ).json()
        validate("get_daily_summaryResponse", summary)
        assert summary["data"]["counts"]["events"] == 3
        assert summary["data"]["period_start"].endswith("+00:00")
        found = client.get(
            "/v1/memory/search",
            headers=reader,
            params={"project_id": "game-one", "query": "deterministic physics"},
        ).json()
        assert any(r["provenance"] == "agent_reported" for r in found["data"]["items"])
        tests = client.get("/v1/memory/projects/game-one/test-results", headers=reader).json()
        assert tests["data"]["items"][0]["status"] == "Passed"
        primary = tests["data"]["items"][0]["source_event_ids"][0]
        assert (
            client.get(
                "/v1/memory/projects/game-one/records/" + primary, headers=reader
            ).status_code
            == 200
        )
