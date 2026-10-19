"""Accelerated 13h history, not a claim of 13h wall-clock soak testing."""

import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from chronicle.config import initialize, save
from chronicle.events import normalize
from chronicle.hook import capture
from chronicle.state import build_state
from chronicle.store import Store


def main():
    with tempfile.TemporaryDirectory(prefix="chronicle-load-") as tmp:
        root = Path(tmp)
        cfg = initialize(root / "local")
        cfg["autostart"] = False
        save(cfg)
        latencies = []
        for i in range(100):
            started = time.perf_counter()
            capture(
                {
                    "cwd": tmp,
                    "hook_event_name": "PostToolUse",
                    "session_id": "perf",
                    "turn_id": "t",
                    "tool_use_id": f"call-{i}",
                    "tool_name": "Bash",
                },
                cfg,
            )
            latencies.append((time.perf_counter() - started) * 1000)
        process_latencies = []
        for _ in range(25):
            started = time.perf_counter()
            subprocess.run(
                [sys.executable, "-m", "chronicle.hook"],
                input=json.dumps(
                    {"cwd": tmp, "hook_event_name": "Stop", "session_id": "process"}
                ).encode(),
                capture_output=True,
                env={**os.environ, "CHRONICLE_HOME": cfg["home"]},
                check=True,
            )
            process_latencies.append((time.perf_counter() - started) * 1000)
        store = Store(root / "load.db")
        start = dt.datetime.now(dt.UTC) - dt.timedelta(hours=13)
        total = 25000
        started = time.perf_counter()
        for offset in range(0, total, 100):
            batch = []
            for n in range(offset, min(offset + 100, total)):
                machine = n % 8
                local_cfg = {**cfg, "computer_id": f"machine-{machine}"}
                e = normalize(
                    {
                        "hook_event_name": "PostToolUse",
                        "session_id": f"session-{machine}",
                        "tool_use_id": f"call-{n}",
                        "tool_name": "Bash",
                        "turn_id": "long",
                    },
                    local_cfg,
                )
                e.update(
                    project_id="shared-project",
                    worktree_id=f"worktree-{machine}",
                    project={"name": "Load Probe", "remote": "example.org/load"},
                    occurred_at=(start + dt.timedelta(seconds=13 * 3600 * n / total)).isoformat(),
                )
                batch.append(e)
            store.append(batch)
            store.append(batch)  # transport replay
        insert_seconds = time.perf_counter() - started
        started = time.perf_counter()
        state = build_state(store.events())
        projection_seconds = time.perf_counter() - started
        assert store.stats()["total"] == total and len(state["sessions"]) == 8
        result = {
            "events": total,
            "replayed_deliveries": total,
            "computers": 8,
            "simulated_history_hours": 13,
            "wall_clock_soak_hours": 0,
            "insert_and_replay_seconds": round(insert_seconds, 3),
            "projection_seconds": round(projection_seconds, 3),
            "hook_capture_ms_p50": round(statistics.median(latencies), 3),
            "hook_capture_ms_p95": round(sorted(latencies)[94], 3),
            "hook_process_ms_p50": round(statistics.median(process_latencies), 3),
            "hook_process_ms_p95": round(sorted(process_latencies)[23], 3),
            "sqlite_bytes": (root / "load.db").stat().st_size,
            "note": "No real 13h soak; subprocess timing includes interpreter startup. No relative Codex throughput claim.",
        }
    Path("evidence/load-probe.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
