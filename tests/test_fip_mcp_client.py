import asyncio
import os
import sys

from conftest import serve
from fip_helpers import event, grant
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chronicle.collector import create_app
from chronicle.config import atomic_json
from chronicle.contracts import validate
from chronicle.fip_client import FipClient
from chronicle.transport import TransportError


def test_offline_queue_survives_restart_lost_ack_and_preserves_order(tmp_path, monkeypatch):
    app = create_app(tmp_path / "server.db", [grant()])
    with serve(app) as url:
        path = tmp_path / "outbox.db"
        client = FipClient(url, "agent-a", path, "stable-node", True)
        original_send = client._send
        calls = []

        def offline(op, args):
            calls.append(args["record"]["record_id"])
            raise TransportError()

        monkeypatch.setattr(client, "_send", offline)
        first, second = event(summary="First experiment"), event(summary="Second experiment")
        r1 = client.call("append_event", {"record": first, "idempotency_key": "first"})
        r2 = client.call("append_event", {"record": second, "idempotency_key": "second"})
        validate("QueuedWriteResponse", r1)
        assert r1["data"]["accepted"] is False
        assert r2["status"] == "queued"
        assert calls == [first["record_id"]]  # dependent writes cannot jump the queue
        assert client.status()["pending"] == 2
        restarted = FipClient(url, "agent-a", path, "stable-node", True)
        assert restarted.flush(force=True)["acknowledged"] == 2
        assert len(app.state.memory.ledger.rows()) == 2
        # Simulate accepted write with lost response, persisted queue retries original key.
        third = event(summary="Third experiment")

        def lose_ack(op, args):
            original_send(op, args)
            raise TransportError()

        monkeypatch.setattr(client, "_send", lose_ack)
        assert (
            client.call("append_event", {"record": third, "idempotency_key": "third"})["status"]
            == "queued"
        )
        assert restarted.flush(force=True)["acknowledged"] == 1
        assert len(app.state.memory.ledger.rows()) == 3


def test_grant_rotation_revocation_and_reload_without_restart(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    old = grant("old-token")
    atomic_json(path, [old])
    monkeypatch.setenv("CHRONICLE_AUTH_FILE", str(path))
    app = create_app(tmp_path / "server.db")
    from fastapi.testclient import TestClient

    c = TestClient(app)
    endpoint = "/v1/capabilities"
    assert c.get(endpoint, headers={"Authorization": "Bearer old-token"}).status_code == 200
    new = grant("new-token")
    atomic_json(path, [{**old, "revoked": True}, new])
    assert c.get(endpoint, headers={"Authorization": "Bearer old-token"}).status_code == 401
    assert c.get(endpoint, headers={"Authorization": "Bearer new-token"}).status_code == 200
    path.write_text("broken JSON")
    assert c.get(endpoint, headers={"Authorization": "Bearer new-token"}).status_code == 503


def test_mcp_real_stdio_sdk_roundtrip_and_write_then_other_reader(tmp_path):
    app = create_app(tmp_path / "server.db", [grant(), grant("reader-b", "reader-b", ["read"])])
    with serve(app) as url:

        async def scenario():
            env = {
                **os.environ,
                "CHRONICLE_API_URL": url,
                "CHRONICLE_API_TOKEN": "agent-a",
                "CHRONICLE_CLIENT_ID": "mcp-agent-a",
                "CHRONICLE_FIP_OUTBOX": str(tmp_path / "mcp.db"),
                "CHRONICLE_ALLOW_LOOPBACK_HTTP": "1",
                "CHRONICLE_MCP_WRITE_ENABLED": "1",
            }
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "chronicle.mcp_server"], env=env
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    assert init.serverInfo.name == "chronicler-fip-v1"
                    tools = await session.list_tools()
                    assert len(tools.tools) == 14
                    caps = await session.call_tool("get_capabilities", {})
                    assert not caps.isError
                    validate("CapabilityDescriptor", caps.structuredContent)
                    e = event(summary="World Forge deterministic simulation result from MCP")
                    result = await session.call_tool(
                        "append_event", {"record": e, "idempotency_key": "mcp-test"}
                    )
                    assert not result.isError, result
                    validate("append_eventResponse", result.structuredContent)
                    denial = await session.call_tool("get_project_state", {"project_id": "private"})
                    assert denial.isError
                    validate("ApiError", denial.structuredContent)
            readonly_env = {
                **env,
                "CHRONICLE_API_TOKEN": "reader-b",
                "CHRONICLE_MCP_WRITE_ENABLED": "0",
            }
            readonly_params = StdioServerParameters(
                command=sys.executable, args=["-m", "chronicle.mcp_server"], env=readonly_env
            )
            async with stdio_client(readonly_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert len(tools.tools) == 11
                    assert "append_event" not in {t.name for t in tools.tools}
                    denial = await session.call_tool(
                        "append_event", {"record": e, "idempotency_key": "denied"}
                    )
                    assert denial.isError
            reader = FipClient(url, "reader-b", tmp_path / "reader.db", allow_loopback_http=True)
            found = reader.call(
                "search_knowledge", {"project_id": "game-one", "query": "deterministic MCP"}
            )
            assert found["data"]["items"][0]["source_event_ids"] == [e["record_id"]]

        asyncio.run(scenario())
