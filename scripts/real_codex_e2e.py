"""Explicit real-Codex acceptance probe; uses existing local Codex authentication.
Only synthetic temporary projects. Does not call Notion or publish data externally.
"""

import concurrent.futures
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from chronicle.config import initialize, save
from chronicle.store import Store


def run_one(base, index):
    cwd = base / f"project-{index}"
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
            f"https://example.org/chronicle/probe-{index}.git",
        ],
        check=True,
    )
    cfg = initialize(base / f"machine-{index}")
    cfg["autostart"] = True
    save(cfg)
    prompt = "Acceptance probe in this synthetic empty repository. Create check.py containing assert 2 + 2 == 4, then execute it with python. Do not use subagents or network tools. Finish with a short Russian report stating the observed result."
    started = time.monotonic()
    try:
        r = subprocess.run(
            [
                "codex",
                "exec",
                "--json",
                "--ephemeral",
                "--dangerously-bypass-hook-trust",
                "--sandbox",
                "workspace-write",
                "-C",
                str(cwd),
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "CHRONICLE_HOME": cfg["home"]},
            check=False,
        )
        result = {
            "index": index,
            "exit_code": r.returncode,
            "seconds": round(time.monotonic() - started, 2),
            "file_created": (cwd / "check.py").exists(),
        }
        # No full model output/transcript is persisted.
        result["stream_event_types"] = sorted(
            {
                json.loads(line).get("type", "unknown")
                for line in r.stdout.splitlines()
                if line.startswith("{")
            }
        )
        result["stderr_categories"] = {
            "hook_failure": "hook failed" in r.stderr.lower(),
            "authentication_error": "unauthorized" in r.stderr.lower(),
        }
    except subprocess.TimeoutExpired:
        result = {"index": index, "error": "timeout", "seconds": 180}
    for _ in range(10):
        if (Path(cfg["home"]) / "events.db").exists():
            time.sleep(0.2)
            break
        time.sleep(0.2)
    store = Store(Path(cfg["home"]) / "events.db")
    events = store.events()
    result.update(
        observed_events=len(events),
        kinds=sorted({e["kind"] for e in events}),
        projects=sorted({e["project_id"] for e in events}),
        sessions=sorted({e["session_id"] for e in events}),
        auto_worker_health=(Path(cfg["home"]) / "agent-health.json").exists(),
    )
    # Stop the dedicated synthetic-probe worker via its health PID.
    health_path = Path(cfg["home"]) / "agent-health.json"
    if health_path.exists():
        import signal

        health = json.loads(health_path.read_text())
        if health.get("pid"):
            os.kill(health["pid"], signal.SIGTERM)
    return result


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="chronicle-codex-") as tmp:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda i: run_one(Path(tmp), i), range(2)))
    output = {
        "probe": "real_codex_cli",
        "results": results,
        "note": "Real CLI hooks only; external Notion acceptance is separate.",
    }
    Path("evidence/real-codex.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(output, ensure_ascii=False))
