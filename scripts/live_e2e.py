"""Opt-in real Codex -> Collector -> Notion -> MCP -> independent reader probe.

Synthetic projects only; dedicated Notion integration required. Keeps evidence,
private databases and published synthetic pages for inspection. No mock fallback.
"""

import argparse
import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from real_codex_e2e import run_one

from chronicle.collector import create_app
from chronicle.config import atomic_json, load
from chronicle.fip_client import FipClient
from chronicle.memory_service import evidence, record_base
from chronicle.notion import Publisher
from chronicle.store import Store
from chronicle.transport import request


async def read_mcp(url, token, directory, pid):
    env = {
        **os.environ,
        "CHRONICLE_API_URL": url,
        "CHRONICLE_API_TOKEN": token,
        "CHRONICLE_ALLOW_LOOPBACK_HTTP": "1",
        "CHRONICLE_FIP_OUTBOX": str(directory / "reader-mcp.db"),
        "CHRONICLE_MCP_WRITE_ENABLED": "0",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chronicle.mcp_server"], env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_project_state", {"project_id": pid})
            assert not result.isError
            assert result.structuredContent["data"]["source_ids"]
            return result.structuredContent["data"]["source_ids"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="Authorize real Codex runs and synthetic Notion writes",
    )
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Explicit --run-live is required; no mock fallback")
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(directory.iterdir()):
        parser.error("Use a new empty private directory")
    cfg = load()
    report = {
        "status": "Running",
        "steps": {},
        "chatgpt_readback": "pending separate connector verification",
    }
    server = thread = None
    try:
        if not (
            os.environ.get("NOTION_TOKEN")
            or os.environ.get("NOTION_TOKEN_FILE")
            or cfg.get("notion_token_file")
        ):
            report.update(
                status="Blocked", reason="Dedicated Notion integration token is not configured"
            )
            return
        cfg.update(notion_parent="3fe99aa2-eb7b-815b-a30e-d0a315146484", notion_existing_root=True)
        # Read-only permission preflight before any Codex work or remote writes.
        Publisher(Store(directory / "preflight.db"), cfg).call(
            "GET", "/pages/" + cfg["notion_parent"]
        )
        report["steps"]["notion_read_access"] = "Passed"
        probes = [run_one(directory, i) for i in range(2)]
        report["steps"]["real_codex"] = probes
        if any(
            p.get("exit_code") != 0 or not p.get("file_created") or not p.get("observed_events")
            for p in probes
        ):
            report.update(
                status="Blocked",
                reason="Real Codex did not complete the synthetic task with captured hooks",
            )
            return
        events = []
        for i in range(2):
            events.extend(Store(directory / f"machine-{i}" / "events.db").events())
        projects = sorted({e["project_id"] for e in events})
        assert len(projects) == 2
        writer, reader = os.urandom(32).hex(), os.urandom(32).hex()
        grants = [
            {
                "sha256": hashlib.sha256(writer.encode()).hexdigest(),
                "computer_id": machine,
                "scopes": ["write"],
                "projects": projects,
            }
            for machine in {e["computer_id"] for e in events}
        ]
        # Legacy credentials are bound to one computer; send each batch separately.
        machine_tokens = {}
        for g in grants:
            token = os.urandom(32).hex()
            g["sha256"] = hashlib.sha256(token.encode()).hexdigest()
            machine_tokens[g["computer_id"]] = token
        grants += [
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "principal_id": actor,
                "agent_id": actor,
                "scopes": scopes,
                "projects": projects,
                "allow_content": actor == "acceptance-writer",
            }
            for token, actor, scopes in [
                (writer, "acceptance-writer", ["read", "write"]),
                (reader, "independent-reader", ["read"]),
            ]
        ]
        app = create_app(directory / "collector.db", grants=grants)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started
        for machine, token in machine_tokens.items():
            batch = [e for e in events if e["computer_id"] == machine]
            headers = {"Authorization": "Bearer " + token}
            first = request("POST", url + "/v1/events", {"events": batch}, headers)
            assert request("POST", url + "/v1/events", {"events": batch}, headers) == first
        report["steps"]["collector_and_replay"] = {"events": len(events), "projects": projects}
        client = FipClient(url, writer, directory / "writer.db", "acceptance-computer", True)
        pid = projects[0]
        source = next(e["event_id"] for e in events if e["project_id"] == pid)
        decision = {
            **record_base(
                "acceptance-decision-" + source,
                pid,
                agent_id="acceptance-writer",
                provenance="agent_reported",
                status="Proposed",
            ),
            "decision_id": "acceptance-isolation",
            "category": "architecture",
            "title": "Изоляция acceptance-проверки",
            "problem": "Проверить интеграцию без рабочих данных",
            "alternatives": ["отдельный синтетический проект"],
            "choice": "синтетические проекты",
            "rationale": "Реальный Codex и реальные hooks без экспорта частных репозиториев",
            "consequences": ["Этот результат не подтверждает готовность рабочих проектов"],
            "source_event_ids": [source],
            "evidence": [evidence(pid, source)],
        }
        operation = {"record": decision, "idempotency_key": "acceptance-decision"}
        ack = client.call("register_decision", operation)
        assert client.call("register_decision", operation) == ack
        # Independently execute the generated synthetic check; file existence is not a passed test.
        project_index = next(i for i in range(2) if pid in probes[i]["projects"])
        check_file = directory / f"project-{project_index}" / "check.py"
        safe_env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }
        execution = subprocess.run(
            [sys.executable, str(check_file)],
            cwd=check_file.parent,
            env=safe_env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        report["steps"]["independent_test_execution"] = {
            "exit_code": execution.returncode,
            "file_sha256": hashlib.sha256(check_file.read_bytes()).hexdigest(),
        }
        artifact_id = "acceptance-check-" + source
        artifact = {
            **record_base(
                "artifact-" + source,
                pid,
                agent_id="acceptance-writer",
                provenance="agent_reported",
                status="available",
            ),
            "artifact_id": artifact_id,
            "title": "Synthetic check.py",
            "uri": "urn:chronicler:acceptance:" + source,
            "artifact_type": "implementation",
            "sha256": report["steps"]["independent_test_execution"]["file_sha256"],
            "source_event_ids": [source],
        }
        client.call(
            "register_artifact", {"record": artifact, "idempotency_key": "acceptance-artifact"}
        )
        test = {
            **record_base(
                "test-" + source,
                pid,
                agent_id="acceptance-writer",
                provenance="agent_reported",
                status="Passed" if execution.returncode == 0 else "Failed",
            ),
            "test_id": "acceptance-check",
            "name": "python check.py",
            "runner": "python",
            "execution_status": "completed",
            "exit_code": execution.returncode,
            "summary": "Independent execution of the file generated by real Codex; no captured output exported",
            "source_event_ids": [source],
            "artifact_refs": [{"artifact_id": artifact_id, "record_id": artifact["record_id"]}],
            "evidence": [evidence(pid, source)],
        }
        client.call("register_test_result", {"record": test, "idempotency_key": "acceptance-test"})
        knowledge = {
            **record_base(
                "knowledge-" + source,
                pid,
                agent_id="acceptance-writer",
                provenance="agent_reported",
                status="active",
            ),
            "knowledge_id": "acceptance-outcome",
            "category": "testing",
            "title": "Результат реальной синтетической проверки",
            "text": f"python check.py завершился с exit_code={execution.returncode}; это отчёт harness, не доказательство готовности всего проекта.",
            "source_event_ids": [source],
            "evidence": [evidence(pid, test["record_id"], kind="test_result")],
        }
        client.call(
            "register_knowledge", {"record": knowledge, "idempotency_key": "acceptance-knowledge"}
        )
        if execution.returncode != 0:
            raise RuntimeError("Generated test did not pass")
        cfg["projects"] = {
            p: {"name": "Synthetic Codex acceptance " + p, "policy": "export", "remote": ""}
            for p in projects
        }
        cfg["fip_notion_projects"] = projects
        publisher = Publisher(app.state.store, cfg)
        publisher.publish()
        pages = {p: app.state.store.get_meta("notion:page:project:" + p) for p in projects}
        for page in pages.values():
            assert publisher.call("GET", "/pages/" + page["id"])["id"] == page["id"]
            assert list(publisher.pages("/blocks/" + page["id"] + "/children"))
        publisher.publish()
        assert pages == {p: app.state.store.get_meta("notion:page:project:" + p) for p in projects}
        report["steps"]["notion_write_read_replay"] = pages
        report["steps"]["mcp_read"] = asyncio.run(read_mcp(url, reader, directory, pid))
        independent = FipClient(url, reader, directory / "reader.db", allow_loopback_http=True)
        found = independent.call("get_decisions", {"project_id": pid})
        assert any(d["record_id"] == decision["record_id"] for d in found["data"]["items"])
        report["steps"]["independent_reader"] = "Passed"
        report["status"] = "AwaitingChatGPTReadback"
    except Exception as exc:
        report.update(status="Failed", error_type=type(exc).__name__)
        raise
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
        atomic_json(directory / "evidence.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
