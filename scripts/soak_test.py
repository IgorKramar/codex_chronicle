"""Real wall-clock durability probe. No accelerated clock or public listener.

Default run lasts 12 hours. --seconds <43200 is explicitly a smoke test.
State, synthetic credentials and SQLite files stay in an external private directory.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from chronicle.config import atomic_json
from chronicle.fip_client import FipClient
from chronicle.memory_service import record_base
from chronicle.transport import request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=43200)
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if args.seconds < 1 or args.interval <= 0:
        parser.error("positive duration and interval required")
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (directory / "status.json").exists():
        parser.error("Use a new directory; existing evidence must not be overwritten")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    token = uuid.uuid4().hex
    auth = directory / "auth.json"
    atomic_json(
        auth,
        [
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "principal_id": "soak-agent",
                "agent_id": "soak-agent",
                "scopes": ["read", "write"],
                "projects": ["synthetic-soak"],
                "allow_content": True,
            }
        ],
    )
    env = {
        **os.environ,
        "CHRONICLE_AUTH_FILE": str(auth),
        "CHRONICLE_DATABASE": str(directory / "collector.db"),
    }
    # A soak must never inherit a live Notion publisher or export real projects.
    for name in ("NOTION_PARENT", "NOTION_PARENT_PAGE_ID", "NOTION_TOKEN", "NOTION_TOKEN_FILE"):
        env.pop(name, None)
    log = (directory / "collector.log").open("ab")
    server = None

    def start_server():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "chronicle.collector:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        for _ in range(100):
            try:
                request("GET", url + "/healthz")
                return process
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError("Collector failed to start; inspect private log") from None
                time.sleep(0.1)
        process.terminate()
        raise RuntimeError("Collector startup timeout")

    started = time.monotonic()
    status = {
        "status": "Running",
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
        "target_seconds": args.seconds,
        "qualifies_for_12h": args.seconds >= 43200,
        "notion": "not tested; dedicated credential absent",
        "generated_events": 0,
        "restarts": 0,
        "outage_queue_checks": 0,
        "samples": 0,
    }
    client = FipClient(url, token, directory / "outbox.db", "soak-computer", True)
    try:
        server = start_server()
        while time.monotonic() - started < args.seconds:
            cycle = status["samples"]
            if cycle % 20 == 5:
                server.terminate()
                server.wait(timeout=10)
                server = None
            rid = str(uuid.uuid4())
            body = {
                **record_base(
                    rid,
                    "synthetic-soak",
                    agent_id="soak-agent",
                    status="recorded",
                    provenance="agent_reported",
                ),
                "event_id": rid,
                "event_type": "soak_checkpoint",
                "category": "testing",
                "summary": "Synthetic real-time durability checkpoint",
                "knowledge": [],
                "test_results": [],
            }
            call = {"record": body, "idempotency_key": rid}
            answer = client.call("append_event", call)
            if server is None:
                assert answer["status"] == "queued"
                status["outage_queue_checks"] += 1
                server = start_server()
                status["restarts"] += 1
            client.flush(force=True)
            # Reopen persistent outbox, resend same operation and confirm original acknowledgement.
            client = FipClient(url, token, directory / "outbox.db", "soak-computer", True)
            replay = client.call("append_event", call)
            assert replay["data"].get("accepted") is True
            status["generated_events"] += 1
            status.update(
                samples=cycle + 1,
                elapsed_seconds=round(time.monotonic() - started, 3),
                cpu_seconds=round(sum(os.times()[:4]), 3),
                updated_at=dt.datetime.now(dt.UTC).isoformat(),
            )
            try:
                import resource

                status["peak_rss_platform_units"] = resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
            except ImportError:
                status["peak_rss_platform_units"] = None
            atomic_json(directory / "status.json", status)
            time.sleep(min(args.interval, max(0, args.seconds - (time.monotonic() - started))))
        summary = client.call(
            "get_daily_summary", {"project_id": "synthetic-soak", "since": status["started_at"]}
        )
        assert summary["data"]["counts"]["events"] == status["generated_events"]
        elapsed = time.monotonic() - started
        status.update(
            status="Passed" if elapsed >= 43200 else "SmokePassed",
            elapsed_seconds=round(elapsed, 3),
            finished_at=dt.datetime.now(dt.UTC).isoformat(),
            duplicate_free=True,
        )
    except Exception as exc:
        status.update(status="Failed", error_type=type(exc).__name__)
        raise
    finally:
        atomic_json(directory / "status.json", status)
        if server and server.poll() is None:
            server.terminate()
            server.wait(timeout=10)
        log.close()
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
