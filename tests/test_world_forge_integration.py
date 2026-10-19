"""Required scenario: REST planner -> work -> API writes -> independent MCP reader."""

import asyncio
import os
import sys

from conftest import serve
from fip_helpers import artifact, decision, event, grant, knowledge
from fip_helpers import test_result as make_test
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chronicle.collector import create_app
from chronicle.contracts import validate
from chronicle.fip_client import FipClient
from chronicle.transport import request


def test_external_agents_exchange_context_results_and_primary_evidence(tmp_path):
    grants = [grant(scopes=["read", "write", "decide"]), grant("reviewer", "reviewer", ["read"])]
    app = create_app(tmp_path / "server.db", grants)
    with serve(app) as url:
        planner = FipClient(url, "agent-a", tmp_path / "planner.db", "forge-planner", True)
        bootstrap = event(
            category="game_design",
            summary="Use deterministic combat tick for replayable game simulations",
        )
        planner.call("append_event", {"record": bootstrap, "idempotency_key": "bootstrap"})
        d = decision(bootstrap["record_id"], status="Accepted")
        planner.call("register_decision", {"record": d, "idempotency_key": "accepted-design"})
        history = planner.call("get_project_history", {"project_id": "game-one"})
        prior = planner.call("get_decisions", {"project_id": "game-one", "status": "Accepted"})
        assert history["data"]["items"] and prior["data"]["items"][0]["choice"] == "fixed tick"
        # Real independent work; Chronicle only records the result, never runs submitted code.
        replay_a = [((t * 17) % 101) for t in range(100)]
        replay_b = [((t * 17) % 101) for t in range(100)]
        assert replay_a == replay_b
        output = event(
            summary="WORLD FORGE combat replay experiment: 100 deterministic ticks matched"
        )
        output["knowledge"] = [
            knowledge(
                output["record_id"],
                text="Combat replay mechanic implemented; 100 deterministic ticks matched",
            )
        ]
        output["test_results"] = [make_test(output["record_id"])]
        planner.call("append_event", {"record": output, "idempotency_key": "combat-experiment"})
        link = artifact(output["record_id"])
        planner.call("register_artifact", {"record": link, "idempotency_key": "combat-artifact"})

        async def read_as_other_agent():
            env = {
                **os.environ,
                "CHRONICLE_API_URL": url,
                "CHRONICLE_API_TOKEN": "reviewer",
                "CHRONICLE_ALLOW_LOOPBACK_HTTP": "1",
                "CHRONICLE_MCP_WRITE_ENABLED": "0",
                "CHRONICLE_FIP_OUTBOX": str(tmp_path / "reviewer.db"),
            }
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "chronicle.mcp_server"], env=env
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    found = await session.call_tool(
                        "search_knowledge", {"project_id": "game-one", "query": "combat replay"}
                    )
                    assert not found.isError
                    records = found.structuredContent["data"]["items"]
                    assert any(output["record_id"] in r["source_event_ids"] for r in records)
                    tests = await session.call_tool("get_test_results", {"project_id": "game-one"})
                    assert (
                        tests.structuredContent["data"]["items"][0]["provenance"]
                        == "agent_reported"
                    )
                    artifacts = await session.call_tool("get_artifacts", {"project_id": "game-one"})
                    assert artifacts.structuredContent["data"]["items"][0]["uri"] == link["uri"]
            primary = request(
                "GET",
                url + "/v1/memory/projects/game-one/records/" + output["record_id"],
                headers={"Authorization": "Bearer reviewer"},
            )
            validate("RecordLookupResponse", primary)
            assert primary["data"]["record"]["summary"] == output["summary"]

        asyncio.run(read_as_other_agent())
