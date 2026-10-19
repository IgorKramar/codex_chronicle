"""Fast fail-open boundary. No network and no repository subprocesses."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, cast

from .config import atomic_json, load
from .events import normalize
from .privacy import excluded


def capture(raw, cfg):
    if cfg["paused"] or excluded(raw.get("cwd", "."), cfg):
        return None
    if cfg["mode"] == "Minimal" and raw.get("hook_event_name") in {
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
    }:
        return None
    event = normalize(raw, cfg)
    envelope = {"cwd": str(Path(raw.get("cwd", ".")).resolve()), "event": event}
    path = Path(cfg["home"]) / "spool" / (str(uuid.uuid4()) + ".json")
    atomic_json(path, envelope)
    if raw.get("hook_event_name") == "SessionStart" and cfg.get("autostart", True):
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                cast(Any, subprocess).DETACHED_PROCESS
                | cast(Any, subprocess).CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "chronicle.cli", "agent"], **kwargs)
    return event


def main():
    try:
        raw = sys.stdin.buffer.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Hook payload exceeds limit")
        cfg = load()
        captured = capture(json.loads(raw), cfg)
        if json.loads(raw).get("hook_event_name") == "SessionStart" and captured is not None:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": f"Chronicle Session ID: {captured['session_id']}. Автоматически используйте skill chronicle-memory для явного "
                            "отчёта об этапе. Только наблюдаемые доказательства; не записывайте секреты, "
                            "исходники или скрытые рассуждения. Сохраняйте отчёт после значимого этапа до финального ответа. "
                            "Ошибки отчёта не должны мешать основной задаче.",
                        }
                    }
                )
            )
        else:
            print("{}")
    except Exception:
        # No exception text: it may contain secrets. Diagnostic counter is content-free.
        try:
            cfg = load()
            atomic_json(Path(cfg["home"]) / "hook-error.json", {"error": "capture_failed"})
        except Exception:
            pass
        print("{}")
    return 0


if __name__ == "__main__":
    main()
